from __future__ import annotations

import base64
import json
import mimetypes
import re
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...artifact_lineage import artifact_lineage_graph
from ...character_lora import (
    character_lora_state,
    refresh_character_lora_training,
    start_character_lora_training as submit_character_lora_training,
)
from ...database import ArtifactRecord, get_db
from ...domain import (
    ArtifactResponse,
    ArtifactUrlImportRequest,
    CharacterLoraTrainRequest,
    FrameCaptureRequest,
    ImageEditDocument,
    SceneSearchRequest,
    SignedUrlRequest,
)
from ...media_capture import MediaCaptureError, capture_video_frame
from ...media_compat import BrowserVideoError
from ...providers_fal import get_fal_generation_services
from ...r2_training_storage import get_r2_training_dataset_store
from ...reference_ingest import ReferenceIngestError
from ...scene_search import SceneSearchError, search_video_scenes
from ...service import artifact_response, audit, create_artifact, new_id
from ...storage import (
    StorageError,
    artifact_content_url,
    extension_for,
    get_storage,
    safe_upload_key,
    storage_location,
)
from ...video_downloaders import get_video_downloader
from ...video_playback import ensure_video_playback_artifact


CANVAS_ARTIFACT_MAX_BYTES = 250 * 1024 * 1024

router = APIRouter(tags=["artifacts"])


