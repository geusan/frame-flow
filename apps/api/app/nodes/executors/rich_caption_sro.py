from __future__ import annotations

import json
import math
import tempfile
from pathlib import Path
from typing import Any

from ...canvas_operations import ArtifactData, _of_type, _probe, _read_artifacts, _run, _video_stream, _write_artifact
from ...caption_documents import canonical_caption_document, caption_document_to_ass, materialize_caption_fonts
from ...database import ArtifactRecord
from ...image_story_video import output_dimensions
from ...service import create_artifact
from ...storage import artifact_content_url, get_storage, storage_location
from ..contracts import NodeExecutionContext, NodeExecutionResult
from .text_support import input_lineage


SUBTITLE_DESIGN_REVISION = "subtitle-design.v1"
SUBTITLE_LAYOUT_V2_REVISION = "subtitle-layout.v2"
SUBTITLE_LAYOUT_V3_REVISION = "subtitle-layout.v3"
VIDEO_CAPTION_BURN_REVISION = "video-caption-burn.v1"
VIDEO_CAPTION_BURN_V2_REVISION = "video-caption-burn.v2"
VIDEO_TYPES = {"Video", "FinalVideo", "ProxyVideo"}


def _result(
    context: NodeExecutionContext,
    artifact: ArtifactRecord,
    *,
    output: dict[str, object],
    input_ids: list[str],
    input_roles: dict[str, str],
    revision: str,
) -> NodeExecutionResult:
    return NodeExecutionResult(
        output={**output, "url": artifact_content_url(artifact.id)},
        output_artifact_ids=[artifact.id],
        provider_request_id=f"local_{context.request_hash[:20]}",
        cost_usd=0.0,
        metadata={
            "artifact_type": context.definition.artifact_contract.primary_type,
            "schema_id": context.definition.artifact_contract.schema_id,
            "input_artifact_ids": input_ids,
            "lineage_roles": input_roles,
            "retryable": False,
            "executor_revision": revision,
        },
    )


def _json_payload(artifact: ArtifactData, *, schema: str, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(artifact.data)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} requires a valid JSON Artifact") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != schema:
        raise ValueError(f"{label} requires a {schema} Artifact")
    return payload


class SubtitleDesignExecutor:
    def execute(
        self,
        context: NodeExecutionContext,
        resolved_node_config: dict[str, Any],
        typed_inputs: list[dict[str, Any]],
    ) -> NodeExecutionResult:
        if context.definition.execution.revision != SUBTITLE_DESIGN_REVISION:
            raise RuntimeError("Subtitle Design executor revision does not match its Node Definition")
        artifacts = _read_artifacts(context.db, typed_inputs)
        subtitles = _of_type(artifacts, "Subtitle", "ReferenceSubtitle")
        if len(subtitles) != 1:
            raise ValueError("Subtitle Design requires one connected Timed Subtitle Artifact")
        document = canonical_caption_document(context.db, dict(resolved_node_config["caption_document"]))
        content = json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        input_ids, input_roles = input_lineage(context, typed_inputs)
        artifact = create_artifact(
            context.db,
            context.definition.artifact_contract.primary_type,
            schema_id=context.definition.artifact_contract.schema_id,
            input_artifact_ids=input_ids,
            input_artifact_roles=input_roles,
            metadata={
                "experiment_id": context.experiment_id,
                "request_hash": context.request_hash,
                "execution_mode": SUBTITLE_DESIGN_REVISION,
                "immutable": True,
                "source": "subtitle_design",
                "normalized_config": resolved_node_config,
                "font_snapshots": document["fonts"],
                "cue_count": len(document["cues"]),
                "output_role": context.definition.artifact_contract.output_role,
            },
            content=content,
            content_type="application/json",
            filename="caption-document.json",
        )
        context.db.flush()
        return _result(
            context,
            artifact,
            output={"kind": "json", "title": f"Caption document · {len(document['cues'])} cues", "text": json.dumps(document, ensure_ascii=False, indent=2)},
            input_ids=input_ids,
            input_roles=input_roles,
            revision=SUBTITLE_DESIGN_REVISION,
        )


