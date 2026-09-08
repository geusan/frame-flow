from __future__ import annotations

import hashlib
import json
import os
import re
import time
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import ArtifactRecord, ExperimentRunRecord
from .domain import ExperimentRunRequest, ExperimentRunResponse, NodeStatus
from .nodes import node_registry
from .infrastructure.node_execution import (
    SqlAlchemyNodeArtifactStore,
    SqlAlchemyNodeCharacterLoraRuntime,
    SqlAlchemyNodeMediaRuntime,
    SqlAlchemyNodeProviderSettings,
)
from .nodes.contracts import NodeExecutionContext
from .providers import model_id_for_alias
from .providers_fal import FAL_LIVE_REVISION
from .providers_generation import LIVE_GENERATION_REVISION
from .providers_openai import OPENAI_LIVE_REVISION
from .providers_xai import XAI_LIVE_REVISION
from .project_skills import snapshot_skill_parameters
from .service import audit, new_id


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


def resolve_character_lora_parameters(db: Session, payload: ExperimentRunRequest, definition: Any = None) -> ExperimentRunRequest:
    lora_capability = bool(
        definition
        and any(family.startswith("fal.image.") for family in definition.execution.model_families)
        and "lora_url" in definition.config_schema.get("properties", {})
    )
    if not lora_capability or str(payload.parameters.get("lora_url") or "").strip():
        return payload
    for item in payload.inputs:
        if str(item.get("type") or "") != "Character":
            continue
        artifact_ids = [*(item.get("artifact_ids") or []), *([item.get("artifact_id")] if item.get("artifact_id") else [])]
        for artifact_id in artifact_ids:
            character = db.get(ArtifactRecord, str(artifact_id))
            if not character or character.type != "Character":
                continue
            metadata = character.metadata_json or {}
            weights_url = str(metadata.get("lora_url") or "").strip()
            if not weights_url:
                raise ValueError("Connected Character does not have a trained LoRA yet")
            parameters = {
                **payload.parameters,
                "lora_url": weights_url,
                "trigger_word": str(payload.parameters.get("trigger_word") or metadata.get("lora_trigger_word") or ""),
                "character_lora_artifact_id": metadata.get("lora_artifact_id"),
            }
            return payload.model_copy(update={"parameters": parameters})
    raise ValueError("LoRA weights URL or a trained Character input is required")


def generation_executor_revision(model_alias: str = "google.text.fast") -> str:
    mode = os.getenv("GENERATION_PROVIDER_MODE", "live").strip().lower()
    if mode == "live":
        if model_alias.startswith("openai."):
            return OPENAI_LIVE_REVISION
        if model_alias.startswith("xai."):
            return XAI_LIVE_REVISION
        if model_alias.startswith("fal."):
            return FAL_LIVE_REVISION
        return LIVE_GENERATION_REVISION
    if mode == "fixture":
        if os.getenv("APP_ENV") != "test":
            raise ValueError("GENERATION_PROVIDER_MODE=fixture is only allowed when APP_ENV=test")
        return FIXTURE_EXECUTOR_REVISION
    raise ValueError("GENERATION_PROVIDER_MODE must be live or fixture")


def resolve_model(model_alias: str, node_key: str, contract_version: int = 1) -> tuple[str, str]:
    definition = node_registry.get(node_key, contract_version)
    if definition is None:
        raise ValueError(f"Node Definition was not found: {node_key}@{contract_version}")
    if not definition.execution.model_families:
        if node_registry.uses_legacy_runtime(definition):
            resolved = definition.execution.model_alias
            return resolved, model_id_for_alias(resolved) or definition.execution.revision
        if model_alias not in {definition.execution.model_alias, "local"}:
            raise ValueError(f"{node_key} requires model alias {definition.execution.model_alias}")
        resolved = definition.execution.model_alias
        return resolved, model_id_for_alias(resolved) or definition.execution.revision
    normalized = model_alias if model_alias.startswith(("google.", "openai.", "fal.", "chatgpt.", "claude.", "xai.")) else f"google.{model_alias}"
    exact = model_id_for_alias(normalized)
    if not exact:
        raise ValueError(f"model alias is not registered: {model_alias}")
    return normalized, exact


def validate_model_for_node(node_key: str, model_alias: str, contract_version: int = 1) -> None:
    definition = node_registry.get(node_key, contract_version)
    if definition is None:
        raise ValueError(f"Node Definition was not found: {node_key}@{contract_version}")
    if definition.execution.model_families:
        if not model_alias.startswith(tuple(definition.execution.model_families)):
            raise ValueError(f"{node_key} requires one of these model families: {', '.join(definition.execution.model_families)}")
        return
    if model_alias != definition.execution.model_alias:
        raise ValueError(f"{node_key} requires model alias {definition.execution.model_alias}")


def resolved_executor_revision(
    node_key: str,
    model_alias: str,
    contract_version: int = 1,
    parameters: dict[str, Any] | None = None,
) -> str:
    definition = node_registry.get(node_key, contract_version)
    if definition:
        if definition.execution.kind == "provider" and node_registry.uses_legacy_runtime(definition):
            return generation_executor_revision(model_alias)
        config = node_registry.resolve_config(definition, parameters or {})
        return node_registry.runtime_revision(definition, config)
    raise ValueError(f"Node Definition was not found: {node_key}@{contract_version}")


