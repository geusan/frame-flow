from __future__ import annotations

import asyncio
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qs, urlparse, urlunparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from .compiler import DEFAULT_NODES
from .database import ArtifactEdgeRecord, ArtifactRecord, AuditEventRecord, NodeRunRecord, RunRecord, SessionLocal
from .domain import ArtifactResponse, EventResponse, NodeRunResponse, NodeStatus, RunResponse
from .storage import artifact_object_key, bucket_for_artifact, get_storage


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:18]}"


def canonicalize_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("only HTTP(S) URLs are supported")
    if parsed.hostname in {"localhost", "127.0.0.1", "0.0.0.0", "::1"}:
        raise ValueError("local and private destinations are blocked")
    query = parse_qs(parsed.query)
    safe_query = ""
    if "v" in query:
        safe_query = f"v={query['v'][0]}"
    return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/"), "", safe_query, ""))


def create_artifact(
    db: Session,
    artifact_type: str,
    *,
    schema_id: str | None = None,
    producer_node_run_id: str | None = None,
    input_artifact_ids: list[str] | None = None,
    input_artifact_roles: dict[str, str] | None = None,
    metadata: dict[str, Any] | None = None,
    content_seed: str | None = None,
    content: bytes | None = None,
    content_type: str | None = None,
    filename: str | None = None,
) -> ArtifactRecord:
    artifact_id = new_id("art")
    artifact_metadata = dict(metadata or {})
    normalized_input_ids = list(dict.fromkeys(input_artifact_ids or []))
    normalized_roles = {
        parent_id: str((input_artifact_roles or {}).get(parent_id) or "input")[:64]
        for parent_id in normalized_input_ids
    }
    if normalized_input_ids:
        artifact_metadata["input_artifact_roles"] = normalized_roles
    if content is None:
        content_type = "application/json"
        content = json.dumps(
            {
                "type": artifact_type,
                "schema_id": schema_id,
                "metadata": artifact_metadata,
                "content_seed": content_seed,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        filename = filename or "artifact.json"
    content_type = content_type or "application/octet-stream"
    storage = get_storage()
    bucket = bucket_for_artifact(storage.settings, artifact_type, artifact_metadata)
    key = artifact_object_key(artifact_type, artifact_id, content_type, filename)
    stored = storage.put_bytes(
        bucket=bucket,
        key=key,
        data=content,
        content_type=content_type,
        metadata={"artifact-id": artifact_id, "artifact-type": artifact_type.lower()},
    )
    artifact_metadata["storage"] = {
        "provider": stored.provider,
        "bucket": stored.bucket,
        "key": stored.key,
        "content_type": stored.content_type,
        "size_bytes": stored.size_bytes,
        "etag": stored.etag,
    }
    artifact = ArtifactRecord(
        id=artifact_id,
        type=artifact_type,
        schema_id=schema_id,
        uri=stored.uri,
        sha256=stored.sha256,
        producer_node_run_id=producer_node_run_id,
        input_artifact_ids=normalized_input_ids,
        metadata_json=artifact_metadata,
    )
    db.add(artifact)
    persistent_parent_ids = set(db.scalars(
        select(ArtifactRecord.id).where(ArtifactRecord.id.in_(normalized_input_ids))
    ).all()) if normalized_input_ids else set()
    pending_parent_ids = {
        record.id for record in db.new if isinstance(record, ArtifactRecord)
    }
    known_parent_ids = persistent_parent_ids | pending_parent_ids
    operation_id = str(
        producer_node_run_id
        or artifact_metadata.get("experiment_id")
        or (artifact_metadata.get("capture") or {}).get("operation")
        or artifact_metadata.get("operation")
        or ""
    )[:64] or None
    for ordinal, parent_artifact_id in enumerate(normalized_input_ids):
        if parent_artifact_id not in known_parent_ids:
            continue
        db.add(ArtifactEdgeRecord(
            id=new_id("edge"),
            parent_artifact_id=parent_artifact_id,
            child_artifact_id=artifact_id,
            role=normalized_roles[parent_artifact_id],
            ordinal=ordinal,
            operation_id=operation_id,
            metadata_json={},
        ))
    return artifact


def backfill_artifact_edges(db: Session) -> int:
    known_artifact_ids = set(db.scalars(select(ArtifactRecord.id)).all())
    existing = {
        (parent_id, child_id, role, ordinal)
        for parent_id, child_id, role, ordinal in db.execute(
            select(
                ArtifactEdgeRecord.parent_artifact_id,
                ArtifactEdgeRecord.child_artifact_id,
                ArtifactEdgeRecord.role,
                ArtifactEdgeRecord.ordinal,
            )
        ).all()
    }
    created = 0
    for artifact in db.scalars(select(ArtifactRecord)).all():
        input_ids = list(dict.fromkeys(artifact.input_artifact_ids or []))
        roles = artifact.metadata_json.get("input_artifact_roles") or {}
        operation_id = str(
            artifact.producer_node_run_id
            or artifact.metadata_json.get("experiment_id")
            or (artifact.metadata_json.get("capture") or {}).get("operation")
            or artifact.metadata_json.get("operation")
            or ""
        )[:64] or None
        for ordinal, parent_artifact_id in enumerate(input_ids):
            if parent_artifact_id not in known_artifact_ids:
                continue
            role = str(roles.get(parent_artifact_id) or "input")[:64]
            key = (parent_artifact_id, artifact.id, role, ordinal)
            if key in existing:
                continue
            db.add(ArtifactEdgeRecord(
                id=new_id("edge"),
                parent_artifact_id=parent_artifact_id,
                child_artifact_id=artifact.id,
                role=role,
                ordinal=ordinal,
                operation_id=operation_id,
                metadata_json={"backfilled": True},
            ))
            existing.add(key)
            created += 1
    return created


def artifact_response(record: ArtifactRecord) -> ArtifactResponse:
    return ArtifactResponse(
        id=record.id,
        created_at=record.created_at,
        type=record.type,
        schema_id=record.schema_id,
        uri=record.uri,
        sha256=record.sha256,
        producer_node_run_id=record.producer_node_run_id,
        input_artifact_ids=record.input_artifact_ids or [],
        metadata=record.metadata_json or {},
    )


def node_response(record: NodeRunRecord) -> NodeRunResponse:
    return NodeRunResponse(
        id=record.id,
        created_at=record.created_at,
        run_id=record.run_id,
        node_key=record.node_key,
        status=record.status,
        progress=record.progress,
        cost_usd=record.cost_usd,
        provider_request_id=record.provider_request_id,
        provider_operation_id=record.provider_operation_id,
        attempt_count=record.attempt_count,
        output_artifact_ids=record.output_artifact_ids or [],
    )


def run_response(record: RunRecord) -> RunResponse:
    return RunResponse(
        id=record.id,
        created_at=record.created_at,
        name=record.name,
        status=record.status,
        progress=record.progress,
        estimated_cost_usd=record.estimated_cost_usd,
        actual_cost_usd=record.actual_cost_usd,
        budget_limit_usd=record.budget_limit_usd,
        execution_plan=record.execution_plan,
        node_runs=[node_response(node) for node in record.node_runs],
    )


def audit(db: Session, action: str, subject_id: str, payload: dict[str, Any] | None = None) -> None:
    db.add(AuditEventRecord(id=new_id("audit"), action=action, subject_id=subject_id, payload=payload or {}))


class EventBroker:
    def __init__(self) -> None:
        self._events: dict[str, list[EventResponse]] = {}
        self._conditions: dict[str, asyncio.Condition] = {}

    async def publish(self, event: EventResponse) -> None:
        self._events.setdefault(event.run_id, []).append(event)
        condition = self._conditions.setdefault(event.run_id, asyncio.Condition())
        async with condition:
            condition.notify_all()

    def snapshot(self, run_id: str, offset: int = 0) -> list[EventResponse]:
        return self._events.get(run_id, [])[offset:]

    async def wait(self, run_id: str, timeout: float = 15) -> None:
        condition = self._conditions.setdefault(run_id, asyncio.Condition())
        try:
            async with condition:
                await asyncio.wait_for(condition.wait(), timeout)
        except TimeoutError:
            pass


broker = EventBroker()
active_tasks: set[asyncio.Task[None]] = set()


class LocalRunEngine:
    """Local async scheduler that executes the same real node contract as Temporal."""

    WAIT_INDEX = 7

    async def start(self, run_id: str) -> None:
        task = asyncio.create_task(self._execute(run_id))
        active_tasks.add(task)
        task.add_done_callback(active_tasks.discard)

    async def _execute(self, run_id: str) -> None:
        from .workflow_execution import execute_workflow_node

        for ordinal, (node_key, _pool, _estimated_cost) in enumerate(DEFAULT_NODES):
            with SessionLocal() as db:
                run = db.get(RunRecord, run_id)
                if not run or run.status == NodeStatus.CANCELED:
                    return
                node = db.scalar(select(NodeRunRecord).where(NodeRunRecord.run_id == run_id, NodeRunRecord.ordinal == ordinal))
                if not node:
                    return
                if node.status == NodeStatus.SUCCEEDED:
                    continue
                if ordinal == self.WAIT_INDEX:
                    node.status = NodeStatus.WAITING_INPUT
                    run.status = NodeStatus.WAITING_INPUT
                    run.progress = 67
                    db.commit()
                    await broker.publish(EventResponse(event="node.waiting_input", run_id=run_id, data={"node_run_id": node.id, "node_key": node.node_key}))
                    return
                node_id = node.id
            await broker.publish(EventResponse(event="node.running", run_id=run_id, data={"node_run_id": node_id, "node_key": node_key}))
            try:
                result = await asyncio.to_thread(execute_workflow_node, run_id, node_key)
            except Exception as exc:
                with SessionLocal() as db:
                    run = db.get(RunRecord, run_id)
                    node = db.get(NodeRunRecord, node_id)
                    if run and node:
                        node.status = NodeStatus.FAILED
                        run.status = NodeStatus.FAILED
                        audit(db, "node.failed", node.id, {"error": str(exc), "node_key": node_key})
                        db.commit()
                await broker.publish(EventResponse(event="node.failed", run_id=run_id, data={"node_run_id": node_id, "node_key": node_key, "error": str(exc)}))
                return
            await broker.publish(EventResponse(event="node.succeeded", run_id=run_id, data={"node_run_id": node_id, "node_key": node_key, "artifact_ids": result["artifact_ids"]}))

        with SessionLocal() as db:
            run = db.get(RunRecord, run_id)
            if run and run.status != NodeStatus.CANCELED:
                run.status = NodeStatus.SUCCEEDED
                run.progress = 100
                audit(db, "run.succeeded", run_id)
                db.commit()
        await broker.publish(EventResponse(event="run.succeeded", run_id=run_id, data={"progress": 100}))

    async def resume_after_selection(self, run_id: str, node_run_id: str, selected_artifact_id: str) -> None:
        with SessionLocal() as db:
            run = db.get(RunRecord, run_id)
            node = db.get(NodeRunRecord, node_run_id)
            if not run or not node or node.status != NodeStatus.WAITING_INPUT:
                raise ValueError("node is not waiting for input")
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
            run.progress = 68
            audit(db, "candidate.selected", node_run_id, {"selected_artifact_id": selected_artifact_id})
            db.commit()
        await broker.publish(EventResponse(event="candidate.selected", run_id=run_id, data={"node_run_id": node_run_id, "selected_artifact_id": selected_artifact_id}))
        await self.start(run_id)


local_engine = LocalRunEngine()
