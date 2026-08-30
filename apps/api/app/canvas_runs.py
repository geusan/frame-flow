from __future__ import annotations

import asyncio
import copy
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


def record_canvas_approval(run_id: str, canvas_node_id: str, parameters: dict[str, Any]) -> None:
    with SessionLocal() as db:
        run = db.get(CanvasRunRecord, run_id)
        node = db.scalar(select(CanvasNodeRunRecord).where(CanvasNodeRunRecord.run_id == run_id, CanvasNodeRunRecord.canvas_node_id == canvas_node_id))
        if not run or not node or node.status != NodeStatus.WAITING_INPUT:
            raise ValueError("Canvas node is not waiting for input approval")
        graph = copy.deepcopy(run.graph_snapshot or {})
        graph_node = next((item for item in graph.get("nodes", []) if str(item.get("id")) == canvas_node_id), None)
        if not graph_node:
            raise ValueError("Canvas graph node was not found")
        data = dict(graph_node.get("data") or {})
        if data.get("waitForInput") is not True:
            raise ValueError("Canvas node does not accept workflow input approval")
        allowed = {
            "caption_x": "captionX",
            "caption_y": "captionY",
            "caption_align": "captionAlign",
            "caption_font_size": "captionFontSize",
        }
        for source_key, target_key in allowed.items():
            if source_key in parameters:
                data[target_key] = parameters[source_key]
        data["inputApproved"] = True
        graph_node["data"] = data
        run.graph_snapshot = graph
        node.status = NodeStatus.BLOCKED
        node.progress = 0
        run.status = NodeStatus.RUNNING
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
                dependencies = canvas_dependencies(run)
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
                approval_nodes = [node for node in ready if _canvas_node_requires_input(run, node)]
                waiting_ids = {node.canvas_node_id for node in [*candidate_nodes, *approval_nodes]}
                executable = [node.canvas_node_id for node in ready if node.canvas_node_id not in waiting_ids]
                for waiting_node in [*candidate_nodes, *approval_nodes]:
                    waiting_node.status = NodeStatus.WAITING_INPUT
                    waiting_node.progress = 100
                if waiting_ids:
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
    seen_input_ids: set[str] = set()
    prompt = str(data.get("configText") or data.get("description") or "")
    node_by_canvas_id = {item.canvas_node_id: item for item in run.node_runs}
    graph_nodes = {str(item.get("id")): dict(item.get("data") or {}) for item in (run.graph_snapshot or {}).get("nodes", [])}

    def append_input(source_id: str) -> None:
        if source_id in seen_input_ids:
            return
        seen_input_ids.add(source_id)
        source = node_by_canvas_id[source_id]
        source_data = graph_nodes[source_id]
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

    def append_prompt_ancestors(source_id: str) -> None:
        for prompt_edge in (run.graph_snapshot or {}).get("edges", []):
            if str(prompt_edge.get("target")) != source_id:
                continue
            ancestor_id = str(prompt_edge.get("source"))
            append_input(ancestor_id)
            if graph_nodes[ancestor_id].get("outputType") == "Prompt":
                append_prompt_ancestors(ancestor_id)

    def resolve_prompt_text(source_id: str, visited: set[str] | None = None) -> str:
        visited = set() if visited is None else visited
        if source_id in visited:
            return ""
        visited.add(source_id)
        source_data = graph_nodes[source_id]
        source_run = node_by_canvas_id[source_id]
        current = str(source_data.get("configText") or (source_run.output_payload or {}).get("text") or "").strip()
        if current:
            return current
        for prompt_edge in (run.graph_snapshot or {}).get("edges", []):
            if str(prompt_edge.get("target")) != source_id:
                continue
            ancestor_id = str(prompt_edge.get("source"))
            if graph_nodes[ancestor_id].get("outputType") != "Prompt":
                continue
            inherited = resolve_prompt_text(ancestor_id, visited)
            if inherited:
                return inherited
        return ""

    for edge in (run.graph_snapshot or {}).get("edges", []):
        if str(edge.get("target")) != node.canvas_node_id:
            continue
        source_id = str(edge.get("source"))
        source_data = graph_nodes[source_id]
        if source_data.get("outputType") == "Prompt":
            prompt = resolve_prompt_text(source_id)
        if source_data.get("outputType") == "Prompt":
            append_prompt_ancestors(source_id)
        append_input(source_id)
    parameters = dict(data.get("parameters") or {})
    parameters.setdefault("resolution", data.get("resolution"))
    parameters.setdefault("aspect_ratio", data.get("aspectRatio"))
    parameters.setdefault("transition", data.get("transition"))
    parameters.setdefault("target_duration_seconds", data.get("targetDurationSeconds"))
    parameters.setdefault("source_language", data.get("sourceLanguage"))
    parameters.setdefault("separate_music", data.get("separateMusic"))
    parameters.setdefault("scene_threshold", data.get("sceneThreshold"))
    parameters.setdefault("target_language", data.get("targetLanguage"))
    parameters.setdefault("voice_name", data.get("voiceName"))
    parameters.setdefault("caption_x", data.get("captionX"))
    parameters.setdefault("caption_y", data.get("captionY"))
    parameters.setdefault("caption_align", data.get("captionAlign"))
    parameters.setdefault("caption_font_size", data.get("captionFontSize"))
    parameters.setdefault("skill_id", data.get("skillId"))
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


def _canvas_node_requires_input(run: CanvasRunRecord, node: CanvasNodeRunRecord) -> bool:
    data = dict(_graph_node(run, node.canvas_node_id).get("data") or {})
    return data.get("waitForInput") is True and data.get("inputApproved") is not True


def _incoming_sources(run: CanvasRunRecord, target_id: str) -> list[str]:
    return [str(edge.get("source")) for edge in (run.graph_snapshot or {}).get("edges", []) if str(edge.get("target")) == target_id]


def canvas_dependencies(run: CanvasRunRecord) -> dict[str, list[str]]:
    direct: dict[str, list[str]] = {node.canvas_node_id: [] for node in run.node_runs}
    for edge in (run.graph_snapshot or {}).get("edges", []):
        direct[str(edge.get("target"))].append(str(edge.get("source")))
    graph_nodes = {str(item.get("id")): dict(item.get("data") or {}) for item in (run.graph_snapshot or {}).get("nodes", [])}

    def expanded(source_id: str, visited: set[str] | None = None) -> list[str]:
        visited = set() if visited is None else visited
        if source_id in visited:
            return []
        visited.add(source_id)
        dependencies = [source_id]
        if graph_nodes[source_id].get("executable") is False:
            for ancestor_id in direct.get(source_id, []):
                dependencies.extend(expanded(ancestor_id, visited))
        return dependencies

    result: dict[str, list[str]] = {}
    for target_id, source_ids in direct.items():
        result[target_id] = list(dict.fromkeys(dependency for source_id in source_ids for dependency in expanded(source_id)))
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