def request_fingerprint(payload: ExperimentRunRequest, model_alias: str, exact_model_id: str) -> str:
    definition = node_registry.get(payload.node_key, payload.node_contract_version)
    normalized_parameters = node_registry.resolve_config(definition, payload.parameters) if definition else payload.parameters
    snapshot = {
        "executor_revision": resolved_executor_revision(
            payload.node_key,
            model_alias,
            payload.node_contract_version,
            normalized_parameters,
        ),
        "node_contract_version": definition.contract_version if definition else payload.node_contract_version,
        "node_definition_digest": definition.definition_digest if definition else None,
        "node_key": payload.node_key,
        "prompt": payload.prompt,
        "model_alias": model_alias,
        "exact_model_id": exact_model_id,
        "parameters": normalized_parameters,
        "inputs": payload.inputs,
    }
    encoded = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()



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


def run_experiment(
    db: Session,
    payload: ExperimentRunRequest,
    progress_callback: Callable[[int, str], None] | None = None,
) -> ExperimentRunRecord:
    payload = resolve_prompt_image_variables(payload)
    definition = node_registry.get(payload.node_key, payload.node_contract_version)
    payload = resolve_character_lora_parameters(db, payload, definition)
    if payload.node_key == "skill.execute":
        payload = payload.model_copy(update={"parameters": snapshot_skill_parameters(payload.parameters, db)})
    configured_model_alias = str(payload.parameters.get("model_alias") or "").strip()
    if definition and not node_registry.uses_legacy_runtime(definition) and configured_model_alias:
        payload = payload.model_copy(update={"model_alias": configured_model_alias})
    model_alias, exact_model_id = resolve_model(payload.model_alias, payload.node_key, payload.node_contract_version)
    if payload.model_alias != model_alias:
        payload = payload.model_copy(update={"model_alias": model_alias})
    requested_provider = str(payload.parameters.get("provider") or "").strip().lower()
    if requested_provider and model_alias.startswith(("google.", "openai.", "fal.", "xai.")) and not model_alias.startswith(f"{requested_provider}."):
        raise ValueError(f"selected provider {requested_provider} does not match model alias {model_alias}")
    validate_model_for_node(payload.node_key, model_alias, payload.node_contract_version)
    contract_parameters = {key: value for key, value in payload.parameters.items() if key != "provider"}
    normalized_parameters = node_registry.resolve_config(definition, contract_parameters) if definition else payload.parameters
    if definition:
        payload = payload.model_copy(update={"parameters": normalized_parameters})
    digest = request_fingerprint(payload, model_alias, exact_model_id)
    cached = db.scalar(
        select(ExperimentRunRecord)
        .where(ExperimentRunRecord.request_hash == digest, ExperimentRunRecord.status == NodeStatus.SUCCEEDED)
        .order_by(ExperimentRunRecord.created_at.desc())
    )
    record = ExperimentRunRecord(
        id=new_id("exp"), canvas_id=payload.canvas_id, node_id=payload.node_id, node_key=payload.node_key,
        status=NodeStatus.RUNNING,
        execution_mode=resolved_executor_revision(
            payload.node_key,
            model_alias,
            payload.node_contract_version,
            normalized_parameters,
        ),
        prompt=payload.prompt,
        model_alias=model_alias, exact_model_id=exact_model_id, parameters=normalized_parameters,
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
        context = NodeExecutionContext(
            definition=definition,
            prompt=payload.prompt,
            model_alias=payload.model_alias,
            request_hash=digest,
            experiment_id=record.id,
            progress_callback=progress_callback,
            artifact_store=SqlAlchemyNodeArtifactStore(db),
            provider_settings=SqlAlchemyNodeProviderSettings(db),
            media_runtime=SqlAlchemyNodeMediaRuntime(db),
            character_lora_runtime=SqlAlchemyNodeCharacterLoraRuntime(db),
        ) if definition else None
        if context is None:
            raise ValueError(
                f"Node Definition was not found: {payload.node_key}@{payload.node_contract_version}"
            )
        if not node_registry.can_execute(context):
            raise RuntimeError(
                f"Node contract has no registered execution capability: "
                f"{payload.node_key}@{payload.node_contract_version}"
            )
        result = node_registry.execute(
            context,
            payload.parameters,
            payload.inputs,
        )
        artifacts = []
        for artifact_id in result.output_artifact_ids:
            artifact = db.get(ArtifactRecord, artifact_id)
            if not artifact:
                raise ValueError(f"registered Node returned a missing Artifact: {artifact_id}")
            artifacts.append(artifact)
        if not artifacts:
            raise ValueError("registered Node returned no output Artifacts")
        db.flush()
    except Exception as exc:
        failure_retryable = getattr(exc, "retryable", None)
        db.rollback()
        record = db.get(ExperimentRunRecord, record.id) or record
        record.status = NodeStatus.FAILED
        record.duration_ms = max(1, round((time.perf_counter() - started) * 1000))
        record.error = str(exc)
        audit(db, "experiment.failed", record.id, {"error": record.error})
        db.commit()
        db.refresh(record)
        setattr(record, "_failure_retryable", failure_retryable)
        return record
    record.status = NodeStatus.SUCCEEDED
    record.provider_request_id = result.provider_request_id
    record.output_artifact_ids = [item.id for item in artifacts]
    record.output_payload = dict(result.output)
    record.duration_ms = max(1, round((time.perf_counter() - started) * 1000))
    record.cost_usd = result.cost_usd
    audit(db, "experiment.succeeded", record.id, {"request_hash": digest, "artifact_ids": record.output_artifact_ids})
    db.commit()
    db.refresh(record)
    return record
