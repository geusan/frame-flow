from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import ArtifactRecord, ExperimentRunRecord
from .canvas_operations import (
    executor_revision,
    execute_canvas_operation,
    is_local_operation,
    resolve_local_model,
)
from .domain import ExperimentRunRequest, ExperimentRunResponse, NodeStatus
from .media_preview import render_audio_wav, render_image_svg, render_video_mp4
from .providers import model_id_for_alias
from .providers_generation import LIVE_GENERATION_REVISION, InputMedia, get_google_generation_services
from .providers_openai import OPENAI_LIVE_REVISION, get_openai_generation_services
from .project_skills import snapshot_skill_parameters
from .service import audit, create_artifact, new_id
from .storage import artifact_content_url, get_storage, storage_location


MODEL_COSTS = {
    "google.text.fast": 0.01,
    "google.text.quality": 0.03,
    "google.image.fast": 0.067,
    "google.image.quality": 0.134,
    "google.image.edit.fast": 0.0336,
    "google.video.fast": 1.40,
    "google.video.quality": 2.80,
    "google.tts.latest": 0.12,
    "google.tts.fast": 0.12,
    "google.tts.quality": 0.24,
    "openai.tts.default": 0.12,
    "openai.tts.fast": 0.12,
    "openai.tts.quality": 0.24,
}
FIXTURE_EXECUTOR_REVISION = "fixture-media.v2"
IMAGE_VARIABLE_PATTERN = re.compile(r"\{\{image:([^}]+)}}")


def resolve_prompt_image_variables(payload: ExperimentRunRequest) -> ExperimentRunRequest:
    referenced_source_ids = IMAGE_VARIABLE_PATTERN.findall(payload.prompt)
    if not referenced_source_ids:
        return payload
    image_inputs = [
        item for item in payload.inputs
        if str(item.get("type") or "") == "Image" and (item.get("artifact_ids") or item.get("artifact_id"))
    ]
    index_by_source_id = {str(item.get("node_id") or ""): index + 1 for index, item in enumerate(image_inputs)}
    missing = [source_id for source_id in dict.fromkeys(referenced_source_ids) if source_id not in index_by_source_id]
    if missing:
        raise ValueError(f"Prompt references image inputs that are no longer connected: {', '.join(missing)}")
    resolved_prompt = IMAGE_VARIABLE_PATTERN.sub(
        lambda match: f"Image {index_by_source_id[match.group(1)]}",
        payload.prompt,
    )
    mapping = "\n".join(
        f"- Image {index}: attached image input {index}"
        for index in range(1, len(image_inputs) + 1)
    )
    return payload.model_copy(update={
        "prompt": f"Use the following image names exactly when following the instruction:\n{mapping}\n\n{resolved_prompt}",
    })


def generation_executor_revision(model_alias: str = "google.text.fast") -> str:
    mode = os.getenv("GENERATION_PROVIDER_MODE", "live").strip().lower()
    if mode == "live":
        return OPENAI_LIVE_REVISION if model_alias.startswith("openai.") else LIVE_GENERATION_REVISION
    if mode == "fixture":
        if os.getenv("APP_ENV") != "test":
            raise ValueError("GENERATION_PROVIDER_MODE=fixture is only allowed when APP_ENV=test")
        return FIXTURE_EXECUTOR_REVISION
    raise ValueError("GENERATION_PROVIDER_MODE must be live or fixture")


