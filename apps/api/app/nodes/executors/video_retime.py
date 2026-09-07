from __future__ import annotations

from typing import Any

from ...video_retime import VIDEO_RETIME_REVISION, VIDEO_RETIME_SCHEMA, retime_video
from ..contracts import NodeArtifactContent, NodeArtifactWrite, NodeExecutionContext, NodeExecutionResult


class VideoRetimeExecutor:
    def execute(
        self,
        context: NodeExecutionContext,
        resolved_node_config: dict[str, Any],
        typed_inputs: list[dict[str, Any]],
    ) -> NodeExecutionResult:
        if context.definition.execution.revision != VIDEO_RETIME_REVISION:
            raise RuntimeError("Video Retime executor revision does not match its Node Definition")
        source_artifact = self._resolve_video(context, typed_inputs)
        rendered = retime_video(
            source_artifact.data, source_artifact.content_type,
            speed_multiplier=float(resolved_node_config["speed_multiplier"]),
            output_fps=int(resolved_node_config["output_fps"]),
            preserve_audio=bool(resolved_node_config["preserve_audio"]),
        )
        artifact_store = context.require_artifact_store()
        source_id = source_artifact.record.id
        artifact = artifact_store.create(
            NodeArtifactWrite(
                artifact_type="Video",
                schema_id=VIDEO_RETIME_SCHEMA,
                input_artifact_ids=[source_id],
                input_artifact_roles={source_id: "source_video"},
                metadata={
                    "experiment_id": context.experiment_id,
                    "request_hash": context.request_hash,
                    "execution_mode": VIDEO_RETIME_REVISION,
                    "immutable": True,
                    "source": "video_retime",
                    "source_duration_ms": rendered.source_duration_ms,
                    "duration_ms": rendered.duration_ms,
                    "fps": rendered.fps,
                    "width": rendered.width,
                    "height": rendered.height,
                    "has_audio": rendered.has_audio,
                    "normalized_config": resolved_node_config,
                },
                content=rendered.data,
                content_type="video/mp4",
                filename="retimed.mp4",
            )
        )
        artifact_store.flush()
        return NodeExecutionResult(
            output={
                "kind": "video", "title": f"Retimed video · {float(resolved_node_config['speed_multiplier']):g}×",
                "mimeType": "video/mp4", "url": artifact_store.content_url(artifact.id),
            },
            output_artifact_ids=[artifact.id],
            provider_request_id=f"local_{context.request_hash[:20]}",
            metadata={
                "artifact_type": "Video", "schema_id": VIDEO_RETIME_SCHEMA,
                "input_artifact_ids": [source_id],
                "lineage_roles": {source_id: "source_video"}, "retryable": False,
            },
        )

    @staticmethod
    def _resolve_video(context: NodeExecutionContext, typed_inputs: list[dict[str, Any]]) -> NodeArtifactContent:
        artifact_store = context.require_artifact_store()
        for item in typed_inputs:
            if str(item.get("type") or "") != "Video":
                continue
            artifact_ids = [*(item.get("artifact_ids") or []), *([item.get("artifact_id")] if item.get("artifact_id") else [])]
            for artifact_id in artifact_ids:
                artifact = artifact_store.read(str(artifact_id))
                if artifact.record.type in {"Video", "FinalVideo", "ProxyVideo"}:
                    return artifact
        raise ValueError("Video Retime requires a connected Video artifact")
