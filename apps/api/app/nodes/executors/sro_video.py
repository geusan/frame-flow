from __future__ import annotations

import json
import math
import tempfile
from pathlib import Path
from typing import Any

from ...canvas_operations import (
    ArtifactData,
    _duration_seconds,
    _edit_videos,
    _of_type,
    _probe,
    _read_artifacts,
    _run,
    _video_stream,
    _write_artifact,
)
from ...database import ArtifactRecord
from ...image_story_video import _motion_filter, _subtitle_ass, output_dimensions, parse_srt_cues
from ...service import create_artifact
from ...storage import artifact_content_url, get_storage, storage_location
from ..contracts import NodeExecutionContext, NodeExecutionResult
from .text_support import input_lineage


IMAGE_MOTION_SCHEMA = "image.motion.v1"
IMAGE_MOTION_REVISION = "image-motion.v1"
MEDIA_FRAME_SCHEMA = "layout.media_frame.v1"
MEDIA_FRAME_REVISION = "media-frame-layout.v1"
FRAME_APPLY_SCHEMA = "video.frame_applied.v1"
FRAME_APPLY_REVISION = "video-frame-apply.v1"
FRAME_APPLY_V2_SCHEMA = "video.frame_applied.v2"
FRAME_APPLY_V2_REVISION = "video-frame-apply.v2"
VIDEO_CONCATENATE_SCHEMA = "video.concatenated.v1"
VIDEO_CONCATENATE_REVISION = "video-concatenate.v1"
SUBTITLE_LAYOUT_SCHEMA = "subtitle.layout.v1"
SUBTITLE_LAYOUT_REVISION = "subtitle-layout.v1"
VIDEO_COMPOSE_SCHEMA = "video.composed.v1"
VIDEO_COMPOSE_REVISION = "video-compose.v1"

VIDEO_TYPES = {"Video", "FinalVideo", "ProxyVideo"}


def _json_artifact(artifact: ArtifactData, *, schema: str, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(artifact.data)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} requires a valid JSON Artifact") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != schema:
        raise ValueError(f"{label} requires a {schema} Artifact")
    return payload


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


def _source_image(context: NodeExecutionContext, source: dict[str, Any]) -> tuple[ArtifactRecord, bytes, str]:
    artifact = context.db.get(ArtifactRecord, str(source.get("artifact_id") or ""))
    if not artifact or artifact.type != "Image":
        raise ValueError("Frame Apply source Image is unavailable")
    if source.get("sha256") and artifact.sha256 != source["sha256"]:
        raise ValueError("Frame Apply source Image no longer matches the motion snapshot")
    bucket, key = storage_location(artifact.uri, artifact.metadata_json)
    content_type = str((artifact.metadata_json.get("storage") or {}).get("content_type") or "application/octet-stream")
    return artifact, get_storage().get_bytes(bucket=bucket, key=key), content_type


def _image_suffix(content_type: str) -> str:
    suffix = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/webp": ".webp",
        "image/gif": ".gif",
    }.get(content_type.split(";", 1)[0].lower())
    if not suffix:
        raise ValueError(f"Frame Apply does not support Image content type: {content_type}")
    return suffix


