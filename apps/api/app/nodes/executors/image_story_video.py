from __future__ import annotations

from typing import Any

from ...database import ArtifactRecord
from ...image_story_video import (
    IMAGE_STORY_VIDEO_REVISION,
    IMAGE_STORY_VIDEO_SCHEMA,
    StoryMedia,
    render_image_story,
)
from ...service import create_artifact
from ...storage import artifact_content_url, get_storage, storage_location
from ..contracts import NodeExecutionContext, NodeExecutionResult


class ImageStoryVideoExecutor:
    def execute(
        self,
        context: NodeExecutionContext,
        resolved_node_config: dict[str, Any],
        typed_inputs: list[dict[str, Any]],
    ) -> NodeExecutionResult:
        if context.definition.execution.revision != IMAGE_STORY_VIDEO_REVISION:
            raise RuntimeError("Image Story Video executor revision does not match its Node Definition")
        images, subtitle, audio, artifact_ids, roles = self._resolve_inputs(context, typed_inputs)
        storage = get_storage()

        def read(artifact: ArtifactRecord) -> StoryMedia:
            bucket, key = storage_location(artifact.uri, artifact.metadata_json)
            content_type = str(
                (artifact.metadata_json.get("storage") or {}).get("content_type")
                or "application/octet-stream"
            )
            return StoryMedia(storage.get_bytes(bucket=bucket, key=key), content_type)

        rendered = render_image_story(
            [read(image) for image in images],
            read(subtitle).data,
            audio=read(audio) if audio else None,
            **resolved_node_config,
        )
        artifact = create_artifact(
            context.db,
            context.definition.artifact_contract.primary_type,
            schema_id=context.definition.artifact_contract.schema_id,
            input_artifact_ids=artifact_ids,
            input_artifact_roles=roles,
            metadata={
                "experiment_id": context.experiment_id,
                "request_hash": context.request_hash,
                "execution_mode": IMAGE_STORY_VIDEO_REVISION,
                "immutable": True,
                "source": "image_story_video",
                "provider": "local",
                "model_alias": context.definition.execution.model_alias,
                "renderer_revision": IMAGE_STORY_VIDEO_REVISION,
                "width": rendered.width,
                "height": rendered.height,
                "fps": rendered.fps,
                "duration_ms": rendered.duration_ms,
                "scene_count": rendered.scene_count,
                "cue_count": rendered.cue_count,
                "has_audio": rendered.has_audio,
                "normalized_config": resolved_node_config,
                "output_role": context.definition.artifact_contract.output_role,
            },
            content=rendered.data,
            content_type="video/mp4",
            filename="image-story.mp4",
        )
        context.db.flush()
        return NodeExecutionResult(
            output={
                "kind": "video",
                "title": f"Image story · {rendered.scene_count} scenes",
                "mimeType": "video/mp4",
                "url": artifact_content_url(artifact.id),
            },
            output_artifact_ids=[artifact.id],
            provider_request_id=f"local_{context.request_hash[:20]}",
            cost_usd=0.0,
            metadata={
                "artifact_type": context.definition.artifact_contract.primary_type,
                "schema_id": IMAGE_STORY_VIDEO_SCHEMA,
                "input_artifact_ids": artifact_ids,
                "lineage_roles": roles,
                "retryable": False,
                "executor_revision": IMAGE_STORY_VIDEO_REVISION,
                "renderer_revision": IMAGE_STORY_VIDEO_REVISION,
            },
        )

    @staticmethod
    def _resolve_inputs(
        context: NodeExecutionContext,
        typed_inputs: list[dict[str, Any]],
    ) -> tuple[list[ArtifactRecord], ArtifactRecord, ArtifactRecord | None, list[str], dict[str, str]]:
        images: list[ArtifactRecord] = []
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
                    raise ValueError(f"Image Story Video input Artifact does not exist: {artifact_id}")
                if legacy_type == "Image" and artifact.type == "Image":
                    images.append(artifact)
                    role = "story_image"
                elif legacy_type == "Subtitle" and artifact.type == "Subtitle":
                    if subtitle is not None and subtitle.id != artifact.id:
                        raise ValueError("Image Story Video accepts one Timed Subtitle Artifact")
                    subtitle = artifact
                    role = "timed_caption"
                elif legacy_type == "Audio" and artifact.type == "Audio":
                    if audio is not None and audio.id != artifact.id:
                        raise ValueError("Image Story Video accepts one Narration Audio Artifact")
                    audio = artifact
                    role = "narration_audio"
                else:
                    continue
                if artifact.id not in artifact_ids:
                    artifact_ids.append(artifact.id)
                    roles[artifact.id] = role
        if not images:
            raise ValueError("Image Story Video requires connected Story Image Artifacts")
        if subtitle is None:
            raise ValueError("Image Story Video requires a connected Timed Subtitle Artifact")
        return images, subtitle, audio, artifact_ids, roles
