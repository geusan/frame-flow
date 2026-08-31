from __future__ import annotations

from typing import Any

from ...database import ArtifactRecord
from ...service import create_artifact
from ...storage import artifact_content_url, get_storage, storage_location
from ...video_retime import VIDEO_RETIME_REVISION, VIDEO_RETIME_SCHEMA, retime_video
from ..contracts import NodeExecutionContext, NodeExecutionResult


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
        bucket, key = storage_location(source_artifact.uri, source_artifact.metadata_json)
        storage = get_storage()
        content_type = str((source_artifact.metadata_json.get("storage") or {}).get("content_type") or "video/mp4")
        rendered = retime_video(
            storage.get_bytes(bucket=bucket, key=key), content_type,
            speed_multiplier=float(resolved_node_config["speed_multiplier"]),
            output_fps=int(resolved_node_config["output_fps"]),
            preserve_audio=bool(resolved_node_config["preserve_audio"]),
        )
        artifact = create_artifact(
            context.db,
            "Video",
            schema_id=VIDEO_RETIME_SCHEMA,
            input_artifact_ids=[source_artifact.id],
            input_artifact_roles={source_artifact.id: "source_video"},
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
        context.db.flush()
        return NodeExecutionResult(
            output={
                "kind": "video", "title": f"Retimed video · {float(resolved_node_config['speed_multiplier']):g}×",
                "mimeType": "video/mp4", "url": artifact_content_url(artifact.id),
            },
            output_artifact_ids=[artifact.id],
            provider_request_id=f"local_{context.request_hash[:20]}",
            metadata={
                "artifact_type": "Video", "schema_id": VIDEO_RETIME_SCHEMA,
                "input_artifact_ids": [source_artifact.id],
                "lineage_roles": {source_artifact.id: "source_video"}, "retryable": False,
            },
        )

    @staticmethod
    def _resolve_video(context: NodeExecutionContext, typed_inputs: list[dict[str, Any]]) -> ArtifactRecord:
        for item in typed_inputs:
            if str(item.get("type") or "") != "Video":
                continue
            artifact_ids = [*(item.get("artifact_ids") or []), *([item.get("artifact_id")] if item.get("artifact_id") else [])]
            for artifact_id in artifact_ids:
                artifact = context.db.get(ArtifactRecord, str(artifact_id))
                if artifact and artifact.type in {"Video", "FinalVideo", "ProxyVideo"}:
                    return artifact
        raise ValueError("Video Retime requires a connected Video artifact")
