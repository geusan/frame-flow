from __future__ import annotations

from typing import Any

from ...canvas_operations import _edit_videos, _read_artifacts, _render_timeline, _replace_audio, _require
from ...service import create_artifact
from ...storage import artifact_content_url
from ..contracts import NodeExecutionContext, NodeExecutionResult
from .text_support import input_lineage


class FFmpegMediaCapabilityExecutor:
    def supports(self, context: NodeExecutionContext) -> bool:
        input_types = {port.type for port in context.definition.ports.inputs}
        return (
            context.definition.execution.kind == "local"
            and context.definition.execution.model_alias == "local.ffmpeg"
            and context.definition.artifact_contract.primary_type in {"Video", "FinalVideo"}
            and (
                "data.timeline.v1" in input_types
                or "data.timeline.v2" in input_types
                or {"media.video.v1", "media.audio.v1"} <= input_types
                or any(port.type == "media.video.v1" and port.multiple for port in context.definition.ports.inputs)
            )
        )

    def execute(
        self,
        context: NodeExecutionContext,
        resolved_node_config: dict[str, Any],
        typed_inputs: list[dict[str, Any]],
    ) -> NodeExecutionResult:
        if not self.supports(context):
            raise RuntimeError("FFmpeg media capability does not support this execution context")
        artifacts = _read_artifacts(context.db, typed_inputs)
        input_artifact_ids, input_roles = input_lineage(context, typed_inputs)
        input_types = {port.type for port in context.definition.ports.inputs}
        if input_types & {"data.timeline.v1", "data.timeline.v2"}:
            timeline = _require(artifacts, "Timeline", "Timeline")
            content = _render_timeline(context.db, timeline)
            title = "Rendered final MP4"
            filename = "final.mp4"
        elif {"media.video.v1", "media.audio.v1"} <= input_types:
            video = _require(artifacts, "Video", "Video", "FinalVideo")
            audio = _require(artifacts, "Audio", "Audio")
            content = _replace_audio(video, audio)
            title = "Video with replaced audio"
            filename = "localized.mp4"
        else:
            content = _edit_videos(artifacts, resolved_node_config)
            title = "Edited video"
            filename = "edited.mp4"
        artifact = create_artifact(
            context.db,
            context.definition.artifact_contract.primary_type,
            schema_id=context.definition.artifact_contract.schema_id,
            input_artifact_ids=input_artifact_ids,
            input_artifact_roles=input_roles,
            metadata={
                "experiment_id": context.experiment_id,
                "request_hash": context.request_hash,
                "execution_mode": context.definition.execution.revision,
                "immutable": True,
                "source": "node_executor_registry",
                "provider": "local",
                "model_alias": context.definition.execution.model_alias,
                "normalized_config": resolved_node_config,
                "output_role": context.definition.artifact_contract.output_role,
            },
            content=content,
            content_type="video/mp4",
            filename=filename,
        )
        context.db.flush()
        return NodeExecutionResult(
            output={"kind": "video", "title": title, "mimeType": "video/mp4", "url": artifact_content_url(artifact.id)},
            output_artifact_ids=[artifact.id],
            provider_request_id=f"local_{context.request_hash[:20]}",
            cost_usd=0.0,
            metadata={
                "artifact_type": context.definition.artifact_contract.primary_type,
                "schema_id": context.definition.artifact_contract.schema_id,
                "input_artifact_ids": input_artifact_ids,
                "lineage_roles": input_roles,
                "retryable": False,
                "executor_revision": context.definition.execution.revision,
            },
        )