@router.get("/artifacts")
def list_artifacts(
    types: str = Query(default="Image,Video,Audio,Text,FinalVideo"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    requested = {value.strip() for value in types.split(",") if value.strip()}
    rows = db.scalars(
        select(ArtifactRecord)
        .where(ArtifactRecord.type.in_(requested))
        .order_by(ArtifactRecord.created_at.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    result: list[dict[str, Any]] = []
    for row in rows:
        playback_id = str(row.metadata_json.get("playback_artifact_id") or row.id)
        result.append(
            {
                "id": row.id,
                "created_at": row.created_at,
                "type": row.type,
                "content_type": str(
                    (row.metadata_json.get("storage") or {}).get("content_type")
                    or "application/octet-stream"
                ),
                "size_bytes": int(
                    (row.metadata_json.get("storage") or {}).get("size_bytes") or 0
                ),
                "filename": str(
                    row.metadata_json.get("filename")
                    or row.metadata_json.get("output", {}).get("title")
                    or f"{row.type} · {row.id[:10]}"
                ),
                "source": str(
                    row.metadata_json.get("source")
                    or (
                        "generated"
                        if row.producer_node_run_id
                        or row.metadata_json.get("experiment_id")
                        else "artifact"
                    )
                ),
                "duration_ms": int(row.metadata_json.get("duration_ms") or 0),
                "url": artifact_content_url(playback_id),
            }
        )
    return result


@router.get("/characters")
def list_characters(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(ArtifactRecord)
        .where(ArtifactRecord.type == "Character")
        .order_by(ArtifactRecord.created_at.desc())
    ).all()
    result: list[dict[str, Any]] = []
    for row in rows:
        metadata = row.metadata_json or {}
        image_ids = [str(value) for value in metadata.get("image_artifact_ids") or []]
        roles = [str(value) for value in metadata.get("image_roles") or []]
        images = [
            {
                "artifact_id": artifact_id,
                "role": roles[index] if index < len(roles) else f"view_{index + 1}",
                "url": artifact_content_url(artifact_id),
            }
            for index, artifact_id in enumerate(image_ids)
            if db.get(ArtifactRecord, artifact_id)
        ]
        cover_id = str(
            metadata.get("cover_artifact_id") or (image_ids[0] if image_ids else "")
        )
        result.append(
            {
                "id": row.id,
                "created_at": row.created_at,
                "name": str(
                    metadata.get("name")
                    or metadata.get("filename")
                    or f"Character {row.id[:8]}"
                ),
                "synopsis": str(metadata.get("synopsis") or ""),
                "model_alias": str(metadata.get("model_alias") or ""),
                "exact_model_id": str(metadata.get("exact_model_id") or ""),
                "cover_url": artifact_content_url(cover_id) if cover_id else None,
                "image_count": len(images),
                "images": images,
                "lora": {
                    "status": str(metadata.get("lora_status") or "UNTRAINED"),
                    "trigger_word": str(metadata.get("lora_trigger_word") or ""),
                    "training_artifact_id": metadata.get("lora_training_artifact_id"),
                    "artifact_id": metadata.get("lora_artifact_id"),
                    "weights_url": metadata.get("lora_url"),
                    "base_model": str(
                        metadata.get("lora_base_model") or "fal-ai/flux-2"
                    ),
                    "error": metadata.get("lora_error"),
                },
            }
        )
    return result


def _character_lora_response(character: ArtifactRecord) -> dict[str, Any]:
    return character_lora_state(character)


@router.post(
    "/characters/{character_id}/lora-training",
    status_code=status.HTTP_202_ACCEPTED,
)
def start_character_lora_training(
    character_id: str,
    payload: CharacterLoraTrainRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return submit_character_lora_training(
            db,
            character_id,
            trigger_word=payload.trigger_word,
            steps=payload.steps,
            learning_rate=payload.learning_rate,
            service=get_fal_generation_services(),
            dataset_store=get_r2_training_dataset_store(),
        )
    except ValueError as exc:
        status_code = (
            404
            if str(exc) == "character not found"
            else 409
            if "already running" in str(exc)
            else 422
        )
        raise HTTPException(status_code, str(exc)) from exc


@router.get("/characters/{character_id}/lora-training")
def get_character_lora_training(
    character_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return refresh_character_lora_training(
            db,
            character_id,
            service=get_fal_generation_services(),
        )
    except ValueError as exc:
        status_code = (
            404
            if str(exc) == "character not found"
            else 409
            if "artifact is missing" in str(exc)
            else 422
        )
        raise HTTPException(status_code, str(exc)) from exc


@router.get("/artifacts/{artifact_id}", response_model=ArtifactResponse)
def get_artifact(
    artifact_id: str,
    db: Session = Depends(get_db),
) -> ArtifactResponse:
    artifact = db.get(ArtifactRecord, artifact_id)
    if not artifact:
        raise HTTPException(404, "artifact not found")
    return artifact_response(artifact)


@router.post(
    "/artifacts/{artifact_id}/audio-asset",
    status_code=status.HTTP_201_CREATED,
)
def create_audio_asset_from_reference(
    artifact_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    source = db.get(ArtifactRecord, artifact_id)
    if not source:
        raise HTTPException(404, "reference audio artifact not found")
    allowed_types = {
        "ReferenceAudioMix": "reference-audio.wav",
        "ReferenceVocals": "vocals.wav",
        "ReferenceAccompaniment": "accompaniment.wav",
    }
    if source.type not in allowed_types:
        raise HTTPException(
            415,
            "only Reference Analyzer audio outputs can be saved as Audio assets",
        )

    existing = next(
        (
            artifact
            for artifact in db.scalars(
                select(ArtifactRecord).where(ArtifactRecord.type == "Audio")
            ).all()
            if artifact.metadata_json.get("source") == "reference_audio_export"
            and artifact.metadata_json.get("source_artifact_id") == source.id
        ),
        None,
    )
    if existing:
        storage_metadata = existing.metadata_json.get("storage") or {}
        return {
            "artifact_id": existing.id,
            "type": existing.type,
            "content_type": str(
                storage_metadata.get("content_type") or "audio/wav"
            ),
            "size_bytes": int(storage_metadata.get("size_bytes") or 0),
            "filename": str(
                existing.metadata_json.get("filename") or allowed_types[source.type]
            ),
            "source": "reference_audio_export",
            "url": artifact_content_url(existing.id),
        }

    storage = get_storage()
    try:
        bucket, key = storage_location(source.uri, source.metadata_json)
        content = storage.get_bytes(bucket=bucket, key=key)
    except StorageError as exc:
        raise HTTPException(409, str(exc)) from exc

    source_storage = source.metadata_json.get("storage") or {}
    content_type = str(source_storage.get("content_type") or "audio/wav")
    filename = str(source.metadata_json.get("filename") or allowed_types[source.type])
    artifact = create_artifact(
        db,
        "Audio",
        schema_id="audio.asset.v1",
        input_artifact_ids=[source.id],
        input_artifact_roles={source.id: "reference_audio_source"},
        metadata={
            "source": "reference_audio_export",
            "source_artifact_id": source.id,
            "reference_component_type": source.type,
            "filename": filename,
            "duration_ms": int(source.metadata_json.get("duration_ms") or 0),
            "immutable": True,
            "storage_scope": "generation",
        },
        content=content,
        content_type=content_type,
        filename=filename,
    )
    audit(
        db,
        "artifact.reference_audio_exported",
        artifact.id,
        {"source_artifact_id": source.id, "source_type": source.type},
    )
    db.commit()
    artifact_storage = artifact.metadata_json.get("storage") or {}
    return {
        "artifact_id": artifact.id,
        "type": artifact.type,
        "content_type": str(artifact_storage.get("content_type") or content_type),
        "size_bytes": int(artifact_storage.get("size_bytes") or len(content)),
        "filename": filename,
        "source": "reference_audio_export",
        "url": artifact_content_url(artifact.id),
    }


@router.get("/artifacts/{artifact_id}/lineage")
def get_artifact_lineage(
    artifact_id: str,
    direction: Literal["ancestors", "descendants", "both"] = Query(default="both"),
    depth: int = Query(default=8, ge=0, le=32),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    try:
        return artifact_lineage_graph(db, artifact_id, direction=direction, depth=depth)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/artifacts/{artifact_id}/scene-search")
def search_artifact_scenes(
    artifact_id: str,
    payload: SceneSearchRequest,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    source = db.get(ArtifactRecord, artifact_id)
    if not source:
        raise HTTPException(404, "source video artifact not found")
    if source.type not in {"Video", "FinalVideo"}:
        raise HTTPException(415, "only video artifacts support scene search")
    storage = get_storage()
    try:
        bucket, key = storage_location(source.uri, source.metadata_json)
        content_type = str(
            (source.metadata_json.get("storage") or {}).get("content_type")
            or "video/mp4"
        )
        result = search_video_scenes(
            storage.get_bytes(bucket=bucket, key=key),
            content_type,
            payload.prompt,
            candidate_count=payload.candidate_count,
            sample_count=payload.sample_count,
            provider=payload.provider,
            model_alias=payload.model_alias,
        )
    except StorageError as exc:
        raise HTTPException(409, str(exc)) from exc
    except SceneSearchError as exc:
        raise HTTPException(422, str(exc)) from exc
    search_id = new_id("search")
    audit(
        db,
        "artifact.scene_searched",
        source.id,
        {
            "search_id": search_id,
            "prompt": payload.prompt,
            "provider": result.provider,
            "model_alias": result.model_alias,
            "provider_request_id": result.provider_request_id,
            "candidate_count": len(result.scenes),
        },
    )
    db.commit()
    return {
        "search_id": search_id,
        "source_artifact_id": source.id,
        "prompt": payload.prompt,
        "provider": result.provider,
        "model_alias": result.model_alias,
        "exact_model_id": result.exact_model_id,
        "provider_request_id": result.provider_request_id,
        "source_duration_ms": result.source_duration_ms,
        "candidates": [
            {
                "index": scene.frame.index,
                "timestamp_ms": scene.frame.timestamp_ms,
                "score": scene.score,
                "reason": scene.reason,
                "thumbnail_data_url": (
                    f"data:{scene.frame.content_type};base64,"
                    f"{base64.b64encode(scene.frame.content).decode()}"
                ),
            }
            for scene in result.scenes
        ],
    }


@router.post(
    "/artifacts/{artifact_id}/capture-frame",
    status_code=status.HTTP_201_CREATED,
)
def capture_artifact_frame(
    artifact_id: str,
    payload: FrameCaptureRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    source = db.get(ArtifactRecord, artifact_id)
    if not source:
        raise HTTPException(404, "source video artifact not found")
    if source.type not in {"Video", "FinalVideo"}:
        raise HTTPException(415, "only video artifacts support frame capture")
    storage = get_storage()
    try:
        bucket, key = storage_location(source.uri, source.metadata_json)
        content_type = str(
            (source.metadata_json.get("storage") or {}).get("content_type")
            or "video/mp4"
        )
        captured = capture_video_frame(
            storage.get_bytes(bucket=bucket, key=key),
            content_type,
            payload.timestamp_ms,
        )
    except StorageError as exc:
        raise HTTPException(409, str(exc)) from exc
    except MediaCaptureError as exc:
        raise HTTPException(422, str(exc)) from exc

    source_filename = str(
        source.metadata_json.get("filename")
        or source.metadata_json.get("output", {}).get("title")
        or source.id
    )
    source_stem = re.sub(r"\.[A-Za-z0-9]{1,10}$", "", source_filename)
    safe_stem = (
        re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "-", source_stem).strip(" .")
        or source.id
    )
    total_seconds, milliseconds = divmod(captured.timestamp_ms, 1000)
    minutes, seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    timestamp_label = f"{hours:02d}-{minutes:02d}-{seconds:02d}-{milliseconds:03d}"
    filename = f"{safe_stem[:150]}-frame-{timestamp_label}.jpg"
    search_context = payload.model_dump(exclude={"timestamp_ms"}, exclude_none=True)
    capture_metadata = {
        "operation": "ffmpeg-accurate-seek.v1",
        "source_artifact_id": source.id,
        "timestamp_ms": captured.timestamp_ms,
        "source_duration_ms": captured.source_duration_ms,
        "width": captured.width,
        "height": captured.height,
        **({"scene_search": search_context} if search_context else {}),
    }
    artifact = create_artifact(
        db,
        "Image",
        input_artifact_ids=[source.id],
        input_artifact_roles={source.id: "source_video"},
        content=captured.content,
        content_type=captured.content_type,
        filename=filename,
        metadata={
            "source": "video_frame_capture",
            "filename": filename,
            "source_artifact_id": source.id,
            "timestamp_ms": captured.timestamp_ms,
            "capture": capture_metadata,
            "immutable": True,
        },
    )
    db.flush()
    audit(
        db,
        "artifact.video_frame_captured",
        artifact.id,
        {
            "source_artifact_id": source.id,
            "timestamp_ms": captured.timestamp_ms,
            **({"search_id": payload.search_id} if payload.search_id else {}),
        },
    )
    db.commit()
    return {
        "id": artifact.id,
        "created_at": artifact.created_at,
        "type": artifact.type,
        "content_type": captured.content_type,
        "size_bytes": len(captured.content),
        "filename": filename,
        "source": "video_frame_capture",
        "duration_ms": 0,
        "source_artifact_id": source.id,
        "timestamp_ms": captured.timestamp_ms,
        "url": artifact_content_url(artifact.id),
    }


@router.get("/artifacts/{artifact_id}/frame-preview")
def preview_artifact_frame(
    artifact_id: str,
    timestamp_ms: int = Query(ge=0),
    db: Session = Depends(get_db),
) -> Response:
    source = db.get(ArtifactRecord, artifact_id)
    if not source:
        raise HTTPException(404, "source video artifact not found")
    if source.type not in {"Video", "FinalVideo"}:
        raise HTTPException(415, "only video artifacts support frame previews")
    storage = get_storage()
    try:
        bucket, key = storage_location(source.uri, source.metadata_json)
        content_type = str(
            (source.metadata_json.get("storage") or {}).get("content_type")
            or "video/mp4"
        )
        captured = capture_video_frame(
            storage.get_bytes(bucket=bucket, key=key),
            content_type,
            timestamp_ms,
        )
    except StorageError as exc:
        raise HTTPException(409, str(exc)) from exc
    except MediaCaptureError as exc:
        raise HTTPException(422, str(exc)) from exc
    return Response(
        content=captured.content,
        media_type=captured.content_type,
        headers={
            "Cache-Control": "public, max-age=86400, immutable",
            "X-Frame-Timestamp-Ms": str(captured.timestamp_ms),
            "X-Source-Duration-Ms": str(captured.source_duration_ms),
        },
    )


@router.post("/artifacts/upload-url")
def artifact_upload_url(payload: SignedUrlRequest) -> dict[str, Any]:
    upload_id = new_id("upload")
    storage = get_storage()
    key = safe_upload_key(upload_id, payload.filename)
    try:
        target = storage.create_upload_url(
            bucket=storage.settings.buckets.generation,
            key=key,
            content_type=payload.content_type,
        )
    except StorageError as exc:
        raise HTTPException(503, str(exc)) from exc
    return {
        "upload_id": upload_id,
        "provider": target.provider,
        "bucket": target.bucket,
        "object_key": target.key,
        "object_uri": target.uri,
        "method": "PUT",
        "url": target.url,
        "expires_in_seconds": target.expires_in_seconds,
        "headers": target.headers,
    }


@router.post("/artifacts/import-url", status_code=status.HTTP_201_CREATED)
def import_artifact_url(
    payload: ArtifactUrlImportRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    source_url = str(payload.url)
    try:
        provider = get_video_downloader()
        inspected = provider.inspect(source_url)
        downloaded = provider.download(
            inspected.canonical_url,
            max_duration_seconds=600,
            max_filesize_bytes=CANVAS_ARTIFACT_MAX_BYTES,
        )
    except ReferenceIngestError as exc:
        raise HTTPException(422, str(exc)) from exc
    if not downloaded.video:
        raise HTTPException(422, "downloaded video is empty")
    if len(downloaded.video) > CANVAS_ARTIFACT_MAX_BYTES:
        raise HTTPException(413, "downloaded video exceeds the 250 MB Canvas limit")

    content_type = downloaded.video_content_type.split(";", 1)[0].lower()
    if not content_type.startswith("video/"):
        raise HTTPException(415, "the URL did not resolve to a supported video")
    title = (
        re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "-", inspected.title).strip(" .")
        or inspected.source_id
    )
    suffix = {
        "video/mp4": ".mp4",
        "video/webm": ".webm",
        "video/quicktime": ".mov",
        "video/mkv": ".mkv",
        "video/x-matroska": ".mkv",
    }.get(content_type, extension_for(content_type))
    if suffix == ".bin":
        suffix = ".video"
    filename = f"{title[:180]}{suffix}"
    artifact = create_artifact(
        db,
        "Video",
        content=downloaded.video,
        content_type=content_type,
        filename=filename,
        metadata={
            "source": "canvas_url_import",
            "source_url": inspected.canonical_url,
            "source_id": inspected.source_id,
            "source_title": inspected.title,
            "source_creator": inspected.creator,
            "downloader_provider": provider.provider_name,
            "duration_ms": inspected.duration_ms,
            "filename": filename,
            "immutable": True,
        },
    )
    db.flush()
    try:
        playback_artifact = ensure_video_playback_artifact(
            db,
            artifact,
            content=downloaded.video,
            content_type=content_type,
            filename=filename,
        )
    except BrowserVideoError as exc:
        db.rollback()
        raise HTTPException(422, str(exc)) from exc
    audit(
        db,
        "artifact.canvas_url_imported",
        artifact.id,
        {
            "source_url": inspected.canonical_url,
            "downloader_provider": provider.provider_name,
            "content_type": content_type,
            "size_bytes": len(downloaded.video),
        },
    )
    db.commit()
    return {
        "artifact_id": artifact.id,
        "type": artifact.type,
        "content_type": content_type,
        "size_bytes": len(downloaded.video),
        "filename": filename,
        "source_url": inspected.canonical_url,
        "downloader_provider": provider.provider_name,
        "url": artifact_content_url(playback_artifact.id),
    }


@router.post("/artifacts/upload", status_code=status.HTTP_201_CREATED)
async def upload_artifact(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    content_type = (file.content_type or "application/octet-stream").split(";", 1)[0].lower()
    if content_type == "application/octet-stream" and file.filename:
        content_type = (mimetypes.guess_type(file.filename)[0] or content_type).lower()
    artifact_type = (
        "Image"
        if content_type.startswith("image/")
        else "Video"
        if content_type.startswith("video/")
        else "Audio"
        if content_type.startswith("audio/")
        else "Text"
        if content_type.startswith("text/")
        else None
    )
    if not artifact_type:
        raise HTTPException(
            415,
            "only image, video, audio, and text files can be added to the Canvas",
        )
    content = await file.read(CANVAS_ARTIFACT_MAX_BYTES + 1)
    if not content:
        raise HTTPException(422, "uploaded file is empty")
    if len(content) > CANVAS_ARTIFACT_MAX_BYTES:
        raise HTTPException(413, "uploaded file exceeds the 250 MB Canvas limit")
    artifact = create_artifact(
        db,
        artifact_type,
        content=content,
        content_type=content_type,
        filename=file.filename or "upload.bin",
        metadata={
            "source": "canvas_upload",
            "filename": file.filename or "upload.bin",
            "immutable": True,
        },
    )
    db.flush()
    playback_artifact = artifact
    if artifact_type == "Video":
        try:
            playback_artifact = ensure_video_playback_artifact(
                db,
                artifact,
                content=content,
                content_type=content_type,
                filename=file.filename or "upload.mp4",
            )
        except BrowserVideoError as exc:
            db.rollback()
            raise HTTPException(422, str(exc)) from exc
    audit(
        db,
        "artifact.canvas_uploaded",
        artifact.id,
        {"content_type": content_type, "size_bytes": len(content)},
    )
    db.commit()
    return {
        "artifact_id": artifact.id,
        "type": artifact.type,
        "content_type": content_type,
        "size_bytes": len(content),
        "filename": file.filename or "upload.bin",
        "url": artifact_content_url(playback_artifact.id),
    }


@router.post(
    "/artifacts/{artifact_id}/image-edits",
    status_code=status.HTTP_201_CREATED,
)
async def save_manual_image_edit(
    artifact_id: str,
    file: UploadFile = File(...),
    edit_document: str = Form(...),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    source = db.get(ArtifactRecord, artifact_id)
    if not source:
        raise HTTPException(404, "source image artifact not found")
    if source.type != "Image":
        raise HTTPException(415, "only image artifacts can be edited")
    content_type = (file.content_type or "").split(";", 1)[0].lower()
    if content_type not in {"image/png", "image/jpeg", "image/webp"}:
        raise HTTPException(415, "edited image must be PNG, JPEG, or WebP")
    if len(edit_document.encode()) > 32_000:
        raise HTTPException(413, "image edit document is too large")
    try:
        document = ImageEditDocument.model_validate(json.loads(edit_document))
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(422, f"invalid image edit document: {exc}") from exc
    content = await file.read(CANVAS_ARTIFACT_MAX_BYTES + 1)
    if not content:
        raise HTTPException(422, "edited image is empty")
    if len(content) > CANVAS_ARTIFACT_MAX_BYTES:
        raise HTTPException(413, "edited image exceeds the 250 MB Canvas limit")

    source_filename = str(source.metadata_json.get("filename") or f"{source.id}.png")
    source_stem = re.sub(r"\.[A-Za-z0-9]{1,10}$", "", source_filename)
    safe_stem = (
        re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "-", source_stem).strip(" .")
        or source.id
    )
    extension = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/webp": ".webp",
    }[content_type]
    filename = f"{safe_stem[:170]}-edited{extension}"
    document_payload = document.model_dump(exclude_none=True)
    artifact = create_artifact(
        db,
        "Image",
        schema_id="image.manual-edit.v1",
        input_artifact_ids=[source.id],
        input_artifact_roles={source.id: "source_image"},
        content=content,
        content_type=content_type,
        filename=filename,
        metadata={
            "source": "image_manual_edit",
            "filename": filename,
            "operation": "image.manual.edit",
            "image_edit": document_payload,
            "immutable": True,
        },
    )
    db.flush()
    audit(
        db,
        "artifact.image_manually_edited",
        artifact.id,
        {
            "source_artifact_id": source.id,
            "content_type": content_type,
            "image_edit": document_payload,
        },
    )
    db.commit()
    return {
        "id": artifact.id,
        "created_at": artifact.created_at,
        "type": artifact.type,
        "content_type": content_type,
        "size_bytes": len(content),
        "filename": filename,
        "source": "image_manual_edit",
        "duration_ms": 0,
        "url": artifact_content_url(artifact.id),
    }


@router.get("/artifacts/{artifact_id}/download-url")
def artifact_download_url(
    artifact_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    artifact = db.get(ArtifactRecord, artifact_id)
    if not artifact:
        raise HTTPException(404, "artifact not found")
    storage = get_storage()
    try:
        bucket, key = storage_location(artifact.uri, artifact.metadata_json)
        url = storage.create_download_url(bucket=bucket, key=key)
    except StorageError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {
        "provider": storage.settings.provider,
        "url": url,
        "expires_in_seconds": storage.settings.signed_url_ttl_seconds,
    }


@router.get("/artifacts/{artifact_id}/content")
def artifact_content(
    artifact_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> Response:
    artifact = db.get(ArtifactRecord, artifact_id)
    if not artifact:
        raise HTTPException(404, "artifact not found")
    storage = get_storage()
    try:
        bucket, key = storage_location(artifact.uri, artifact.metadata_json)
        if storage.settings.provider == "memory":
            content_type = str(
                (artifact.metadata_json.get("storage") or {}).get("content_type")
                or "application/octet-stream"
            )
            content = storage.get_bytes(bucket=bucket, key=key)
            range_header = request.headers.get("range")
            if not range_header:
                return Response(
                    content,
                    media_type=content_type,
                    headers={
                        "Accept-Ranges": "bytes",
                        "Content-Length": str(len(content)),
                    },
                )
            match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header.strip())
            if not match or not any(match.groups()):
                return Response(
                    status_code=416,
                    headers={"Content-Range": f"bytes */{len(content)}"},
                )
            start_text, end_text = match.groups()
            if start_text:
                start = int(start_text)
                end = (
                    min(int(end_text), len(content) - 1)
                    if end_text
                    else len(content) - 1
                )
            else:
                suffix_length = int(end_text)
                start = max(0, len(content) - suffix_length)
                end = len(content) - 1
            if start >= len(content) or end < start:
                return Response(
                    status_code=416,
                    headers={"Content-Range": f"bytes */{len(content)}"},
                )
            partial = content[start : end + 1]
            return Response(
                partial,
                status_code=206,
                media_type=content_type,
                headers={
                    "Accept-Ranges": "bytes",
                    "Content-Range": f"bytes {start}-{end}/{len(content)}",
                    "Content-Length": str(len(partial)),
                },
            )
        url = storage.create_download_url(bucket=bucket, key=key)
    except StorageError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse(url, status_code=307)
