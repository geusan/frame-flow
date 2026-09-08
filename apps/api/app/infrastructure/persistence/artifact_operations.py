from __future__ import annotations

import base64
import mimetypes
import re
from typing import Any, Callable, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...artifact_lineage import artifact_lineage_graph
from ...character_lora import (
    refresh_character_lora_training,
    start_character_lora_training as submit_character_lora_training,
)
from ...character_motion.validation import inspect_glb
from ...contexts.artifacts.application import (
    CaptureFrameCommand,
    ImportArtifactUrlCommand,
    SaveImageEditCommand,
    SceneSearchCommand,
    TrainCharacterLoraCommand,
    UploadArtifactCommand,
)
from ...contexts.artifacts.domain import (
    ArtifactConflictError,
    ArtifactNotFoundError,
    ArtifactPayloadTooLargeError,
    ArtifactServiceUnavailableError,
    ArtifactUnsupportedMediaError,
    ArtifactValidationError,
    BinaryContent,
    CANVAS_ARTIFACT_MAX_BYTES,
    StoredContent,
)
from ...database import ArtifactRecord, SessionLocal
from ...domain import FrameCaptureRequest, SceneSearchRequest
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


class LegacySqlAlchemyArtifactOperations:
    """Strangler adapter around Artifact persistence, storage, and media providers."""

    def __init__(
        self,
        session_factory: Callable[[], Session] = SessionLocal,
    ) -> None:
        self._session_factory = session_factory

    def list_artifacts(
        self,
        types: str,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        requested = {value.strip() for value in types.split(",") if value.strip()}
        with self._session_factory() as db:
            rows = db.scalars(
                select(ArtifactRecord)
                .where(ArtifactRecord.type.in_(requested))
                .order_by(ArtifactRecord.created_at.desc())
                .offset(offset)
                .limit(limit)
            ).all()
            result: list[dict[str, Any]] = []
            for row in rows:
                playback_id = str(
                    row.metadata_json.get("playback_artifact_id") or row.id
                )
                result.append(
                    {
                        "id": row.id,
                        "created_at": row.created_at,
                        "type": row.type,
                        "content_type": str(
                            (row.metadata_json.get("storage") or {}).get(
                                "content_type"
                            )
                            or "application/octet-stream"
                        ),
                        "size_bytes": int(
                            (row.metadata_json.get("storage") or {}).get("size_bytes")
                            or 0
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
                        "duration_ms": int(
                            row.metadata_json.get("duration_ms") or 0
                        ),
                        "url": artifact_content_url(playback_id),
                    }
                )
            return result

    def list_characters(self) -> list[dict[str, Any]]:
        with self._session_factory() as db:
            rows = db.scalars(
                select(ArtifactRecord)
                .where(ArtifactRecord.type == "Character")
                .order_by(ArtifactRecord.created_at.desc())
            ).all()
            result: list[dict[str, Any]] = []
            for row in rows:
                metadata = row.metadata_json or {}
                image_ids = [
                    str(value) for value in metadata.get("image_artifact_ids") or []
                ]
                roles = [str(value) for value in metadata.get("image_roles") or []]
                images = [
                    {
                        "artifact_id": artifact_id,
                        "role": (
                            roles[index]
                            if index < len(roles)
                            else f"view_{index + 1}"
                        ),
                        "url": artifact_content_url(artifact_id),
                    }
                    for index, artifact_id in enumerate(image_ids)
                    if db.get(ArtifactRecord, artifact_id)
                ]
                cover_id = str(
                    metadata.get("cover_artifact_id")
                    or (image_ids[0] if image_ids else "")
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
                        "exact_model_id": str(
                            metadata.get("exact_model_id") or ""
                        ),
                        "cover_url": (
                            artifact_content_url(cover_id) if cover_id else None
                        ),
                        "image_count": len(images),
                        "images": images,
                        "lora": {
                            "status": str(
                                metadata.get("lora_status") or "UNTRAINED"
                            ),
                            "trigger_word": str(
                                metadata.get("lora_trigger_word") or ""
                            ),
                            "training_artifact_id": metadata.get(
                                "lora_training_artifact_id"
                            ),
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

    def start_character_lora(
        self,
        command: TrainCharacterLoraCommand,
    ) -> dict[str, Any]:
        with self._session_factory() as db:
            try:
                return submit_character_lora_training(
                    db,
                    command.character_id,
                    trigger_word=command.trigger_word,
                    steps=command.steps,
                    learning_rate=command.learning_rate,
                    service=get_fal_generation_services(),
                    dataset_store=get_r2_training_dataset_store(),
                )
            except ValueError as exc:
                if str(exc) == "character not found":
                    raise ArtifactNotFoundError(str(exc)) from exc
                if "already running" in str(exc):
                    raise ArtifactConflictError(str(exc)) from exc
                raise ArtifactValidationError(str(exc)) from exc

    def get_character_lora(self, character_id: str) -> dict[str, Any]:
        with self._session_factory() as db:
            try:
                return refresh_character_lora_training(
                    db,
                    character_id,
                    service=get_fal_generation_services(),
                )
            except ValueError as exc:
                if str(exc) == "character not found":
                    raise ArtifactNotFoundError(str(exc)) from exc
                if "artifact is missing" in str(exc):
                    raise ArtifactConflictError(str(exc)) from exc
                raise ArtifactValidationError(str(exc)) from exc

    def get_artifact(self, artifact_id: str) -> Any:
        with self._session_factory() as db:
            artifact = db.get(ArtifactRecord, artifact_id)
            if artifact is None:
                raise ArtifactNotFoundError("artifact not found")
            return artifact_response(artifact)

    def create_audio_asset(self, artifact_id: str) -> dict[str, Any]:
        with self._session_factory() as db:
            source = db.get(ArtifactRecord, artifact_id)
            if source is None:
                raise ArtifactNotFoundError("reference audio artifact not found")
            allowed_types = {
                "ReferenceAudioMix": "reference-audio.wav",
                "ReferenceVocals": "vocals.wav",
                "ReferenceAccompaniment": "accompaniment.wav",
            }
            if source.type not in allowed_types:
                raise ArtifactUnsupportedMediaError(
                    "only Reference Analyzer audio outputs can be saved as Audio assets"
                )
            existing = next(
                (
                    artifact
                    for artifact in db.scalars(
                        select(ArtifactRecord).where(ArtifactRecord.type == "Audio")
                    ).all()
                    if artifact.metadata_json.get("source")
                    == "reference_audio_export"
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
                        existing.metadata_json.get("filename")
                        or allowed_types[source.type]
                    ),
                    "source": "reference_audio_export",
                    "url": artifact_content_url(existing.id),
                }
            storage = get_storage()
            try:
                bucket, key = storage_location(source.uri, source.metadata_json)
                content = storage.get_bytes(bucket=bucket, key=key)
            except StorageError as exc:
                raise ArtifactConflictError(str(exc)) from exc
            source_storage = source.metadata_json.get("storage") or {}
            content_type = str(source_storage.get("content_type") or "audio/wav")
            filename = str(
                source.metadata_json.get("filename") or allowed_types[source.type]
            )
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
                "content_type": str(
                    artifact_storage.get("content_type") or content_type
                ),
                "size_bytes": int(
                    artifact_storage.get("size_bytes") or len(content)
                ),
                "filename": filename,
                "source": "reference_audio_export",
                "url": artifact_content_url(artifact.id),
            }

    def get_lineage(
        self,
        artifact_id: str,
        direction: Literal["ancestors", "descendants", "both"],
        depth: int,
    ) -> dict[str, object]:
        with self._session_factory() as db:
            try:
                return artifact_lineage_graph(
                    db,
                    artifact_id,
                    direction=direction,
                    depth=depth,
                )
            except ValueError as exc:
                raise ArtifactNotFoundError(str(exc)) from exc

    def search_scenes(self, command: SceneSearchCommand) -> dict[str, object]:
        payload = SceneSearchRequest.model_validate(command.values)
        with self._session_factory() as db:
            source = db.get(ArtifactRecord, command.artifact_id)
            if source is None:
                raise ArtifactNotFoundError("source video artifact not found")
            if source.type not in {"Video", "FinalVideo"}:
                raise ArtifactUnsupportedMediaError(
                    "only video artifacts support scene search"
                )
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
                raise ArtifactConflictError(str(exc)) from exc
            except SceneSearchError as exc:
                raise ArtifactValidationError(str(exc)) from exc
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

    def capture_frame(self, command: CaptureFrameCommand) -> dict[str, Any]:
        payload = FrameCaptureRequest.model_validate(command.values)
        with self._session_factory() as db:
            source = db.get(ArtifactRecord, command.artifact_id)
            if source is None:
                raise ArtifactNotFoundError("source video artifact not found")
            if source.type not in {"Video", "FinalVideo"}:
                raise ArtifactUnsupportedMediaError(
                    "only video artifacts support frame capture"
                )
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
                raise ArtifactConflictError(str(exc)) from exc
            except MediaCaptureError as exc:
                raise ArtifactValidationError(str(exc)) from exc
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
            timestamp_label = (
                f"{hours:02d}-{minutes:02d}-{seconds:02d}-{milliseconds:03d}"
            )
            filename = f"{safe_stem[:150]}-frame-{timestamp_label}.jpg"
            search_context = payload.model_dump(
                exclude={"timestamp_ms"},
                exclude_none=True,
            )
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

    def preview_frame(self, artifact_id: str, timestamp_ms: int) -> BinaryContent:
        with self._session_factory() as db:
            source = db.get(ArtifactRecord, artifact_id)
            if source is None:
                raise ArtifactNotFoundError("source video artifact not found")
            if source.type not in {"Video", "FinalVideo"}:
                raise ArtifactUnsupportedMediaError(
                    "only video artifacts support frame previews"
                )
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
                raise ArtifactConflictError(str(exc)) from exc
            except MediaCaptureError as exc:
                raise ArtifactValidationError(str(exc)) from exc
            return BinaryContent(
                data=captured.content,
                content_type=captured.content_type,
                headers={
                    "Cache-Control": "public, max-age=86400, immutable",
                    "X-Frame-Timestamp-Ms": str(captured.timestamp_ms),
                    "X-Source-Duration-Ms": str(captured.source_duration_ms),
                },
            )

    def create_upload_target(self, filename: str, content_type: str) -> dict[str, Any]:
        upload_id = new_id("upload")
        storage = get_storage()
        key = safe_upload_key(upload_id, filename)
        try:
            target = storage.create_upload_url(
                bucket=storage.settings.buckets.generation,
                key=key,
                content_type=content_type,
            )
        except StorageError as exc:
            raise ArtifactServiceUnavailableError(str(exc)) from exc
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

    def import_url(self, command: ImportArtifactUrlCommand) -> dict[str, Any]:
        try:
            provider = get_video_downloader()
            inspected = provider.inspect(command.url)
            downloaded = provider.download(
                inspected.canonical_url,
                max_duration_seconds=600,
                max_filesize_bytes=CANVAS_ARTIFACT_MAX_BYTES,
            )
        except ReferenceIngestError as exc:
            raise ArtifactValidationError(str(exc)) from exc
        if not downloaded.video:
            raise ArtifactValidationError("downloaded video is empty")
        if len(downloaded.video) > CANVAS_ARTIFACT_MAX_BYTES:
            raise ArtifactPayloadTooLargeError(
                "downloaded video exceeds the 250 MB Canvas limit"
            )
        content_type = downloaded.video_content_type.split(";", 1)[0].lower()
        if not content_type.startswith("video/"):
            raise ArtifactUnsupportedMediaError(
                "the URL did not resolve to a supported video"
            )
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
        with self._session_factory() as db:
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
                raise ArtifactValidationError(str(exc)) from exc
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

    def upload(self, command: UploadArtifactCommand) -> dict[str, Any]:
        content_type = command.content_type.split(";", 1)[0].lower()
        if content_type == "application/octet-stream" and command.filename:
            content_type = (
                mimetypes.guess_type(command.filename)[0] or content_type
            ).lower()
        is_glb = command.filename.lower().endswith(".glb") or content_type == "model/gltf-binary"
        if is_glb:
            content_type = "model/gltf-binary"
        artifact_type = (
            "Model3D"
            if is_glb
            else "Image"
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
            raise ArtifactUnsupportedMediaError(
                "only image, video, audio, text, and binary glTF (.glb) files can be added to the Canvas"
            )
        if not command.content:
            raise ArtifactValidationError("uploaded file is empty")
        if len(command.content) > CANVAS_ARTIFACT_MAX_BYTES:
            raise ArtifactPayloadTooLargeError(
                "uploaded file exceeds the 250 MB Canvas limit"
            )
        if artifact_type == "Model3D":
            try:
                model_validation = inspect_glb(command.content)
            except ValueError as exc:
                raise ArtifactValidationError(str(exc)) from exc
            if not model_validation["valid"]:
                raise ArtifactValidationError(
                    "uploaded GLB does not contain a usable mesh"
                )
        else:
            model_validation = None
        with self._session_factory() as db:
            artifact = create_artifact(
                db,
                artifact_type,
                content=command.content,
                content_type=content_type,
                filename=command.filename,
                metadata={
                    "source": "canvas_upload",
                    "filename": command.filename,
                    "immutable": True,
                    **({"validation": model_validation} if model_validation else {}),
                },
            )
            db.flush()
            playback_artifact = artifact
            if artifact_type == "Video":
                try:
                    playback_artifact = ensure_video_playback_artifact(
                        db,
                        artifact,
                        content=command.content,
                        content_type=content_type,
                        filename=command.filename,
                    )
                except BrowserVideoError as exc:
                    db.rollback()
                    raise ArtifactValidationError(str(exc)) from exc
            audit(
                db,
                "artifact.canvas_uploaded",
                artifact.id,
                {
                    "content_type": content_type,
                    "size_bytes": len(command.content),
                },
            )
            db.commit()
            return {
                "artifact_id": artifact.id,
                "type": artifact.type,
                "content_type": content_type,
                "size_bytes": len(command.content),
                "filename": command.filename,
                "url": artifact_content_url(playback_artifact.id),
            }

    def save_image_edit(self, command: SaveImageEditCommand) -> dict[str, Any]:
        with self._session_factory() as db:
            source = db.get(ArtifactRecord, command.artifact_id)
            if source is None:
                raise ArtifactNotFoundError("source image artifact not found")
            if source.type != "Image":
                raise ArtifactUnsupportedMediaError(
                    "only image artifacts can be edited"
                )
            content_type = command.content_type.split(";", 1)[0].lower()
            if content_type not in {"image/png", "image/jpeg", "image/webp"}:
                raise ArtifactUnsupportedMediaError(
                    "edited image must be PNG, JPEG, or WebP"
                )
            if not command.content:
                raise ArtifactValidationError("edited image is empty")
            if len(command.content) > CANVAS_ARTIFACT_MAX_BYTES:
                raise ArtifactPayloadTooLargeError(
                    "edited image exceeds the 250 MB Canvas limit"
                )
            source_filename = str(
                source.metadata_json.get("filename") or f"{source.id}.png"
            )
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
            artifact = create_artifact(
                db,
                "Image",
                schema_id="image.manual-edit.v1",
                input_artifact_ids=[source.id],
                input_artifact_roles={source.id: "source_image"},
                content=command.content,
                content_type=content_type,
                filename=filename,
                metadata={
                    "source": "image_manual_edit",
                    "filename": filename,
                    "operation": "image.manual.edit",
                    "image_edit": command.document,
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
                    "image_edit": command.document,
                },
            )
            db.commit()
            return {
                "id": artifact.id,
                "created_at": artifact.created_at,
                "type": artifact.type,
                "content_type": content_type,
                "size_bytes": len(command.content),
                "filename": filename,
                "source": "image_manual_edit",
                "duration_ms": 0,
                "url": artifact_content_url(artifact.id),
            }

    def create_download_url(self, artifact_id: str) -> dict[str, Any]:
        with self._session_factory() as db:
            artifact = db.get(ArtifactRecord, artifact_id)
            if artifact is None:
                raise ArtifactNotFoundError("artifact not found")
            storage = get_storage()
            try:
                bucket, key = storage_location(artifact.uri, artifact.metadata_json)
                url = storage.create_download_url(bucket=bucket, key=key)
            except StorageError as exc:
                raise ArtifactConflictError(str(exc)) from exc
            return {
                "provider": storage.settings.provider,
                "url": url,
                "expires_in_seconds": storage.settings.signed_url_ttl_seconds,
            }

    def get_content(self, artifact_id: str) -> StoredContent:
        with self._session_factory() as db:
            artifact = db.get(ArtifactRecord, artifact_id)
            if artifact is None:
                raise ArtifactNotFoundError("artifact not found")
            storage = get_storage()
            try:
                bucket, key = storage_location(artifact.uri, artifact.metadata_json)
                content_type = str(
                    (artifact.metadata_json.get("storage") or {}).get("content_type")
                    or "application/octet-stream"
                )
                if storage.settings.provider == "memory":
                    return StoredContent(
                        content_type=content_type,
                        data=storage.get_bytes(bucket=bucket, key=key),
                    )
                return StoredContent(
                    content_type=content_type,
                    redirect_url=storage.create_download_url(bucket=bucket, key=key),
                )
            except StorageError as exc:
                raise ArtifactConflictError(str(exc)) from exc