class RichSubtitleLayoutExecutor:
    def execute(
        self,
        context: NodeExecutionContext,
        resolved_node_config: dict[str, Any],
        typed_inputs: list[dict[str, Any]],
    ) -> NodeExecutionResult:
        revision = context.definition.execution.revision
        if revision not in {SUBTITLE_LAYOUT_V2_REVISION, SUBTITLE_LAYOUT_V3_REVISION}:
            raise RuntimeError("Rich Subtitle Layout executor revision does not match its Node Definition")
        artifacts = _read_artifacts(context.db, typed_inputs)
        documents = _of_type(artifacts, "CaptionDocument")
        if len(documents) != 1:
            raise ValueError("Rich Subtitle Layout requires one Caption Document")
        document_artifact = documents[0]
        _json_payload(document_artifact, schema="caption.document.v1", label="Rich Subtitle Layout")
        config = resolved_node_config
        frame = {
            "x": float(config["frame_x"]),
            "y": float(config["frame_y"]),
            "width": float(config["frame_width"]),
            "height": float(config["frame_height"]),
        }
        if frame["x"] + frame["width"] > 1 or frame["y"] + frame["height"] > 1:
            raise ValueError("Caption placement must stay inside the Video Canvas")
        source = {
            "artifact_id": document_artifact.record.id,
            "sha256": document_artifact.record.sha256,
            "schema_id": "caption.document.v1",
        }
        metadata_snapshot: dict[str, Any]
        if revision == SUBTITLE_LAYOUT_V2_REVISION:
            videos = _of_type(artifacts, *VIDEO_TYPES)
            if len(videos) != 1:
                raise ValueError("Rich Subtitle Layout v2 requires one Video")
            video = videos[0]
            with tempfile.TemporaryDirectory(prefix="frameflow-caption-layout-") as temp_dir:
                video_path = _write_artifact(Path(temp_dir), video, 0)
                stream = _video_stream(_probe(video_path))
            width = int(stream.get("width") or 0)
            height = int(stream.get("height") or 0)
            if width <= 0 or height <= 0:
                raise ValueError("Rich Subtitle Layout could not resolve Video dimensions")
            layout = {
                "schema_version": "subtitle.layout.v2",
                "source": source,
                "canvas": {
                    "video_artifact_id": video.record.id,
                    "video_sha256": video.record.sha256,
                    "width": width,
                    "height": height,
                    "preview_aspect_ratio": str(config["aspect_ratio"]),
                },
                "frame": frame,
                "align": str(config["align"]),
            }
            metadata_snapshot = {"video_sha256": video.record.sha256}
        else:
            media_frames = _of_type(artifacts, "MediaFrame")
            if len(media_frames) != 1:
                raise ValueError("Rich Subtitle Layout v3 requires one Media Frame")
            media_frame_artifact = media_frames[0]
            media_frame_layout = _json_payload(
                media_frame_artifact,
                schema="layout.media_frame.v1",
                label="Rich Subtitle Layout",
            )
            media_canvas = dict(media_frame_layout.get("canvas") or {})
            media_frame = dict(media_frame_layout.get("frame") or {})
            aspect_ratio = str(media_canvas.get("aspect_ratio") or "")
            resolution = str(media_canvas.get("resolution") or "")
            width, height = output_dimensions(aspect_ratio, resolution)
            layout = {
                "schema_version": "subtitle.layout.v3",
                "source": source,
                "canvas": {
                    "media_frame_artifact_id": media_frame_artifact.record.id,
                    "media_frame_sha256": media_frame_artifact.record.sha256,
                    "aspect_ratio": aspect_ratio,
                    "resolution": resolution,
                    "background_color": str(media_canvas.get("background_color") or "#000000"),
                    "width": width,
                    "height": height,
                },
                "media_frame": media_frame,
                "caption_frame": frame,
                "align": str(config["align"]),
            }
            metadata_snapshot = {"media_frame_sha256": media_frame_artifact.record.sha256}
        content = json.dumps(layout, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        input_ids, input_roles = input_lineage(context, typed_inputs)
        artifact = create_artifact(
            context.db,
            context.definition.artifact_contract.primary_type,
            schema_id=context.definition.artifact_contract.schema_id,
            input_artifact_ids=input_ids,
            input_artifact_roles=input_roles,
            metadata={
                "experiment_id": context.experiment_id,
                "request_hash": context.request_hash,
                "execution_mode": revision,
                "immutable": True,
                "source": "rich_subtitle_layout",
                "normalized_config": config,
                "caption_document_sha256": document_artifact.record.sha256,
                **metadata_snapshot,
                "output_role": context.definition.artifact_contract.output_role,
            },
            content=content,
            content_type="application/json",
            filename="caption-layout.json",
        )
        context.db.flush()
        return _result(
            context,
            artifact,
            output={"kind": "json", "title": "Caption placement", "text": json.dumps(layout, ensure_ascii=False, indent=2)},
            input_ids=input_ids,
            input_roles=input_roles,
            revision=revision,
        )


def _read_record(record: ArtifactRecord) -> ArtifactData:
    bucket, key = storage_location(record.uri, record.metadata_json)
    content_type = str((record.metadata_json.get("storage") or {}).get("content_type") or "application/octet-stream")
    return ArtifactData(record, get_storage().get_bytes(bucket=bucket, key=key), content_type)


def _render_captioned_video(
    db_context: NodeExecutionContext,
    video: ArtifactData,
    layout: dict[str, Any],
    document: dict[str, Any],
) -> tuple[bytes, dict[str, int]]:
    with tempfile.TemporaryDirectory(prefix="frameflow-caption-burn-") as temp_dir:
        directory = Path(temp_dir)
        video_path = _write_artifact(directory, video, 0)
        stream = _video_stream(_probe(video_path))
        width = int(stream.get("width") or 0)
        height = int(stream.get("height") or 0)
        canvas = dict(layout["canvas"])
        if width != int(canvas["width"]) or height != int(canvas["height"]):
            raise ValueError("Caption Layout dimensions do not match the source Video")
        frame = dict(layout["caption_frame"] if layout["schema_version"] == "subtitle.layout.v3" else layout["frame"])
        ass_content = caption_document_to_ass(
            document,
            width=width,
            height=height,
            track_style={"align": layout["align"], "frame": frame},
        )
        subtitle_path = directory / "captions.ass"
        subtitle_path.write_text(ass_content, encoding="utf-8")
        fonts_directory = directory / "fonts"
        if document.get("fonts"):
            materialize_caption_fonts(db_context.db, document, fonts_directory)
        ass_filter = f"ass={subtitle_path.as_posix()}"
        if fonts_directory.is_dir():
            ass_filter += f":fontsdir={fonts_directory.as_posix()}"
        output_path = directory / "captioned.mp4"
        _run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(video_path),
            "-vf", ass_filter, "-map", "0:v:0", "-map", "0:a:0?",
            "-c:v", "libx264", "-profile:v", "high", "-preset", "veryfast", "-crf", "18",
            "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart", str(output_path),
        ], timeout=max(180, math.ceil(float((_probe(video_path).get("format") or {}).get("duration") or 1) * 12)))
        return output_path.read_bytes(), {"width": width, "height": height}


