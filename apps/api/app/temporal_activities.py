from __future__ import annotations

import asyncio
import json
from typing import Any

from sqlalchemy import select
from temporalio import activity

from .database import NodeRunRecord, RunRecord, SessionLocal
from .domain import NodeStatus
from .service import audit, create_artifact
from .workflow_execution import execute_workflow_node


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
    task = asyncio.create_task(asyncio.to_thread(execute_workflow_node, run_id, node_key))
    while not task.done():
        activity.heartbeat({"stage": "executing", "node_key": node_key})
        done, _ = await asyncio.wait({task}, timeout=20)
        if done:
            break
    return await task


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
        video_node = db.scalar(select(NodeRunRecord).where(NodeRunRecord.run_id == run_id, NodeRunRecord.node_key == "video.generate"))
        if not video_node or selected_artifact_id not in (video_node.output_artifact_ids or []):
            raise ValueError("selected artifact is not a candidate produced by this run")
        content = json.dumps({"version": "selection.v1", "selected_artifact_id": selected_artifact_id}, sort_keys=True).encode()
        selection = create_artifact(db, "SelectionArtifact", schema_id="selection.v1", producer_node_run_id=node.id, input_artifact_ids=[selected_artifact_id], metadata={"selected_artifact_id": selected_artifact_id}, content=content, content_type="application/json", filename="selection.json")
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
