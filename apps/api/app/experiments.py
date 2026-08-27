from __future__ import annotations

import hashlib
import html
import json
import time
from dataclasses import dataclass
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import ExperimentRunRecord
from .domain import ExperimentRunRequest, ExperimentRunResponse, NodeStatus
from .providers import MODEL_REGISTRY
from .service import audit, create_artifact, new_id


MODEL_COSTS = {
    "google.text.fast": 0.01,
    "google.text.quality": 0.03,
    "google.image.fast": 0.21,
    "google.image.quality": 0.42,
    "google.video.fast": 1.40,
    "google.video.quality": 2.80,
    "google.tts.fast": 0.12,
}
EXECUTOR_REVISION = "deterministic-experiment.v1"


def resolve_model(model_alias: str) -> tuple[str, str]:
    normalized = model_alias if model_alias.startswith("google.") else f"google.{model_alias}"
    exact = MODEL_REGISTRY.get(normalized)
    if not exact:
        raise ValueError(f"model alias is not registered: {model_alias}")
    return normalized, exact


def validate_model_for_node(node_key: str, model_alias: str) -> None:
    expected_family = {
        "image.generate": "google.image.",
        "video.generate": "google.video.",
        "tts.generate": "google.tts.",
        "llm.assistant": "google.text.",
        "script.generate": "google.text.",
    }.get(node_key)
    if expected_family and not model_alias.startswith(expected_family):
        raise ValueError(f"{node_key} requires a {expected_family.removesuffix('.')} model")