class VideoCaptionBurnExecutor:
    def execute(
        self,
        context: NodeExecutionContext,
        resolved_node_config: dict[str, Any],
        typed_inputs: list[dict[str, Any]],
    ) -> NodeExecutionResult:
        revision = context.definition.execution.revision
        if revision not in {VIDEO_CAPTION_BURN_REVISION, VIDEO_CAPTION_BURN_V2_REVISION}:
            raise RuntimeError("Video Caption Burn executor revision does not match its Node Definition")
        artifacts = _read_artifacts(context.db, typed_inputs)
        videos = _of_type(artifacts, *VIDEO_TYPES)
        layouts = _of_type(artifacts, "CaptionLayout")
        if len(videos) != 1 or len(layouts) != 1:
            raise ValueError("Video Caption Burn requires one Video and one Rich Caption Layout")
        video, layout_artifact = videos[0], layouts[0]
        layout_schema = "subtitle.layout.v3" if revision == VIDEO_CAPTION_BURN_V2_REVISION else "subtitle.layout.v2"
        layout = _json_payload(layout_artifact, schema=layout_schema, label="Video Caption Burn")
        if layout_schema == "subtitle.layout.v2" and layout.get("canvas", {}).get("video_sha256") != video.record.sha256:
            raise ValueError("Video Caption Burn source does not match the Caption Layout snapshot")
        document_ref = dict(layout["source"])
        document_record = context.db.get(ArtifactRecord, str(document_ref.get("artifact_id") or ""))
        if not document_record or document_record.type != "CaptionDocument" or document_record.sha256 != document_ref.get("sha256"):
            raise ValueError("Video Caption Burn Caption Document snapshot is unavailable or changed")
        document_artifact = _read_record(document_record)
        document = _json_payload(document_artifact, schema="caption.document.v1", label="Video Caption Burn")
        content, media = _render_captioned_video(context, video, layout, document)
        base_input_ids, base_roles = input_lineage(context, typed_inputs)
        font_artifact_ids = [str(item["artifact_id"]) for item in document.get("fonts") or []]
        input_ids = list(dict.fromkeys([*base_input_ids, document_record.id, *font_artifact_ids]))
        input_roles = {
            **base_roles,
            document_record.id: "caption_document",
            **{artifact_id: "caption_font" for artifact_id in font_artifact_ids},
        }
        artifact = create_artifact(
            context.db,
            context.definition.artifact_contract.primary_type,
            schema_id=context.definition.artifact_contract.schema_id,
            input_artifact_ids=input_ids,
            input_artifact_roles=input_roles,
            metadata={
                "experiment_id": context.experiment_id,
                "request_hash": context.request_hash,
                "execution_mode": revision,
                "immutable": True,
                "source": "video_caption_burn",
                "normalized_config": resolved_node_config,
                "caption_layout": layout,
                "font_snapshots": document.get("fonts") or [],
                **media,
                "output_role": context.definition.artifact_contract.output_role,
            },
            content=content,
            content_type="video/mp4",
            filename="captioned-video.mp4",
        )
        context.db.flush()
        return _result(
            context,
            artifact,
            output={"kind": "video", "title": "Captioned video", "mimeType": "video/mp4"},
            input_ids=input_ids,
            input_roles=input_roles,
            revision=revision,
        )
