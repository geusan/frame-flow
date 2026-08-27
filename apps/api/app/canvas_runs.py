from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import CanvasNodeRunRecord, CanvasRunRecord, SessionLocal
from .domain import CanvasNodeRunResponse, CanvasRunRequest, CanvasRunResponse, ExperimentRunRequest, NodeStatus
from .experiments import run_experiment
from .service import new_id


def canvas_run_response(run: CanvasRunRecord) -> CanvasRunResponse:
    return CanvasRunResponse(
        id=run.id,
        created_at=run.created_at,
        canvas_id=run.canvas_id,
        name=run.name,
        status=run.status,
        progress=run.progress,
        graph=run.graph_snapshot or {},
        node_runs=[CanvasNodeRunResponse(
            id=node.id,
            created_at=node.created_at,
            canvas_node_id=node.canvas_node_id,
            node_key=node.node_key,
            status=node.status,
            progress=node.progress,
            attempt_count=node.attempt_count,
            provider_request_id=node.provider_request_id,
            provider_operation_id=node.provider_operation_id,
            request_hash=node.request_hash,
            output_artifact_ids=node.output_artifact_ids or [],
            output=node.output_payload or {},
            duration_ms=node.duration_ms,
            cost_usd=node.cost_usd,
            error=node.error,
        ) for node in run.node_runs],
    )


def create_canvas_run(db: Session, payload: CanvasRunRequest) -> CanvasRunRecord:
    node_ids = [str(node.get("id") or "") for node in payload.nodes]
    if any(not node_id for node_id in node_ids) or len(set(node_ids)) != len(node_ids):
        raise ValueError("Canvas node IDs must be present and unique")
    known = set(node_ids)
    edges = payload.edges
    if any(str(edge.get("source")) not in known or str(edge.get("target")) not in known for edge in edges):
        raise ValueError("Canvas edge references an unknown node")
    _assert_acyclic(node_ids, edges)
    run = CanvasRunRecord(
        id=new_id("canvasrun"),
        canvas_id=payload.canvas_id,
        name=payload.name,
        status=NodeStatus.READY,
        progress=0,
        graph_snapshot={"nodes": payload.nodes, "edges": payload.edges},
    )
    db.add(run)
    for ordinal, node in enumerate(payload.nodes):
        data = dict(node.get("data") or {})
        executable = data.get("executable") is not False
        db.add(CanvasNodeRunRecord(
            id=new_id("canvasnode"),
            run_id=run.id,
            canvas_node_id=str(node["id"]),
            node_key=str(data.get("key") or "unknown"),
            ordinal=ordinal,
            status=NodeStatus.BLOCKED if executable else NodeStatus.SUCCEEDED,
            progress=0 if executable else 100,
            attempt_count=0,
            output_artifact_ids=list(data.get("outputArtifactIds") or []),
            output_payload=dict(data.get("output") or {}),
        ))
    db.commit()
    db.refresh(run)
    return run


def execute_canvas_node(run_id: str, canvas_node_id: str) -> dict[str, Any]:
    with SessionLocal() as db:
        run = db.get(CanvasRunRecord, run_id)
        node = db.scalar(select(CanvasNodeRunRecord).where(CanvasNodeRunRecord.run_id == run_id, CanvasNodeRunRecord.canvas_node_id == canvas_node_id))
        if not run or not node:
            raise ValueError(f"Canvas run node was not found: {run_id}/{canvas_node_id}")
        if run.status == NodeStatus.CANCELED:
            raise RuntimeError("Canvas run was canceled")
        if node.status == NodeStatus.SUCCEEDED:
            return {"node_run_id": node.id, "artifact_ids": node.output_artifact_ids, "cache_hit": True}
        graph_node = _graph_node(run, canvas_node_id)
        data = dict(graph_node.get("data") or {})
        node.status = NodeStatus.RUNNING
        node.progress = 5
        node.attempt_count += 1
        node.error = None
        run.status = NodeStatus.RUNNING
        db.commit()
        experiment_payload = _experiment_payload(db, run, node, data)
        experiment = run_experiment(db, experiment_payload)
        db.refresh(run)
        db.refresh(node)
        if run.status == NodeStatus.CANCELED:
            node.status = NodeStatus.CANCELED
            db.commit()
            raise RuntimeError("Canvas run was canceled")
        if experiment.status != NodeStatus.SUCCEEDED:
            node.status = NodeStatus.FAILED
            node.progress = 0
            node.error = experiment.error or "Canvas node execution failed"
            run.status = NodeStatus.FAILED
            db.commit()
            raise RuntimeError(node.error)
        node.status = NodeStatus.SUCCEEDED
        node.progress = 100
        node.provider_request_id = experiment.provider_request_id
        node.request_hash = experiment.request_hash
        node.output_artifact_ids = list(experiment.output_artifact_ids or [])
        node.output_payload = dict(experiment.output_payload or {})
        node.duration_ms = experiment.duration_ms
        node.cost_usd = experiment.cost_usd
        run.progress = _run_progress(run)
        db.commit()
        return {"node_run_id": node.id, "artifact_ids": node.output_artifact_ids, "cache_hit": experiment.cache_hit}


