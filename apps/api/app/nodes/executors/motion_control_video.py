from __future__ import annotations

from typing import Any

from ...motion_control_video import (
    MOTION_CONTROL_VIDEO_REVISION,
    MOTION_CONTROL_VIDEO_SCHEMA,
    parse_motion_track,
    render_motion_control_video,
)
from ..contracts import NodeArtifactContent, NodeArtifactWrite, NodeExecutionContext, NodeExecutionResult


class MotionControlVideoExecutor:
    def execute(
        self,
        context: NodeExecutionContext,
        resolved_node_config: dict[str, Any],
        typed_inputs: list[dict[str, Any]],
    ) -> NodeExecutionResult:
        if context.definition.execution.revision != MOTION_CONTROL_VIDEO_REVISION:
            raise RuntimeError("Motion Control Video executor revision does not match its Node Definition")
        motion_artifact = self._resolve_motion_track(context, typed_inputs)
        motion_track = parse_motion_track(motion_artifact.data)
        rendered = render_motion_control_video(
            motion_track,
            width=int(resolved_node_config["width"]),
            output_fps=int(resolved_node_config["output_fps"]),
            theme=str(resolved_node_config["theme"]),
            draw_pose=bool(resolved_node_config["draw_pose"]),
            draw_face=bool(resolved_node_config["draw_face"]),
            draw_hands=bool(resolved_node_config["draw_hands"]),
            line_width=int(resolved_node_config["line_width"]),
            point_radius=int(resolved_node_config["point_radius"]),
        )
        artifact_store = context.require_artifact_store()
        source_id = motion_artifact.record.id
        artifact = artifact_store.create(
            NodeArtifactWrite(
                artifact_type="Video",
                schema_id=MOTION_CONTROL_VIDEO_SCHEMA,
                input_artifact_ids=[source_id],
                input_artifact_roles={source_id: "motion_track"},
                metadata={
                    "experiment_id": context.experiment_id,
                    "request_hash": context.request_hash,
                    "execution_mode": MOTION_CONTROL_VIDEO_REVISION,
                    "immutable": True,
                    "source": "motion_track_control_renderer",
                    "duration_ms": rendered.duration_ms,
                    "frame_count": rendered.frame_count,
                    "fps": rendered.fps,
                    "width": rendered.width,
                    "height": rendered.height,
                    "has_audio": False,
                    "normalized_config": resolved_node_config,
                },
                content=rendered.data,
                content_type="video/mp4",
                filename="motion-control.mp4",
            )
        )
        artifact_store.flush()
        return NodeExecutionResult(
            output={
                "kind": "video",
                "title": "Motion control video",
                "mimeType": "video/mp4",
                "url": artifact_store.content_url(artifact.id),
                "frameCount": rendered.frame_count,
                "sampleFps": rendered.fps,
            },
            output_artifact_ids=[artifact.id],
            provider_request_id=f"local_{context.request_hash[:20]}",
            metadata={
                "artifact_type": "Video",
                "schema_id": MOTION_CONTROL_VIDEO_SCHEMA,
                "input_artifact_ids": [source_id],
                "lineage_roles": {source_id: "motion_track"},
                "retryable": False,
            },
        )

    @staticmethod
    def _resolve_motion_track(context: NodeExecutionContext, typed_inputs: list[dict[str, Any]]) -> NodeArtifactContent:
        artifact_store = context.require_artifact_store()
        for item in typed_inputs:
            if str(item.get("type") or "") != "MotionTrack":
                continue
            artifact_ids = [*(item.get("artifact_ids") or []), *([item.get("artifact_id")] if item.get("artifact_id") else [])]
            for artifact_id in artifact_ids:
                artifact = artifact_store.read(str(artifact_id))
                if artifact.record.type == "MotionTrack":
                    return artifact
        raise ValueError("Motion Control Video requires a connected MotionTrack artifact")
