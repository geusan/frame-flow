from __future__ import annotations

import json
from typing import Any

from ...database import ArtifactRecord
from ...motion_control_video import parse_motion_track
from ...motion_segmentation import MOTION_SEGMENT_REVISION, MOTION_SEGMENT_SCHEMA, segment_motion_track
from ...service import create_artifact
from ...storage import artifact_content_url, get_storage, storage_location
from ..contracts import NodeExecutionContext, NodeExecutionResult


class MotionSegmentExecutor:
    def execute(
        self,
        context: NodeExecutionContext,
        resolved_node_config: dict[str, Any],
        typed_inputs: list[dict[str, Any]],
    ) -> NodeExecutionResult:
        if context.definition.execution.revision != MOTION_SEGMENT_REVISION:
            raise RuntimeError("Motion Segment executor revision does not match its Node Definition")
        source_artifact = self._resolve_motion_track(context, typed_inputs)
        bucket, key = storage_location(source_artifact.uri, source_artifact.metadata_json)
        source_track = parse_motion_track(get_storage().get_bytes(bucket=bucket, key=key))
        segmented = segment_motion_track(
            source_track,
            start_seconds=float(resolved_node_config["start_seconds"]),
            duration_seconds=float(resolved_node_config["duration_seconds"]),
            time_scale=float(resolved_node_config["time_scale"]),
        )
        content = json.dumps(segmented, ensure_ascii=False, separators=(",", ":")).encode()
        summary = segmented["summary"]
        coverage = summary["coverage"]
        artifact = create_artifact(
            context.db,
            "MotionTrack",
            schema_id=MOTION_SEGMENT_SCHEMA,
            input_artifact_ids=[source_artifact.id],
            input_artifact_roles={source_artifact.id: "source_motion_track"},
            metadata={
                "experiment_id": context.experiment_id,
                "request_hash": context.request_hash,
                "execution_mode": MOTION_SEGMENT_REVISION,
                "immutable": True,
                "source": "motion_track_segment",
                "payload_schema": "motion.track.v1",
                "duration_ms": segmented["source"]["duration_ms"],
                "frame_count": summary["frame_count"],
                "sample_fps": segmented["source"]["sample_fps"],
                "coverage": coverage,
                "normalized_config": resolved_node_config,
            },
            content=content,
            content_type="application/json",
            filename="motion-segment.json",
        )
        context.db.flush()
        return NodeExecutionResult(
            output={
                "kind": "json",
                "title": f"Motion segment · {float(resolved_node_config['start_seconds']):g}s",
                "url": artifact_content_url(artifact.id),
                "frameCount": summary["frame_count"],
                "sampleFps": segmented["source"]["sample_fps"],
                "faceCoverage": coverage["face"],
                "poseCoverage": coverage["pose"],
                "leftHandCoverage": coverage["left_hand"],
                "rightHandCoverage": coverage["right_hand"],
            },
            output_artifact_ids=[artifact.id],
            provider_request_id=f"local_{context.request_hash[:20]}",
            metadata={
                "artifact_type": "MotionTrack", "schema_id": MOTION_SEGMENT_SCHEMA,
                "input_artifact_ids": [source_artifact.id],
                "lineage_roles": {source_artifact.id: "source_motion_track"}, "retryable": False,
            },
        )

    @staticmethod
    def _resolve_motion_track(context: NodeExecutionContext, typed_inputs: list[dict[str, Any]]) -> ArtifactRecord:
        for item in typed_inputs:
            if str(item.get("type") or "") != "MotionTrack":
                continue
            artifact_ids = [*(item.get("artifact_ids") or []), *([item.get("artifact_id")] if item.get("artifact_id") else [])]
            for artifact_id in artifact_ids:
                artifact = context.db.get(ArtifactRecord, str(artifact_id))
                if artifact and artifact.type == "MotionTrack":
                    return artifact
        raise ValueError("Motion Segment requires a connected MotionTrack artifact")