def record_canvas_selection(run_id: str, canvas_node_id: str, artifact_id: str) -> None:
    with SessionLocal() as db:
        run = db.get(CanvasRunRecord, run_id)
        node = db.scalar(select(CanvasNodeRunRecord).where(CanvasNodeRunRecord.run_id == run_id, CanvasNodeRunRecord.canvas_node_id == canvas_node_id))
        if not run or not node or node.status != NodeStatus.WAITING_INPUT:
            raise ValueError("Canvas node is not waiting for candidate selection")
        incoming = _incoming_sources(run, canvas_node_id)
        source_nodes = db.scalars(select(CanvasNodeRunRecord).where(CanvasNodeRunRecord.run_id == run_id, CanvasNodeRunRecord.canvas_node_id.in_(incoming))).all()
        source = next((candidate for candidate in source_nodes if artifact_id in (candidate.output_artifact_ids or [])), None)
        if not source:
            raise ValueError("selected Artifact is not produced by a connected candidate node")
        node.status = NodeStatus.SUCCEEDED
        node.progress = 100
        node.output_artifact_ids = [artifact_id]
        node.output_payload = dict(source.output_payload or {})
        run.status = NodeStatus.RUNNING
        run.progress = _run_progress(run)
        db.commit()


def mark_canvas_waiting(run_id: str, canvas_node_id: str) -> None:
    with SessionLocal() as db:
        run = db.get(CanvasRunRecord, run_id)
        node = db.scalar(select(CanvasNodeRunRecord).where(CanvasNodeRunRecord.run_id == run_id, CanvasNodeRunRecord.canvas_node_id == canvas_node_id))
        if not run or not node:
            raise ValueError("Canvas run node was not found")
        node.status = NodeStatus.WAITING_INPUT
        node.progress = 100
        run.status = NodeStatus.WAITING_INPUT
        db.commit()


def finalize_canvas_run(run_id: str) -> None:
    with SessionLocal() as db:
        run = db.get(CanvasRunRecord, run_id)
        if not run or run.status == NodeStatus.CANCELED:
            return
        failed = any(node.status == NodeStatus.FAILED for node in run.node_runs)
        run.status = NodeStatus.FAILED if failed else NodeStatus.SUCCEEDED
        run.progress = _run_progress(run)
        db.commit()


class LocalCanvasRunEngine:
    def __init__(self) -> None:
        self.tasks: dict[str, asyncio.Task[None]] = {}

    async def start(self, run_id: str) -> None:
        existing = self.tasks.get(run_id)
        if existing and not existing.done():
            return
        task = asyncio.create_task(self._execute(run_id))
        self.tasks[run_id] = task
        task.add_done_callback(lambda _: self.tasks.pop(run_id, None))

    async def _execute(self, run_id: str) -> None:
        while True:
            with SessionLocal() as db:
                run = db.get(CanvasRunRecord, run_id)
                if not run or run.status in {NodeStatus.CANCELED, NodeStatus.FAILED, NodeStatus.SUCCEEDED}:
                    return
                dependencies = _dependencies(run)
                by_canvas_id = {node.canvas_node_id: node for node in run.node_runs}
                pending = [node for node in run.node_runs if node.status in {NodeStatus.BLOCKED, NodeStatus.READY}]
                ready = [node for node in pending if all(by_canvas_id[source].status == NodeStatus.SUCCEEDED for source in dependencies.get(node.canvas_node_id, []))]
                if not ready:
                    if any(node.status == NodeStatus.WAITING_INPUT for node in run.node_runs):
                        run.status = NodeStatus.WAITING_INPUT
                        db.commit()
                        return
                    if all(node.status == NodeStatus.SUCCEEDED for node in run.node_runs):
                        finalize_canvas_run(run_id)
                        return
                    run.status = NodeStatus.FAILED
                    db.commit()
                    return
                candidate_nodes = [node for node in ready if node.node_key == "candidate.select"]
                executable = [node.canvas_node_id for node in ready if node.node_key != "candidate.select"]
                for candidate in candidate_nodes:
                    candidate.status = NodeStatus.WAITING_INPUT
                    candidate.progress = 100
                if candidate_nodes:
                    run.status = NodeStatus.WAITING_INPUT
                db.commit()
            if executable:
                results = await asyncio.gather(
                    *(asyncio.to_thread(execute_canvas_node, run_id, node_id) for node_id in executable),
                    return_exceptions=True,
                )
                if any(isinstance(result, Exception) for result in results):
                    with SessionLocal() as db:
                        run = db.get(CanvasRunRecord, run_id)
                        if run and run.status != NodeStatus.CANCELED:
                            run.status = NodeStatus.FAILED
                            db.commit()
                    return
                continue
            return


