from __future__ import annotations

import json
import time
from typing import Any

from sqlalchemy.orm import Session

from .database import ArtifactRecord
from .providers_fal import FAL_FLUX2_TRAINER_MODEL, get_fal_generation_services
from .r2_training_storage import build_captioned_lora_archive, get_r2_training_dataset_store
from .service import audit, create_artifact
from .storage import get_storage, storage_location


TERMINAL_LORA_STATUSES = {"READY", "FAILED", "CANCELLED"}


def character_lora_state(character: ArtifactRecord) -> dict[str, Any]:
    metadata = character.metadata_json or {}
    return {
        "character_id": character.id,
        "status": str(metadata.get("lora_status") or "UNTRAINED"),
        "trigger_word": str(metadata.get("lora_trigger_word") or ""),
        "training_artifact_id": metadata.get("lora_training_artifact_id"),
        "lora_artifact_id": metadata.get("lora_artifact_id"),
        "weights_url": metadata.get("lora_url"),
        "base_model": str(metadata.get("lora_base_model") or "fal-ai/flux-2"),
        "request_id": metadata.get("lora_request_id"),
        "error": metadata.get("lora_error"),
    }


def require_character(db: Session, character_id: str) -> ArtifactRecord:
    character = db.get(ArtifactRecord, character_id)
    if not character or character.type != "Character":
        raise ValueError("character not found")
    return character


def start_character_lora_training(
    db: Session,
    character_id: str,
    *,
    trigger_word: str,
    steps: int = 1000,
    learning_rate: float = 0.00005,
    service: Any | None = None,
    dataset_store: Any | None = None,
) -> dict[str, Any]:
    character = require_character(db, character_id)
    metadata = character.metadata_json or {}
    if str(metadata.get("lora_status") or "").upper() in {"IN_QUEUE", "IN_PROGRESS"}:
        raise ValueError("LoRA training is already running for this character")
    reference_ids = [str(value) for value in metadata.get("reference_image_artifact_ids") or []]
    generated_ids = [str(value) for value in metadata.get("image_artifact_ids") or []]
    image_ids = list(dict.fromkeys([*reference_ids, *generated_ids]))
    roles = [str(value) for value in metadata.get("image_roles") or []]
    storage = get_storage()
    training_images: list[tuple[str, bytes, str]] = []
    for image_id in image_ids:
        image = db.get(ArtifactRecord, image_id)
        if not image or image.type != "Image":
            continue
        bucket, key = storage_location(image.uri, image.metadata_json)
        content_type = str((image.metadata_json.get("storage") or {}).get("content_type") or "image/png")
        extension = "jpg" if "jpeg" in content_type or "jpg" in content_type else "webp" if "webp" in content_type else "svg" if "svg" in content_type else "png"
        generated_index = generated_ids.index(image_id) if image_id in generated_ids else -1
        role = roles[generated_index] if 0 <= generated_index < len(roles) else "canonical_reference"
        training_images.append((role, storage.get_bytes(bucket=bucket, key=key), extension))
    if len(training_images) < 4:
        raise ValueError("At least 4 valid character images are required for LoRA training")
    archive = build_captioned_lora_archive(training_images, trigger_word=trigger_word)
    dataset = (dataset_store or get_r2_training_dataset_store()).put_archive(character_id=character.id, archive=archive)
    submission = (service or get_fal_generation_services()).submit_lora_training(
        image_data_url=dataset.download_url,
        trigger_word=trigger_word,
        steps=steps,
        learning_rate=learning_rate,
    )
    training_snapshot = {
        "schema_version": "character.lora.training.v1",
        "character_id": character.id,
        "provider": "fal",
        "model": FAL_FLUX2_TRAINER_MODEL,
        "trigger_word": trigger_word,
        "steps": steps,
        "learning_rate": learning_rate,
        "image_artifact_ids": image_ids,
        "dataset": {
            "provider": "r2",
            "bucket": dataset.bucket,
            "key": dataset.key,
            "uri": dataset.uri,
            "sha256": dataset.sha256,
            "size_bytes": dataset.size_bytes,
            "presigned_url_expires_at": dataset.expires_at,
        },
        **submission,
    }
    training = create_artifact(
        db,
        "CharacterLoRATraining",
        schema_id="character.lora.training.v1",
        input_artifact_ids=[character.id, *image_ids],
        input_artifact_roles={character.id: "character_bundle", **{image_id: "training_image" for image_id in image_ids}},
        metadata={**training_snapshot, "source": "fal_lora_training", "immutable": False},
        content=json.dumps(training_snapshot, ensure_ascii=False, separators=(",", ":")).encode(),
        content_type="application/json",
        filename="lora-training.json",
    )
    db.flush()
    character.metadata_json = {
        **metadata,
        "lora_status": submission["status"],
        "lora_trigger_word": trigger_word,
        "lora_training_artifact_id": training.id,
        "lora_request_id": submission["request_id"],
        "lora_base_model": "fal-ai/flux-2",
        "lora_error": None,
    }
    audit(db, "character.lora_training_started", character.id, {"training_artifact_id": training.id, "request_id": submission["request_id"]})
    db.commit()
    db.refresh(character)
    return character_lora_state(character)