def resolve_model(model_alias: str, node_key: str) -> tuple[str, str]:
    if is_local_operation(node_key):
        return resolve_local_model(node_key)
    normalized = model_alias if model_alias.startswith(("google.", "openai.")) else f"google.{model_alias}"
    exact = model_id_for_alias(
        normalized,
        gemini_api=bool((os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()),
    )
    if not exact:
        raise ValueError(f"model alias is not registered: {model_alias}")
    return normalized, exact


def validate_model_for_node(node_key: str, model_alias: str) -> None:
    allowed_families = {
        "image.generate": ("google.image.", "openai.image."),
        "image.edit": ("google.image.", "openai.image."),
        "video.generate": ("google.video.",),
        "tts.generate": ("google.tts.", "openai.tts."),
        "llm.assistant": ("google.text.", "openai.text.", "openai.chat."),
        "script.generate": ("google.text.", "openai.text.", "openai.chat."),
        "skill.execute": ("google.text.", "openai.text.", "openai.chat."),
    }.get(node_key)
    if allowed_families and not model_alias.startswith(allowed_families):
        raise ValueError(f"{node_key} requires one of these model families: {', '.join(allowed_families)}")


def request_fingerprint(payload: ExperimentRunRequest, model_alias: str, exact_model_id: str) -> str:
    snapshot = {
        "executor_revision": executor_revision(payload.node_key) if is_local_operation(payload.node_key) else generation_executor_revision(model_alias),
        "node_key": payload.node_key,
        "prompt": payload.prompt,
        "model_alias": model_alias,
        "exact_model_id": exact_model_id,
        "parameters": payload.parameters,
        "inputs": payload.inputs,
    }
    encoded = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


@dataclass(frozen=True)
class FixtureResult:
    output: dict[str, object]
    artifact_type: str
    schema_id: str | None
    provider_request_id: str
    content: bytes
    content_type: str
    filename: str


def execute_fixture(payload: ExperimentRunRequest, exact_model_id: str, digest: str) -> FixtureResult:
    provider_request_id = f"local_{digest[:20]}"
    if payload.node_key in {"image.generate", "image.edit"}:
        output = {"kind": "image", "title": "AI edited image" if payload.node_key == "image.edit" else "Experiment image", "mimeType": "image/svg+xml"}
        content = render_image_svg(payload.prompt, exact_model_id, digest)
        return FixtureResult(output, "Image", "experiment.image.edit.v1" if payload.node_key == "image.edit" else "experiment.image.v1", provider_request_id, content, "image/svg+xml", "edited.svg" if payload.node_key == "image.edit" else "preview.svg")
    if payload.node_key == "video.generate":
        output = {"kind": "video", "title": "Experiment video", "mimeType": "video/mp4"}
        content = render_video_mp4(digest)
        return FixtureResult(output, "Video", "experiment.video.v1", provider_request_id, content, "video/mp4", "preview.mp4")
    if payload.node_key == "tts.generate":
        output = {"kind": "audio", "title": "Fixture voiceover", "text": f"Test fixture · {exact_model_id}", "mimeType": "audio/wav"}
        content = render_audio_wav(digest)
        return FixtureResult(output, "Audio", "experiment.audio.v1", provider_request_id, content, "audio/wav", "preview.wav")
    refined = f"{payload.prompt.strip()}\n\nCinematic intent preserved. Subject, action, camera motion, lighting, timing, and exclusions are explicit."
    if payload.node_key == "skill.execute":
        refined = (
            "### 1. English Master Prompt\n"
            f"Production-ready visual specification for: {payload.prompt.strip()}\n\n"
            "### 2. Korean Translation\n"
            f"제작 가능한 시각 명세: {payload.prompt.strip()}\n\n"
            "### 3. Technical / Visual Blueprint\n"
            "Discipline: visual production · Medium / Output: inferred from the request · "
            "Invariants / Avoid: preserve explicit constraints"
        )
        output = {"kind": "text", "title": "Generated master prompt", "text": refined}
        return FixtureResult(output, "Text", "prompt.master.v1", provider_request_id, refined.encode(), "text/plain", "master-prompt.txt")
    if payload.node_key == "script.generate":
        output = {"kind": "text", "title": "Generated script", "text": refined}
        return FixtureResult(output, "Script", "script.v1", provider_request_id, refined.encode(), "text/plain", "script.txt")
    output = {"kind": "text", "title": "Experiment text", "text": refined}
    return FixtureResult(output, "Text", "experiment.text.v1", provider_request_id, refined.encode(), "text/plain", "result.txt")


def execute_live_provider(db: Session, payload: ExperimentRunRequest):
    storage = get_storage()
    input_ids: list[str] = []
    inputs: list[InputMedia] = []
    for item in payload.inputs:
        artifact_ids = list(item.get("artifact_ids") or [])
        if item.get("artifact_id"):
            artifact_ids.insert(0, item["artifact_id"])
        for artifact_id_value in artifact_ids:
            artifact_id = str(artifact_id_value)
            if artifact_id in input_ids:
                continue
            artifact = db.get(ArtifactRecord, artifact_id)
            if not artifact:
                raise ValueError(f"input artifact does not exist: {artifact_id}")
            bucket, key = storage_location(artifact.uri, artifact.metadata_json)
            content_type = str((artifact.metadata_json.get("storage") or {}).get("content_type") or "application/octet-stream")
            inputs.append(InputMedia(artifact.id, artifact.type, storage.get_bytes(bucket=bucket, key=key), content_type))
            input_ids.append(artifact.id)
    services = get_openai_generation_services() if payload.model_alias.startswith("openai.") else get_google_generation_services()
    result = services.execute(payload, inputs)
    return result


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
    payload = resolve_prompt_image_variables(payload)
    if payload.node_key == "skill.execute":
        payload = payload.model_copy(update={"parameters": snapshot_skill_parameters(payload.parameters)})
    model_alias, exact_model_id = resolve_model(payload.model_alias, payload.node_key)
    requested_provider = str(payload.parameters.get("provider") or "").strip().lower()
    if requested_provider and model_alias.startswith(("google.", "openai.")) and not model_alias.startswith(f"{requested_provider}."):
        raise ValueError(f"selected provider {requested_provider} does not match model alias {model_alias}")
    validate_model_for_node(payload.node_key, model_alias)
    digest = request_fingerprint(payload, model_alias, exact_model_id)
    cached = db.scalar(
        select(ExperimentRunRecord)
        .where(ExperimentRunRecord.request_hash == digest, ExperimentRunRecord.status == NodeStatus.SUCCEEDED)
        .order_by(ExperimentRunRecord.created_at.desc())
    )
    record = ExperimentRunRecord(
        id=new_id("exp"), canvas_id=payload.canvas_id, node_id=payload.node_id, node_key=payload.node_key,
        status=NodeStatus.RUNNING,
        execution_mode=executor_revision(payload.node_key) if is_local_operation(payload.node_key) else generation_executor_revision(model_alias),
        prompt=payload.prompt,
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
        if is_local_operation(payload.node_key):
            result = execute_canvas_operation(db, payload, digest)
        elif generation_executor_revision(model_alias) in {LIVE_GENERATION_REVISION, OPENAI_LIVE_REVISION}:
            result = execute_live_provider(db, payload)
        else:
            result = execute_fixture(payload, exact_model_id, digest)
        input_artifact_ids = getattr(result, "input_artifact_ids", [])
        result_metadata = dict(getattr(result, "metadata", {}) or {})
        input_artifact_roles = dict(getattr(result, "input_artifact_roles", {}) or {})
        artifact = create_artifact(
            db, result.artifact_type, schema_id=result.schema_id,
            input_artifact_ids=input_artifact_ids,
            input_artifact_roles=input_artifact_roles,
            metadata={
                **result_metadata,
                "experiment_id": record.id,
                "request_hash": digest,
                "execution_mode": record.execution_mode,
                "output": result.output,
                "immutable": True,
            },
            content_seed=digest,
            content=result.content,
            content_type=result.content_type,
            filename=result.filename,
        )
        artifacts = [artifact]
        for additional in getattr(result, "additional_assets", ()):
            artifacts.append(create_artifact(
                db, result.artifact_type, schema_id=result.schema_id,
                input_artifact_ids=input_artifact_ids,
                input_artifact_roles=input_artifact_roles,
                metadata={
                    **result_metadata,
                    "experiment_id": record.id,
                    "request_hash": digest,
                    "execution_mode": record.execution_mode,
                    "immutable": True,
                    "candidate_index": len(artifacts) + 1,
                },
                content_seed=digest,
                content=additional.data,
                content_type=additional.content_type,
                filename=additional.filename,
            ))
        db.flush()
    except Exception as exc:
        db.rollback()
        record = db.get(ExperimentRunRecord, record.id) or record
        record.status = NodeStatus.FAILED
        record.duration_ms = max(1, round((time.perf_counter() - started) * 1000))
        record.error = str(exc)
        audit(db, "experiment.failed", record.id, {"error": record.error})
        db.commit()
        db.refresh(record)
        return record
    record.status = NodeStatus.SUCCEEDED
    record.provider_request_id = result.provider_request_id
    record.output_artifact_ids = [item.id for item in artifacts]
    output = dict(result.output)
    if result.output.get("kind") in {"image", "video", "audio"}:
        output["url"] = artifact_content_url(artifact.id)
    record.output_payload = output
    record.duration_ms = max(1, round((time.perf_counter() - started) * 1000))
    record.cost_usd = MODEL_COSTS.get(model_alias, 0)
    audit(db, "experiment.succeeded", record.id, {"request_hash": digest, "artifact_ids": record.output_artifact_ids})
    db.commit()
    db.refresh(record)
    return record
