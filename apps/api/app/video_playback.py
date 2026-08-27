from __future__ import annotations

from sqlalchemy.orm import Session

from .database import ArtifactRecord
from .media_compat import BrowserVideoResult, ensure_browser_video
from .service import create_artifact
from .storage import get_storage, storage_location


def ensure_video_playback_artifact(
    db: Session,
    source: ArtifactRecord,
    *,
    content: bytes | None = None,
    content_type: str | None = None,
    filename: str | None = None,
) -> ArtifactRecord:
    existing_id = str((source.metadata_json or {}).get("playback_artifact_id") or "")
    if existing_id:
        existing = db.get(ArtifactRecord, existing_id)
        if existing:
            return existing
    storage_metadata = (source.metadata_json or {}).get("storage") or {}
    resolved_content_type = content_type or str(storage_metadata.get("content_type") or "video/mp4")
    if content is None:
        bucket, key = storage_location(source.uri, source.metadata_json)
        content = get_storage().get_bytes(bucket=bucket, key=key)
    result = ensure_browser_video(content, resolved_content_type)
    _record_playback_metadata(source, result)
    if not result.transcoded:
        return source
    source_filename = filename or str((source.metadata_json or {}).get("filename") or f"{source.id}.mp4")
    proxy = create_artifact(
        db,
        "VideoProxy",
        content=result.content,
        content_type=result.content_type,
        filename=f"{source_filename.rsplit('.', 1)[0]}-browser.mp4",
        input_artifact_ids=[source.id],
        input_artifact_roles={source.id: "source_video"},
        metadata={
            "source": "browser_playback_proxy",
            "source_artifact_id": source.id,
            "operation": "video.browser_compat.h264.v1",
            "filename": f"{source_filename.rsplit('.', 1)[0]}-browser.mp4",
            "duration_ms": result.duration_ms,
            "video_codec": result.video_codec,
            "audio_codec": result.audio_codec,
            "width": result.width,
            "height": result.height,
            "immutable": True,
        },
    )
    db.flush()
    source.metadata_json = {**(source.metadata_json or {}), "playback_artifact_id": proxy.id}
    return proxy


def _record_playback_metadata(source: ArtifactRecord, result: BrowserVideoResult) -> None:
    metadata = dict(source.metadata_json or {})
    source.metadata_json = {
        **metadata,
        "video_codec": result.video_codec,
        "audio_codec": result.audio_codec,
        "width": result.width,
        "height": result.height,
        **({"duration_ms": result.duration_ms} if result.duration_ms and not metadata.get("duration_ms") else {}),
    }
