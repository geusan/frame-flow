from __future__ import annotations

from typing import Any

from ...database import ArtifactRecord
from ...image_story_video import (
    MEDIA_STORY_VIDEO_REVISION,
    MEDIA_STORY_VIDEO_SCHEMA,
    StoryMedia,
    render_image_story,
    renderer_environment,
)
from ...service import create_artifact
from ...storage import artifact_content_url, get_storage, storage_location
from ..contracts import NodeExecutionContext, NodeExecutionResult


class MediaStoryVideoExecutor:
    @staticmethod
    def runtime_revision(_, resolved_node_config: dict[str, Any]) -> str:
        fingerprint = str(renderer_environment(str(resolved_node_config["caption_font_family"]))["fingerprint"])
        return f"{MEDIA_STORY_VIDEO_REVISION}+{fingerprint.removeprefix('sha256:')[:12]}"

    def execute(
        self,
        context: NodeExecutionContext,
        resolved_node_config: dict[str, Any],
        typed_inputs: list[dict[str, Any]],
    ) -> NodeExecutionResult:
        if context.definition.execution.revision != MEDIA_STORY_VIDEO_REVISION:
            raise RuntimeError("Media Story Video executor revision does not match its Node Definition")
        media, subtitle, audio, artifact_ids, roles = self._resolve_inputs(context, typed_inputs)
        storage = get_storage()

        def read(artifact: ArtifactRecord, *, kind: str) -> StoryMedia:
            bucket, key = storage_location(artifact.uri, artifact.metadata_json)
            content_type = str(
                (artifact.metadata_json.get("storage") or {}).get("content_type")
                or "application/octet-stream"
            )
            return StoryMedia(storage.get_bytes(bucket=bucket, key=key), content_type, kind)

        config = resolved_node_config
        sources = [read(artifact, kind=kind) for artifact, kind in media]
        rendered = render_image_story(
            sources,
            read(subtitle, kind="subtitle").data,
            audio=read(audio, kind="audio") if audio else None,
            aspect_ratio=str(config["aspect_ratio"]),
            resolution=str(config["resolution"]),
            fps=int(config["fps"]),
            scene_timing=str(config["scene_timing"]),
            motion_preset=str(config["motion_preset"]),
            motion_amount=float(config["motion_amount"]),
            image_region_height_ratio=float(config["frame_height"]),
            image_margin_ratio=0,
            background_color=str(config["background_color"]),
            caption_font_family=str(config["caption_font_family"]),
            caption_font_size=int(config["caption_font_size"]),
            caption_color=str(config["caption_color"]),
            caption_outline_color=str(config["caption_outline_color"]),
            caption_align=str(config["caption_align"]),
            frame_x=float(config["frame_x"]),
            frame_y=float(config["frame_y"]),
            frame_width=float(config["frame_width"]),
            frame_height=float(config["frame_height"]),
            media_fit=str(config["media_fit"]),
            crop_focus_x=float(config["crop_focus_x"]),
            crop_focus_y=float(config["crop_focus_y"]),
            motion_start_scale=float(config["motion_start_scale"]),
            motion_end_scale=float(config["motion_end_scale"]),
            motion_start_x=float(config["motion_start_x"]),
            motion_start_y=float(config["motion_start_y"]),
            motion_end_x=float(config["motion_end_x"]),
            motion_end_y=float(config["motion_end_y"]),
            caption_frame_x=float(config["caption_frame_x"]),
            caption_frame_y=float(config["caption_frame_y"]),
            caption_frame_width=float(config["caption_frame_width"]),
            caption_frame_height=float(config["caption_frame_height"]),
        )
        runtime_revision = self.runtime_revision(context.definition, config)
        resolved_motion_plan = [
            {**item, "artifact_id": media[int(item["scene_index"])][0].id}
            for item in rendered.motion_plan
        ]
        artifact = create_artifact(
            context.db,
            context.definition.artifact_contract.primary_type,
            schema_id=context.definition.artifact_contract.schema_id,
            input_artifact_ids=artifact_ids,
            input_artifact_roles=roles,
            metadata={
                "experiment_id": context.experiment_id,
                "request_hash": context.request_hash,
                "execution_mode": runtime_revision,
                "immutable": True,
                "source": "media_story_video",
                "provider": "local",
                "model_alias": context.definition.execution.model_alias,
                "renderer_revision": runtime_revision,
                "renderer_environment": rendered.renderer_environment,
                "width": rendered.width,
                "height": rendered.height,
                "fps": rendered.fps,
                "duration_ms": rendered.duration_ms,
                "scene_count": rendered.scene_count,
                "cue_count": rendered.cue_count,
                "has_audio": rendered.has_audio,
                "media_kinds": [kind for _, kind in media],
                "resolved_motion_plan": resolved_motion_plan,
                "normalized_config": config,
                "output_role": context.definition.artifact_contract.output_role,
            },
            content=rendered.data,
            content_type="video/mp4",
            filename="media-story.mp4",
        )
        context.db.flush()
        return NodeExecutionResult(
            output={
                "kind": "video",
                "title": f"Media story · {rendered.scene_count} scenes",
                "mimeType": "video/mp4",
                "url": artifact_content_url(artifact.id),
            },
            output_artifact_ids=[artifact.id],
            provider_request_id=f"local_{context.request_hash[:20]}",
            cost_usd=0.0,
            metadata={
                "artifact_type": context.definition.artifact_contract.primary_type,
                "schema_id": MEDIA_STORY_VIDEO_SCHEMA,
                "input_artifact_ids": artifact_ids,
                "lineage_roles": roles,
                "retryable": False,
                "executor_revision": runtime_revision,
                "renderer_revision": runtime_revision,
                "renderer_fingerprint": rendered.renderer_environment.get("fingerprint"),
                "resolved_motion_plan": resolved_motion_plan,
            },
        )

    @staticmethod
    def _resolve_inputs(
        context: NodeExecutionContext,
        typed_inputs: list[dict[str, Any]],
    ) -> tuple[
        list[tuple[ArtifactRecord, str]],
        ArtifactRecord,
        ArtifactRecord | None,
        list[str],
        dict[str, str],
    ]:
        media: list[tuple[ArtifactRecord, str]] = []
        subtitle: ArtifactRecord | None = None
        audio: ArtifactRecord | None = None
        artifact_ids: list[str] = []
        roles: dict[str, str] = {}
        for item in typed_inputs:
            legacy_type = str(item.get("type") or "")
            values = [
                *(str(value) for value in item.get("artifact_ids") or []),
                *([str(item["artifact_id"])] if item.get("artifact_id") else []),
            ]
            for artifact_id in values:
                artifact = context.db.get(ArtifactRecord, artifact_id)
                if not artifact:
                    raise ValueError(f"Media Story Video input Artifact does not exist: {artifact_id}")
                if legacy_type == "Image" and artifact.type == "Image":
                    media.append((artifact, "image"))
                    role = "story_image"
                elif legacy_type == "Video" and artifact.type in {"Video", "FinalVideo", "ProxyVideo"}:
                    media.append((artifact, "video"))
                    role = "story_video"
                elif legacy_type == "Subtitle" and artifact.type == "Subtitle":
                    if subtitle is not None and subtitle.id != artifact.id:
                        raise ValueError("Media Story Video accepts one Timed Subtitle Artifact")
                    subtitle = artifact
                    role = "timed_caption"
                elif legacy_type == "Audio" and artifact.type == "Audio":
                    if audio is not None and audio.id != artifact.id:
                        raise ValueError("Media Story Video accepts one Narration Audio Artifact")
                    audio = artifact
                    role = "narration_audio"
                else:
                    continue
                if artifact.id not in artifact_ids:
                    artifact_ids.append(artifact.id)
                    roles[artifact.id] = role
        if not media:
            raise ValueError("Media Story Video requires at least one connected Image or Video Artifact")
        if subtitle is None:
            raise ValueError("Media Story Video requires a connected Timed Subtitle Artifact")
        return media, subtitle, audio, artifact_ids, roles
