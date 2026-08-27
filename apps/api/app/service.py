from __future__ import annotations

import asyncio
import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qs, urlparse, urlunparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from .compiler import DEFAULT_NODES
from .database import ArtifactRecord, AuditEventRecord, NodeRunRecord, RunRecord, SessionLocal
from .domain import ArtifactResponse, EventResponse, NodeRunResponse, NodeStatus, RunResponse
from .providers import MockGoogleProvider
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


def source_id_for(url: str) -> str:
    parsed = urlparse(url)
    video_id = parse_qs(parsed.query).get("v", [None])[0]
    if video_id:
        return video_id
    slug = parsed.path.rstrip("/").split("/")[-1]
    return slug or hashlib.sha256(url.encode()).hexdigest()[:12]


def create_artifact(
    db: Session,
    artifact_type: str,
    *,
    schema_id: str | None = None,
    producer_node_run_id: str | None = None,
    input_artifact_ids: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    content_seed: str | None = None,
    content: bytes | None = None,
    content_type: str | None = None,
    filename: str | None = None,
) -> ArtifactRecord:
    artifact_id = new_id("art")
    artifact_metadata = dict(metadata or {})
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
        input_artifact_ids=input_artifact_ids or [],
        metadata_json=artifact_metadata,
    )
    db.add(artifact)
    return artifact


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


class DemoRunEngine:
    """Durable-state demo engine. Temporal replaces this scheduler in production."""

    WAIT_INDEX = 7

    async def start(self, run_id: str) -> None:
        task = asyncio.create_task(self._execute(run_id))
        active_tasks.add(task)
        task.add_done_callback(active_tasks.discard)

    async def _execute(self, run_id: str) -> None:
        for ordinal, (node_key, pool, estimated_cost) in enumerate(DEFAULT_NODES):
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
                node.status = NodeStatus.RUNNING
                node.attempt_count += 1
                run.status = NodeStatus.RUNNING
                db.commit()
                await broker.publish(EventResponse(event="node.running", run_id=run_id, data={"node_run_id": node.id, "node_key": node.node_key}))

            await asyncio.sleep(0.35)
            with SessionLocal() as db:
                run = db.get(RunRecord, run_id)
                node = db.scalar(select(NodeRunRecord).where(NodeRunRecord.run_id == run_id, NodeRunRecord.ordinal == ordinal))
                if not run or not node or run.status == NodeStatus.CANCELED:
                    return
                if pool.startswith("google"):
                    submission = MockGoogleProvider(pool).submit({"run_id": run_id, "node_key": node_key}, node.id)
                    node.provider_request_id = submission.provider_request_id
                    node.provider_operation_id = submission.provider_operation_id
                    node.request_hash = submission.request_hash
                artifact_types = {
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
                if node_key in artifact_types:
                    artifact_type, schema_id = artifact_types[node_key]
                    artifact = create_artifact(db, artifact_type, schema_id=schema_id, producer_node_run_id=node.id, content_seed=f"{run_id}:{node_key}:{node.attempt_count}", metadata={"immutable": True, "mock_provider": True})
                    db.flush()
                    node.output_artifact_ids = [artifact.id]
                node.status = NodeStatus.SUCCEEDED
                node.progress = 100
                node.cost_usd = estimated_cost
                run.actual_cost_usd = round(run.actual_cost_usd + estimated_cost, 2)
                run.progress = min(99, round((ordinal + 1) / len(DEFAULT_NODES) * 100))
                db.commit()
                await broker.publish(EventResponse(event="node.succeeded", run_id=run_id, data={"node_run_id": node.id, "node_key": node.node_key, "artifact_ids": node.output_artifact_ids}))

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
            selection = create_artifact(db, "SelectionArtifact", schema_id="selection.v1", producer_node_run_id=node.id, input_artifact_ids=[selected_artifact_id], metadata={"selected_artifact_id": selected_artifact_id})
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


demo_engine = DemoRunEngine()