def refresh_character_lora_training(db: Session, character_id: str, *, service: Any | None = None) -> dict[str, Any]:
    character = require_character(db, character_id)
    metadata = character.metadata_json or {}
    current_status = str(metadata.get("lora_status") or "UNTRAINED").upper()
    if current_status in {"UNTRAINED", *TERMINAL_LORA_STATUSES}:
        return character_lora_state(character)
    training_id = str(metadata.get("lora_training_artifact_id") or "")
    training = db.get(ArtifactRecord, training_id) if training_id else None
    if not training:
        raise ValueError("LoRA training artifact is missing")
    training_metadata = training.metadata_json or {}
    fal_service = service or get_fal_generation_services()
    try:
        status_payload = fal_service.get_queue_status(str(training_metadata.get("status_url") or ""))
    except Exception as exc:
        return _mark_lora_training_failed(db, character, training, metadata, training_metadata, exc)
    fal_status = str(status_payload.get("status") or current_status).upper()
    if fal_status in {"FAILED", "CANCELLED"}:
        error = str(status_payload.get("error") or f"fal training {fal_status.lower()}")
        character.metadata_json = {**metadata, "lora_status": fal_status, "lora_error": error}
        training.metadata_json = {**training_metadata, "status": fal_status, "error": error}
        db.commit()
        db.refresh(character)
        return character_lora_state(character)
    if fal_status != "COMPLETED":
        character.metadata_json = {**metadata, "lora_status": fal_status}
        training.metadata_json = {**training_metadata, "status": fal_status, "logs": status_payload.get("logs") or []}
        db.commit()
        db.refresh(character)
        return character_lora_state(character)
    try:
        result = fal_service.get_queue_result(str(training_metadata.get("response_url") or ""))
    except Exception as exc:
        return _mark_lora_training_failed(db, character, training, metadata, training_metadata, exc)
    lora_file = result.get("diffusers_lora_file") or {}
    config_file = result.get("config_file") or {}
    weights_url = str(lora_file.get("url") or "")
    if not weights_url:
        raise ValueError("fal trainer returned no LoRA weights URL")
    lora_snapshot = {
        "schema_version": "character.lora.v1",
        "character_id": character.id,
        "provider": "fal",
        "base_model": "fal-ai/flux-2",
        "trainer_model": FAL_FLUX2_TRAINER_MODEL,
        "trigger_word": str(metadata.get("lora_trigger_word") or ""),
        "weights_url": weights_url,
        "config_url": config_file.get("url"),
        "training_request_id": metadata.get("lora_request_id"),
    }
    lora_artifact = create_artifact(
        db,
        "CharacterLoRA",
        schema_id="character.lora.v1",
        input_artifact_ids=[character.id, training.id],
        input_artifact_roles={character.id: "character_bundle", training.id: "training_run"},
        metadata={**lora_snapshot, "source": "fal_lora_training", "immutable": True},
        content=json.dumps(lora_snapshot, ensure_ascii=False, separators=(",", ":")).encode(),
        content_type="application/json",
        filename="character-lora.json",
    )
    db.flush()
    character.metadata_json = {
        **metadata,
        "lora_status": "READY",
        "lora_artifact_id": lora_artifact.id,
        "lora_url": weights_url,
        "lora_config_url": config_file.get("url"),
        "lora_error": None,
    }
    training.metadata_json = {**training_metadata, "status": "COMPLETED", "result": result, "lora_artifact_id": lora_artifact.id}
    audit(db, "character.lora_training_completed", character.id, {"lora_artifact_id": lora_artifact.id})
    db.commit()
    db.refresh(character)
    return character_lora_state(character)


def _mark_lora_training_failed(
    db: Session,
    character: ArtifactRecord,
    training: ArtifactRecord,
    character_metadata: dict[str, Any],
    training_metadata: dict[str, Any],
    error: Exception,
) -> dict[str, Any]:
    message = str(error) or error.__class__.__name__
    character.metadata_json = {**character_metadata, "lora_status": "FAILED", "lora_error": message}
    training.metadata_json = {**training_metadata, "status": "FAILED", "error": message}
    audit(db, "character.lora_training_failed", character.id, {"training_artifact_id": training.id, "error": message})
    db.commit()
    db.refresh(character)
    return character_lora_state(character)


def wait_for_character_lora_training(
    db: Session,
    character_id: str,
    *,
    timeout_seconds: int = 1800,
    poll_interval_seconds: float = 5.0,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        state = refresh_character_lora_training(db, character_id)
        status = str(state["status"]).upper()
        if status == "READY":
            return state
        if status in {"FAILED", "CANCELLED"}:
            raise RuntimeError(str(state.get("error") or f"fal training {status.lower()}"))
        time.sleep(poll_interval_seconds)
    raise RuntimeError(f"fal LoRA training timed out after {timeout_seconds} seconds")