def render_framed_motion(
    image: bytes,
    content_type: str,
    motion: dict[str, Any],
    config: dict[str, Any],
) -> tuple[bytes, dict[str, int | float]]:
    width, height = output_dimensions(str(config["aspect_ratio"]), str(config["resolution"]))
    left = round(width * float(config["frame_x"]) / 2) * 2
    top = round(height * float(config["frame_y"]) / 2) * 2
    frame_width = round(width * float(config["frame_width"]) / 2) * 2
    frame_height = round(height * float(config["frame_height"]) / 2) * 2
    if min(frame_width, frame_height) < 32:
        raise ValueError("Frame Apply requires a frame of at least 32 pixels")
    if left < 0 or top < 0 or left + frame_width > width or top + frame_height > height:
        raise ValueError("Frame Apply frame must stay inside the output Canvas")

    duration = float(motion["duration_seconds"])
    fps = int(motion["fps"])
    frames = max(1, round(duration * fps))
    start = dict(motion["start"])
    end = dict(motion["end"])
    filter_graph = _motion_filter(
        motion="custom",
        amount=0,
        frames=frames,
        width=frame_width,
        height=frame_height,
        fps=fps,
        media_fit=str(config["media_fit"]),
        motion_start_scale=float(start["scale"]),
        motion_end_scale=float(end["scale"]),
        motion_start_x=float(start["x"]),
        motion_start_y=float(start["y"]),
        motion_end_x=float(end["x"]),
        motion_end_y=float(end["y"]),
        background_color=str(config["background_color"]),
        still_image=True,
    )
    background = str(config["background_color"]).removeprefix("#")
    filter_graph += f",pad={width}:{height}:{left}:{top}:color=0x{background}"

    with tempfile.TemporaryDirectory(prefix="frameflow-frame-apply-") as temp_dir:
        directory = Path(temp_dir)
        source = directory / f"source{_image_suffix(content_type)}"
        output = directory / "framed-motion.mp4"
        source.write_bytes(image)
        _run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-loop", "1", "-i", str(source),
            "-vf", filter_graph, "-frames:v", str(frames), "-an",
            "-c:v", "libx264", "-profile:v", "high", "-preset", "veryfast", "-crf", "18",
            "-pix_fmt", "yuv420p", "-video_track_timescale", str(fps * 1000), "-movflags", "+faststart", str(output),
        ], timeout=max(180, math.ceil(duration * 12)))
        return output.read_bytes(), {
            "width": width,
            "height": height,
            "fps": fps,
            "duration_ms": round(duration * 1000),
            "frame_count": frames,
        }


def compose_video(
    video: ArtifactData,
    subtitle: ArtifactData,
    audio: ArtifactData,
    layout: dict[str, Any],
) -> tuple[bytes, dict[str, int | float]]:
    with tempfile.TemporaryDirectory(prefix="frameflow-video-compose-") as temp_dir:
        directory = Path(temp_dir)
        video_path = _write_artifact(directory, video, 0)
        audio_path = _write_artifact(directory, audio, 1)
        metadata = _probe(video_path)
        stream = _video_stream(metadata)
        width = int(stream.get("width") or 1080)
        height = int(stream.get("height") or 1920)
        duration = _duration_seconds(metadata)
        style = dict(layout["style"])
        frame = dict(layout["frame"])
        caption_left = round(width * float(frame["x"]) / 2) * 2
        caption_top = round(height * float(frame["y"]) / 2) * 2
        caption_right = caption_left + round(width * float(frame["width"]) / 2) * 2
        caption_bottom = caption_top + round(height * float(frame["height"]) / 2) * 2
        if caption_left < 0 or caption_top < 0 or caption_right > width or caption_bottom > height:
            raise ValueError("Video Compose Caption Layout must stay inside the Video Canvas")
        ass_content = _subtitle_ass(
            parse_srt_cues(subtitle.data),
            width=width,
            height=height,
            caption_left=caption_left,
            caption_top=caption_top,
            caption_right=caption_right,
            caption_bottom=caption_bottom,
            align=str(style["align"]),
            font_size=int(style["font_size"]),
            font_family=str(style["font_family"]),
            color=str(style["color"]),
            outline_color=str(style["outline_color"]),
        )
        subtitle_path = directory / "captions.ass"
        subtitle_path.write_text(ass_content, encoding="utf-8")
        output = directory / "composed.mp4"
        _run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(video_path), "-i", str(audio_path),
            "-filter_complex", "[1:a]apad[a]", "-map", "0:v:0", "-map", "[a]",
            "-vf", f"ass={subtitle_path.as_posix()}", "-t", f"{duration:.6f}",
            "-c:v", "libx264", "-profile:v", "high", "-preset", "veryfast", "-crf", "18",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
            "-movflags", "+faststart", str(output),
        ], timeout=max(180, math.ceil(duration * 12)))
        return output.read_bytes(), {
            "width": width,
            "height": height,
            "duration_ms": round(duration * 1000),
        }


