from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy import select
from temporalio import activity

from .compiler import DEFAULT_NODES
from .database import NodeRunRecord, RunRecord, SessionLocal
from .domain import NodeStatus
from .providers import MockGoogleProvider
from .service import audit, create_artifact


NODE_COST = {node_key: cost for node_key, _pool, cost in DEFAULT_NODES}
NODE_POOL = {node_key: pool for node_key, pool, _cost in DEFAULT_NODES}
ARTIFACT_TYPES: dict[str, tuple[str, str | None]] = {
    "generation.resolve": ("GenerationSpec", "generation.spec.v1"),
    "script.generate": ("Script", "script.v1"),
    "script.fit_duration": ("TimedScript", "script.timed.v1"),
    "shot.plan": ("ShotPlan", "shot.plan.v1"),
    "image.generate": ("ImageList", "image.candidates.v1"),
    "video.generate": ("VideoClipList", "video.candidates.v1"),
    "tts.generate": ("Audio", None),
    "subtitle.align": ("Subtitle", "subtitle.ass.v1"),
    "timeline.compose": ("Timeline", "timeline.v1"),
    "video.render": ("Video", None),
    "media.qc": ("QCReport", "qc.report.v1"),
}


def _get_node(run_id: str, node_key: str) -> tuple[RunRecord, NodeRunRecord]:
    db = SessionLocal()
    run = db.get(RunRecord, run_id)
    node = db.scalar(select(NodeRunRecord).where(NodeRunRecord.run_id == run_id, NodeRunRecord.node_key == node_key))
    if not run or not node:
        db.close()
        raise ValueError(f"run or node was not found: {run_id}/{node_key}")
    db.expunge(run)
    db.expunge(node)
    db.close()
    return run, node


@activity.defn(name="execute_node")
async def execute_node(run_id: str, node_key: str) -> dict[str, Any]:
    _get_node(run_id, node_key)
    with SessionLocal() as db:
        run = db.get(RunRecord, run_id)
        node = db.scalar(select(NodeRunRecord).where(NodeRunRecord.run_id == run_id, NodeRunRecord.node_key == node_key))
        if not run or not node:
            raise ValueError("run or node disappeared")
        if run.status == NodeStatus.CANCELED:
            raise asyncio.CancelledError
        if node.status == NodeStatus.SUCCEEDED:
            return {"node_run_id": node.id, "artifact_ids": node.output_artifact_ids, "cache_hit": True}
        node.status = NodeStatus.RUNNING
        node.attempt_count += 1
        run.status = NodeStatus.RUNNING
        db.commit()

    activity.heartbeat({"stage": "executing", "node_key": node_key})
    await asyncio.sleep(0.05)

    with SessionLocal() as db:
        run = db.get(RunRecord, run_id)
        node = db.scalar(select(NodeRunRecord).where(NodeRunRecord.run_id == run_id, NodeRunRecord.node_key == node_key))
        if not run or not node:
            raise ValueError("run or node disappeared")
        pool = NODE_POOL[node_key]
        if pool.startswith("google") and not node.provider_request_id:
            submission = MockGoogleProvider(pool).submit({"run_id": run_id, "node_key": node_key}, node.id)
            node.provider_request_id = submission.provider_request_id
            node.provider_operation_id = submission.provider_operation_id
            node.request_hash = submission.request_hash
        if node_key in ARTIFACT_TYPES and not node.output_artifact_ids:
            artifact_type, schema_id = ARTIFACT_TYPES[node_key]
            artifact = create_artifact(db, artifact_type, schema_id=schema_id, producer_node_run_id=node.id, content_seed=f"{run_id}:{node_key}:{node.attempt_count}", metadata={"immutable": True, "execution_backend": "temporal"})
            db.flush()
            node.output_artifact_ids = [artifact.id]
        node.status = NodeStatus.SUCCEEDED
        node.progress = 100
        node.cost_usd = NODE_COST[node_key]
        run.actual_cost_usd = round(sum(item.cost_usd for item in run.node_runs), 2)
        run.progress = min(99, round((node.ordinal + 1) / len(DEFAULT_NODES) * 100))
        db.commit()
        return {"node_run_id": node.id, "artifact_ids": node.output_artifact_ids, "cache_hit": False}


@activity.defn(name="mark_waiting_input")
async def mark_waiting_input(run_id: str, node_key: str) -> None:
    with SessionLocal() as db:
        run = db.get(RunRecord, run_id)
        node = db.scalar(select(NodeRunRecord).where(NodeRunRecord.run_id == run_id, NodeRunRecord.node_key == node_key))
        if not run or not node:
            raise ValueError("run or node not found")
        run.status = NodeStatus.WAITING_INPUT
        node.status = NodeStatus.WAITING_INPUT
        db.commit()


@activity.defn(name="record_candidate_selection")
async def record_candidate_selection(run_id: str, node_key: str, selected_artifact_id: str) -> str:
    with SessionLocal() as db:
        run = db.get(RunRecord, run_id)
        node = db.scalar(select(NodeRunRecord).where(NodeRunRecord.run_id == run_id, NodeRunRecord.node_key == node_key))
        if not run or not node:
            raise ValueError("run or node not found")
        selection = create_artifact(db, "SelectionArtifact", schema_id="selection.v1", producer_node_run_id=node.id, input_artifact_ids=[selected_artifact_id], metadata={"selected_artifact_id": selected_artifact_id})
        db.flush()
        node.output_artifact_ids = [selection.id]
        node.status = NodeStatus.SUCCEEDED
        node.progress = 100
        run.status = NodeStatus.RUNNING
        audit(db, "candidate.selected", node.id, {"selected_artifact_id": selected_artifact_id})
        db.commit()
        return selection.id


@activity.defn(name="finalize_run")
async def finalize_run(run_id: str) -> None:
    with SessionLocal() as db:
        run = db.get(RunRecord, run_id)
        if not run:
            raise ValueError("run not found")
        run.status = NodeStatus.SUCCEEDED
        run.progress = 100
        audit(db, "run.succeeded", run.id, {"execution_backend": "temporal"})
        db.commit()