local_canvas_engine = LocalCanvasRunEngine()


def _experiment_payload(db: Session, run: CanvasRunRecord, node: CanvasNodeRunRecord, data: dict[str, Any]) -> ExperimentRunRequest:
    inputs: list[dict[str, Any]] = []
    prompt = str(data.get("configText") or data.get("description") or "")
    node_by_canvas_id = {item.canvas_node_id: item for item in run.node_runs}
    graph_nodes = {str(item.get("id")): dict(item.get("data") or {}) for item in (run.graph_snapshot or {}).get("nodes", [])}
    for edge in (run.graph_snapshot or {}).get("edges", []):
        if str(edge.get("target")) != node.canvas_node_id:
            continue
        source_id = str(edge.get("source"))
        source = node_by_canvas_id[source_id]
        source_data = graph_nodes[source_id]
        if source_data.get("key") == "prompt.input":
            prompt = str(source_data.get("configText") or "")
        inputs.append({
            "node_id": source_id,
            "node_key": source.node_key,
            "type": source_data.get("outputType") or "Any",
            "label": source_data.get("label") or source_id,
            "description": source_data.get("description"),
            "config_text": source_data.get("configText"),
            "output_title": (source.output_payload or {}).get("title"),
            "output_text": (source.output_payload or {}).get("text"),
            "mime_type": (source.output_payload or {}).get("mimeType"),
            "artifact_ids": source.output_artifact_ids or [],
        })
    parameters = dict(data.get("parameters") or {})
    parameters.setdefault("resolution", data.get("resolution"))
    parameters.setdefault("aspect_ratio", data.get("aspectRatio"))
    parameters.setdefault("transition", data.get("transition"))
    parameters.setdefault("target_duration_seconds", data.get("targetDurationSeconds"))
    parameters.setdefault("source_language", data.get("sourceLanguage"))
    parameters.setdefault("target_language", data.get("targetLanguage"))
    parameters.setdefault("voice_name", data.get("voiceName"))
    parameters.setdefault("provider", data.get("provider"))
    return ExperimentRunRequest(
        canvas_id=run.canvas_id,
        node_id=node.canvas_node_id,
        node_key=node.node_key,
        prompt=prompt,
        model_alias=str(data.get("model") or "local"),
        parameters=parameters,
        inputs=inputs,
    )


def _graph_node(run: CanvasRunRecord, canvas_node_id: str) -> dict[str, Any]:
    return next(node for node in (run.graph_snapshot or {}).get("nodes", []) if str(node.get("id")) == canvas_node_id)


def _incoming_sources(run: CanvasRunRecord, target_id: str) -> list[str]:
    return [str(edge.get("source")) for edge in (run.graph_snapshot or {}).get("edges", []) if str(edge.get("target")) == target_id]


def _dependencies(run: CanvasRunRecord) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {node.canvas_node_id: [] for node in run.node_runs}
    for edge in (run.graph_snapshot or {}).get("edges", []):
        result[str(edge.get("target"))].append(str(edge.get("source")))
    return result


def _run_progress(run: CanvasRunRecord) -> int:
    if not run.node_runs:
        return 0
    complete = sum(node.status in {NodeStatus.SUCCEEDED, NodeStatus.FAILED, NodeStatus.CANCELED} for node in run.node_runs)
    return round(complete / len(run.node_runs) * 100)


def _assert_acyclic(node_ids: list[str], edges: list[dict[str, Any]]) -> None:
    indegree = {node_id: 0 for node_id in node_ids}
    outgoing = {node_id: [] for node_id in node_ids}
    for edge in edges:
        source, target = str(edge.get("source")), str(edge.get("target"))
        outgoing[source].append(target)
        indegree[target] += 1
    queue = [node_id for node_id, value in indegree.items() if value == 0]
    visited = 0
    while queue:
        source = queue.pop()
        visited += 1
        for target in outgoing[source]:
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)
    if visited != len(node_ids):
        raise ValueError("Canvas graph contains a cycle")