class ImageMotionExecutor:
    def execute(
        self,
        context: NodeExecutionContext,
        resolved_node_config: dict[str, Any],
        typed_inputs: list[dict[str, Any]],
    ) -> NodeExecutionResult:
        if context.definition.execution.revision != IMAGE_MOTION_REVISION:
            raise RuntimeError("Image Motion executor revision does not match its Node Definition")
        artifacts = _read_artifacts(context.db, typed_inputs)
        images = _of_type(artifacts, "Image")
        if not images:
            raise ValueError("Image Motion requires one connected Image Artifact")
        image = images[0]
        config = resolved_node_config
        plan = {
            "schema_version": IMAGE_MOTION_SCHEMA,
            "source": {
                "artifact_id": image.record.id,
                "sha256": image.record.sha256,
                "content_type": image.content_type,
            },
            "duration_seconds": float(config["duration_seconds"]),
            "fps": int(config["fps"]),
            "easing": str(config["easing"]),
            "start": {
                "scale": float(config["start_scale"]),
                "x": float(config["start_x"]),
                "y": float(config["start_y"]),
            },
            "end": {
                "scale": float(config["end_scale"]),
                "x": float(config["end_x"]),
                "y": float(config["end_y"]),
            },
        }
        content = json.dumps(plan, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        input_ids, input_roles = input_lineage(context, typed_inputs)
        artifact = create_artifact(
            context.db,
            context.definition.artifact_contract.primary_type,
            schema_id=IMAGE_MOTION_SCHEMA,
            input_artifact_ids=input_ids,
            input_artifact_roles=input_roles,
            metadata={
                "experiment_id": context.experiment_id,
                "request_hash": context.request_hash,
                "execution_mode": IMAGE_MOTION_REVISION,
                "immutable": True,
                "source": "image_motion",
                "normalized_config": config,
                "source_image_sha256": image.record.sha256,
                "output_role": context.definition.artifact_contract.output_role,
            },
            content=content,
            content_type="application/json",
            filename="image-motion.json",
        )
        context.db.flush()
        return _result(
            context,
            artifact,
            output={"kind": "json", "title": "Image motion plan", "text": json.dumps(plan, ensure_ascii=False, indent=2)},
            input_ids=input_ids,
            input_roles=input_roles,
            revision=IMAGE_MOTION_REVISION,
        )


class MediaFrameLayoutExecutor:
    def execute(
        self,
        context: NodeExecutionContext,
        resolved_node_config: dict[str, Any],
        typed_inputs: list[dict[str, Any]],
    ) -> NodeExecutionResult:
        if context.definition.execution.revision != MEDIA_FRAME_REVISION:
            raise RuntimeError("Media Frame executor revision does not match its Node Definition")
        if typed_inputs:
            raise ValueError("Media Frame does not accept input Artifacts")
        config = resolved_node_config
        frame = {
            "x": float(config["frame_x"]),
            "y": float(config["frame_y"]),
            "width": float(config["frame_width"]),
            "height": float(config["frame_height"]),
            "media_fit": str(config["media_fit"]),
        }
        if frame["x"] + frame["width"] > 1 or frame["y"] + frame["height"] > 1:
            raise ValueError("Media Frame must stay inside the output Canvas")
        layout = {
            "schema_version": MEDIA_FRAME_SCHEMA,
            "canvas": {
                "aspect_ratio": str(config["aspect_ratio"]),
                "resolution": str(config["resolution"]),
                "background_color": str(config["background_color"]),
            },
            "frame": frame,
        }
        content = json.dumps(layout, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        artifact = create_artifact(
            context.db,
            context.definition.artifact_contract.primary_type,
            schema_id=MEDIA_FRAME_SCHEMA,
            input_artifact_ids=[],
            input_artifact_roles={},
            metadata={
                "experiment_id": context.experiment_id,
                "request_hash": context.request_hash,
                "execution_mode": MEDIA_FRAME_REVISION,
                "immutable": True,
                "source": "media_frame_layout",
                "normalized_config": config,
                "output_role": context.definition.artifact_contract.output_role,
            },
            content=content,
            content_type="application/json",
            filename="media-frame.json",
        )
        context.db.flush()
        return _result(
            context,
            artifact,
            output={
                "kind": "json",
                "title": f"Shared media frame · {round(frame['width'] * 100)} × {round(frame['height'] * 100)}%",
                "text": json.dumps(layout, ensure_ascii=False, indent=2),
            },
            input_ids=[],
            input_roles={},
            revision=MEDIA_FRAME_REVISION,
        )


def _frame_render_config(layout: dict[str, Any]) -> dict[str, Any]:
    canvas = dict(layout.get("canvas") or {})
    frame = dict(layout.get("frame") or {})
    return {
        "aspect_ratio": str(canvas.get("aspect_ratio") or ""),
        "resolution": str(canvas.get("resolution") or ""),
        "background_color": str(canvas.get("background_color") or ""),
        "frame_x": float(frame.get("x")),
        "frame_y": float(frame.get("y")),
        "frame_width": float(frame.get("width")),
        "frame_height": float(frame.get("height")),
        "media_fit": str(frame.get("media_fit") or ""),
    }


class VideoFrameApplyExecutor:
    def execute(
        self,
        context: NodeExecutionContext,
        resolved_node_config: dict[str, Any],
        typed_inputs: list[dict[str, Any]],
    ) -> NodeExecutionResult:
        revision = context.definition.execution.revision
        if revision not in {FRAME_APPLY_REVISION, FRAME_APPLY_V2_REVISION}:
            raise RuntimeError("Frame Apply executor revision does not match its Node Definition")
        artifacts = _read_artifacts(context.db, typed_inputs)
        plans = _of_type(artifacts, "MediaMotion")
        if not plans:
            raise ValueError("Frame Apply requires one connected MediaMotion Artifact")
        plan_artifact = plans[0]
        plan = _json_artifact(plan_artifact, schema=IMAGE_MOTION_SCHEMA, label="Frame Apply")
        frame_artifact = None
        frame_layout = None
        render_config = resolved_node_config
        output_schema = FRAME_APPLY_SCHEMA
        if revision == FRAME_APPLY_V2_REVISION:
            frames = _of_type(artifacts, "MediaFrame")
            if not frames:
                raise ValueError("Frame Apply v2 requires one connected MediaFrame Artifact")
            frame_artifact = frames[0]
            frame_layout = _json_artifact(frame_artifact, schema=MEDIA_FRAME_SCHEMA, label="Frame Apply")
            render_config = _frame_render_config(frame_layout)
            output_schema = FRAME_APPLY_V2_SCHEMA
        source, image, content_type = _source_image(context, dict(plan["source"]))
        rendered, media = render_framed_motion(image, content_type, plan, render_config)
        input_ids = [plan_artifact.record.id, source.id]
        input_roles = {plan_artifact.record.id: "motion_plan", source.id: "source_image"}
        if frame_artifact is not None:
            input_ids.insert(1, frame_artifact.record.id)
            input_roles[frame_artifact.record.id] = "media_frame"
        artifact = create_artifact(
            context.db,
            context.definition.artifact_contract.primary_type,
            schema_id=output_schema,
            input_artifact_ids=input_ids,
            input_artifact_roles=input_roles,
            metadata={
                "experiment_id": context.experiment_id,
                "request_hash": context.request_hash,
                "execution_mode": revision,
                "immutable": True,
                "source": "video_frame_apply",
                "normalized_config": resolved_node_config,
                "motion_plan": plan,
                **({"media_frame": frame_layout} if frame_layout is not None else {}),
                **media,
                "output_role": context.definition.artifact_contract.output_role,
            },
            content=rendered,
            content_type="video/mp4",
            filename="framed-motion.mp4",
        )
        context.db.flush()
        return _result(
            context,
            artifact,
            output={"kind": "video", "title": "Framed motion clip", "mimeType": "video/mp4"},
            input_ids=input_ids,
            input_roles=input_roles,
            revision=revision,
        )


class VideoConcatenateExecutor:
    def execute(
        self,
        context: NodeExecutionContext,
        resolved_node_config: dict[str, Any],
        typed_inputs: list[dict[str, Any]],
    ) -> NodeExecutionResult:
        if context.definition.execution.revision != VIDEO_CONCATENATE_REVISION:
            raise RuntimeError("Video Concatenate executor revision does not match its Node Definition")
        artifacts = _read_artifacts(context.db, typed_inputs)
        videos = _of_type(artifacts, *VIDEO_TYPES)
        if not videos:
            raise ValueError("Video Concatenate requires at least one connected Video Artifact")
        content = _edit_videos(videos, {"resolution": "source", "aspect_ratio": "source", "transition": "hard_cut"})
        input_ids, input_roles = input_lineage(context, typed_inputs)
        artifact = create_artifact(
            context.db,
            context.definition.artifact_contract.primary_type,
            schema_id=VIDEO_CONCATENATE_SCHEMA,
            input_artifact_ids=input_ids,
            input_artifact_roles=input_roles,
            metadata={
                "experiment_id": context.experiment_id,
                "request_hash": context.request_hash,
                "execution_mode": VIDEO_CONCATENATE_REVISION,
                "immutable": True,
                "source": "video_concatenate",
                "clip_count": len(videos),
                "normalized_config": resolved_node_config,
                "output_role": context.definition.artifact_contract.output_role,
            },
            content=content,
            content_type="video/mp4",
            filename="concatenated.mp4",
        )
        context.db.flush()
        return _result(
            context,
            artifact,
            output={"kind": "video", "title": f"Connected video · {len(videos)} clips", "mimeType": "video/mp4"},
            input_ids=input_ids,
            input_roles=input_roles,
            revision=VIDEO_CONCATENATE_REVISION,
        )


class SubtitleLayoutExecutor:
    def execute(
        self,
        context: NodeExecutionContext,
        resolved_node_config: dict[str, Any],
        typed_inputs: list[dict[str, Any]],
    ) -> NodeExecutionResult:
        if context.definition.execution.revision != SUBTITLE_LAYOUT_REVISION:
            raise RuntimeError("Subtitle Layout executor revision does not match its Node Definition")
        artifacts = _read_artifacts(context.db, typed_inputs)
        subtitles = _of_type(artifacts, "Subtitle")
        if not subtitles:
            raise ValueError("Subtitle Layout requires one connected Subtitle Artifact")
        subtitle = subtitles[0]
        cues = parse_srt_cues(subtitle.data)
        config = resolved_node_config
        layout = {
            "schema_version": SUBTITLE_LAYOUT_SCHEMA,
            "subtitle": {"artifact_id": subtitle.record.id, "sha256": subtitle.record.sha256},
            "canvas_aspect_ratio": str(config["aspect_ratio"]),
            "frame": {
                "x": float(config["frame_x"]),
                "y": float(config["frame_y"]),
                "width": float(config["frame_width"]),
                "height": float(config["frame_height"]),
            },
            "style": {
                "align": str(config["align"]),
                "font_family": str(config["font_family"]),
                "font_size": int(config["font_size"]),
                "color": str(config["color"]),
                "outline_color": str(config["outline_color"]),
            },
            "cue_count": len(cues),
        }
        frame = layout["frame"]
        if float(frame["x"]) + float(frame["width"]) > 1 or float(frame["y"]) + float(frame["height"]) > 1:
            raise ValueError("Subtitle Layout frame must stay inside the output Canvas")
        content = json.dumps(layout, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        input_ids, input_roles = input_lineage(context, typed_inputs)
        artifact = create_artifact(
            context.db,
            context.definition.artifact_contract.primary_type,
            schema_id=SUBTITLE_LAYOUT_SCHEMA,
            input_artifact_ids=input_ids,
            input_artifact_roles=input_roles,
            metadata={
                "experiment_id": context.experiment_id,
                "request_hash": context.request_hash,
                "execution_mode": SUBTITLE_LAYOUT_REVISION,
                "immutable": True,
                "source": "subtitle_layout",
                "normalized_config": config,
                "output_role": context.definition.artifact_contract.output_role,
            },
            content=content,
            content_type="application/json",
            filename="subtitle-layout.json",
        )
        context.db.flush()
        return _result(
            context,
            artifact,
            output={"kind": "json", "title": f"Subtitle region · {len(cues)} cues", "text": json.dumps(layout, ensure_ascii=False, indent=2)},
            input_ids=input_ids,
            input_roles=input_roles,
            revision=SUBTITLE_LAYOUT_REVISION,
        )


class VideoComposeExecutor:
    def execute(
        self,
        context: NodeExecutionContext,
        resolved_node_config: dict[str, Any],
        typed_inputs: list[dict[str, Any]],
    ) -> NodeExecutionResult:
        if context.definition.execution.revision != VIDEO_COMPOSE_REVISION:
            raise RuntimeError("Video Compose executor revision does not match its Node Definition")
        artifacts = _read_artifacts(context.db, typed_inputs)
        videos = _of_type(artifacts, *VIDEO_TYPES)
        layouts = _of_type(artifacts, "CaptionLayout")
        audios = _of_type(artifacts, "Audio")
        if not videos or not layouts or not audios:
            raise ValueError("Video Compose requires Video, CaptionLayout and Audio Artifacts")
        video, layout_artifact, audio = videos[0], layouts[0], audios[0]
        layout = _json_artifact(layout_artifact, schema=SUBTITLE_LAYOUT_SCHEMA, label="Video Compose")
        subtitle_ref = dict(layout["subtitle"])
        subtitle = context.db.get(ArtifactRecord, str(subtitle_ref.get("artifact_id") or ""))
        if not subtitle or subtitle.type != "Subtitle" or subtitle.sha256 != subtitle_ref.get("sha256"):
            raise ValueError("Video Compose Subtitle snapshot is unavailable or changed")
        bucket, key = storage_location(subtitle.uri, subtitle.metadata_json)
        subtitle_content_type = str((subtitle.metadata_json.get("storage") or {}).get("content_type") or "application/x-subrip")
        subtitle_data = ArtifactData(subtitle, get_storage().get_bytes(bucket=bucket, key=key), subtitle_content_type)
        content, media = compose_video(video, subtitle_data, audio, layout)
        input_ids = [video.record.id, layout_artifact.record.id, audio.record.id, subtitle.id]
        input_roles = {
            video.record.id: "video",
            layout_artifact.record.id: "caption_layout",
            audio.record.id: "narration_audio",
            subtitle.id: "subtitle_snapshot",
        }
        artifact = create_artifact(
            context.db,
            context.definition.artifact_contract.primary_type,
            schema_id=VIDEO_COMPOSE_SCHEMA,
            input_artifact_ids=input_ids,
            input_artifact_roles=input_roles,
            metadata={
                "experiment_id": context.experiment_id,
                "request_hash": context.request_hash,
                "execution_mode": VIDEO_COMPOSE_REVISION,
                "immutable": True,
                "source": "video_compose",
                "normalized_config": resolved_node_config,
                "caption_layout": layout,
                **media,
                "output_role": context.definition.artifact_contract.output_role,
            },
            content=content,
            content_type="video/mp4",
            filename="composed-final.mp4",
        )
        context.db.flush()
        return _result(
            context,
            artifact,
            output={"kind": "video", "title": "Composed video", "mimeType": "video/mp4"},
            input_ids=input_ids,
            input_roles=input_roles,
            revision=VIDEO_COMPOSE_REVISION,
        )