def request_fingerprint(payload: ExperimentRunRequest, model_alias: str, exact_model_id: str) -> str:
    snapshot = {
        "executor_revision": EXECUTOR_REVISION,
        "node_key": payload.node_key,
        "prompt": payload.prompt,
        "model_alias": model_alias,
        "exact_model_id": exact_model_id,
        "parameters": payload.parameters,
        "inputs": payload.inputs,
    }
    encoded = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def _poster(prompt: str, exact_model_id: str, digest: str) -> str:
    title = html.escape(prompt.strip()[:56] or "Untitled experiment")
    model = html.escape(exact_model_id)
    hue = int(digest[:4], 16) % 360
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 720 960">
    <defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop stop-color="hsl({hue} 42% 20%)"/><stop offset="1" stop-color="hsl({(hue + 70) % 360} 48% 50%)"/></linearGradient></defs>
    <rect width="720" height="960" fill="url(#g)"/><circle cx="570" cy="180" r="230" fill="#fff" opacity=".1"/>
    <path d="M0 760 C170 610 320 760 480 570 S650 500 720 420 V960 H0Z" fill="#090b10" opacity=".48"/>
    <text x="48" y="820" fill="#fff" font-family="Arial,sans-serif" font-size="34" font-weight="700">{title}</text>
    <text x="50" y="872" fill="#fff" opacity=".72" font-family="Arial,sans-serif" font-size="20">{model}</text>
    <text x="50" y="910" fill="#fff" opacity=".52" font-family="monospace" font-size="16">experiment {digest[:12]}</text>
    </svg>'''
    return f"data:image/svg+xml;charset=UTF-8,{quote(svg)}"


@dataclass(frozen=True)
class DeterministicResult:
    output: dict[str, object]
    artifact_type: str
    schema_id: str | None
    provider_request_id: str


def execute_deterministic(payload: ExperimentRunRequest, exact_model_id: str, digest: str) -> DeterministicResult:
    provider_request_id = f"local_{digest[:20]}"
    if payload.node_key == "image.generate":
        output = {"kind": "image", "title": "Experiment image", "url": _poster(payload.prompt, exact_model_id, digest), "mimeType": "image/svg+xml"}
        return DeterministicResult(output, "Image", "experiment.image.v1", provider_request_id)
    if payload.node_key == "video.generate":
        output = {"kind": "video", "title": "Experiment video", "url": _poster(payload.prompt, exact_model_id, digest), "mimeType": "image/svg+xml"}
        return DeterministicResult(output, "Video", "experiment.video.v1", provider_request_id)
    if payload.node_key == "tts.generate":
        output = {"kind": "audio", "title": "Experiment voiceover", "text": f"Local deterministic preview · {exact_model_id}"}
        return DeterministicResult(output, "Audio", "experiment.audio.v1", provider_request_id)
    refined = f"{payload.prompt.strip()}\n\nCinematic intent preserved. Subject, action, camera motion, lighting, timing, and exclusions are explicit."
    output = {"kind": "text", "title": "Experiment text", "text": refined}
    return DeterministicResult(output, "Text", "experiment.text.v1", provider_request_id)


def experiment_response(record: ExperimentRunRecord) -> ExperimentRunResponse:
    return ExperimentRunResponse(
        id=record.id,
        created_at=record.created_at,
        canvas_id=record.canvas_id,
        node_id=record.node_id,
        node_key=record.node_key,
        status=record.status,
        execution_mode=record.execution_mode,
        prompt=record.prompt,
        model_alias=record.model_alias,
        exact_model_id=record.exact_model_id,
        parameters=record.parameters or {},
        inputs=record.input_snapshot or [],
        request_hash=record.request_hash,
        provider_request_id=record.provider_request_id,
        output_artifact_ids=record.output_artifact_ids or [],
        output=record.output_payload or {},
        duration_ms=record.duration_ms,
        cost_usd=record.cost_usd,
        cache_hit=record.cache_hit,
        cached_from_id=record.cached_from_id,
        is_baseline=record.is_baseline,
        error=record.error,
    )


def run_experiment(db: Session, payload: ExperimentRunRequest) -> ExperimentRunRecord:
    model_alias, exact_model_id = resolve_model(payload.model_alias)
    validate_model_for_node(payload.node_key, model_alias)
    digest = request_fingerprint(payload, model_alias, exact_model_id)
    cached = db.scalar(
        select(ExperimentRunRecord)
        .where(ExperimentRunRecord.request_hash == digest, ExperimentRunRecord.status == NodeStatus.SUCCEEDED)
        .order_by(ExperimentRunRecord.created_at.desc())
    )
    record = ExperimentRunRecord(
        id=new_id("exp"), canvas_id=payload.canvas_id, node_id=payload.node_id, node_key=payload.node_key,
        status=NodeStatus.RUNNING, execution_mode=EXECUTOR_REVISION, prompt=payload.prompt,
        model_alias=model_alias, exact_model_id=exact_model_id, parameters=payload.parameters,
        input_snapshot=payload.inputs, request_hash=digest, output_artifact_ids=[], output_payload={},
    )
    db.add(record)
    db.flush()
    audit(db, "experiment.started", record.id, {"request_hash": digest})
    db.commit()
    db.refresh(record)
    if cached:
        record.status = NodeStatus.SUCCEEDED
        record.provider_request_id = cached.provider_request_id
        record.output_artifact_ids = list(cached.output_artifact_ids or [])
        record.output_payload = dict(cached.output_payload or {})
        record.cache_hit = True
        record.cached_from_id = cached.id
        audit(db, "experiment.cache_hit", record.id, {"cached_from_id": cached.id})
        db.commit()
        db.refresh(record)
        return record

    started = time.perf_counter()
    try:
        result = execute_deterministic(payload, exact_model_id, digest)
    except Exception as exc:
        record.status = NodeStatus.FAILED
        record.duration_ms = max(1, round((time.perf_counter() - started) * 1000))
        record.error = str(exc)
        audit(db, "experiment.failed", record.id, {"error": record.error})
        db.commit()
        db.refresh(record)
        return record
    artifact = create_artifact(
        db, result.artifact_type, schema_id=result.schema_id,
        metadata={"experiment_id": record.id, "request_hash": digest, "output": result.output, "immutable": True},
        content_seed=digest,
    )
    db.flush()
    record.status = NodeStatus.SUCCEEDED
    record.provider_request_id = result.provider_request_id
    record.output_artifact_ids = [artifact.id]
    record.output_payload = result.output
    record.duration_ms = max(1, round((time.perf_counter() - started) * 1000))
    record.cost_usd = MODEL_COSTS.get(model_alias, 0)
    audit(db, "experiment.succeeded", record.id, {"request_hash": digest, "artifact_id": artifact.id})
    db.commit()
    db.refresh(record)
    return record
