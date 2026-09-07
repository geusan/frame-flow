from __future__ import annotations

import json
from typing import Any

from ...media_workflow import (
    AUDIO_EXTRACT_REVISION,
    AUDIO_EXTRACT_SCHEMA,
    VIDEO_CLIP_LIST_SCHEMA,
    VIDEO_CLIP_SCHEMA,
    VIDEO_CLIP_SELECT_REVISION,
    VIDEO_SPLIT_REVISION,
    extract_audio_stream,
    split_video,
)
from ..contracts import NodeArtifactContent, NodeArtifactWrite, NodeExecutionContext, NodeExecutionResult


VIDEO_TYPES = {"Video", "FinalVideo", "ProxyVideo"}


def _artifact_ids(item: dict[str, Any]) -> list[str]:
    return list(dict.fromkeys([
        *(str(value) for value in item.get("artifact_ids") or []),
        *([str(item["artifact_id"])] if item.get("artifact_id") else []),
    ]))


def _resolve_artifact(
    context: NodeExecutionContext,
    typed_inputs: list[dict[str, Any]],
    *,
    input_type: str,
    artifact_types: set[str],
    label: str,
) -> NodeArtifactContent:
    artifact_store = context.require_artifact_store()
    for item in typed_inputs:
        if str(item.get("type") or "") != input_type:
            continue
        for artifact_id in _artifact_ids(item):
            artifact = artifact_store.read(artifact_id)
            if artifact.record.type in artifact_types:
                return artifact
    raise ValueError(f"{label} requires a connected {input_type} artifact")


class AudioExtractExecutor:
    def execute(
        self,
        context: NodeExecutionContext,
        resolved_node_config: dict[str, Any],
        typed_inputs: list[dict[str, Any]],
    ) -> NodeExecutionResult:
        if context.definition.execution.revision != AUDIO_EXTRACT_REVISION:
            raise RuntimeError("Audio Extract executor revision does not match its Node Definition")
        source = _resolve_artifact(
            context,
            typed_inputs,
            input_type="Video",
            artifact_types=VIDEO_TYPES,
            label="Audio Extract",
        )
        extracted = extract_audio_stream(source.data, source.content_type)
        artifact_store = context.require_artifact_store()
        source_id = source.record.id
        artifact = artifact_store.create(
            NodeArtifactWrite(
                artifact_type="Audio",
                schema_id=AUDIO_EXTRACT_SCHEMA,
                input_artifact_ids=[source_id],
                input_artifact_roles={source_id: "source_video"},
                metadata={
                    "experiment_id": context.experiment_id,
                    "request_hash": context.request_hash,
                    "execution_mode": AUDIO_EXTRACT_REVISION,
                    "immutable": True,
                    "source": "audio_stream_extract",
                    "codec": extracted.codec,
                    "duration_ms": extracted.duration_ms,
                    "sample_rate": extracted.sample_rate,
                    "channels": extracted.channels,
                    "stream_copy": True,
                    "normalized_config": resolved_node_config,
                },
                content=extracted.data,
                content_type=extracted.content_type,
                filename=extracted.filename,
            )
        )
        artifact_store.flush()
        return NodeExecutionResult(
            output={
                "kind": "audio",
                "title": "Extracted original audio",
                "mimeType": extracted.content_type,
                "url": artifact_store.content_url(artifact.id),
            },
            output_artifact_ids=[artifact.id],
            provider_request_id=f"local_{context.request_hash[:20]}",
            metadata={
                "artifact_type": "Audio",
                "schema_id": AUDIO_EXTRACT_SCHEMA,
                "input_artifact_ids": [source_id],
                "lineage_roles": {source_id: "source_video"},
                "retryable": False,
            },
        )


class VideoSplitExecutor:
    def execute(
        self,
        context: NodeExecutionContext,
        resolved_node_config: dict[str, Any],
        typed_inputs: list[dict[str, Any]],
    ) -> NodeExecutionResult:
        if context.definition.execution.revision != VIDEO_SPLIT_REVISION:
            raise RuntimeError("Video Split executor revision does not match its Node Definition")
        source = _resolve_artifact(
            context,
            typed_inputs,
            input_type="Video",
            artifact_types=VIDEO_TYPES,
            label="Video Split",
        )
        split = split_video(
            source.data,
            source.content_type,
            segment_duration_seconds=float(resolved_node_config["segment_duration_seconds"]),
            remainder_policy=str(resolved_node_config["remainder_policy"]),
            output_fps=int(resolved_node_config["output_fps"]),
            max_segments=int(resolved_node_config["max_segments"]),
        )
        artifact_store = context.require_artifact_store()
        source_id = source.record.id
        clip_artifacts = [
            artifact_store.create(
                NodeArtifactWrite(
                    artifact_type="Video",
                    schema_id=VIDEO_CLIP_SCHEMA,
                    input_artifact_ids=[source_id],
                    input_artifact_roles={source_id: "source_video"},
                    metadata={
                        "experiment_id": context.experiment_id,
                        "request_hash": context.request_hash,
                        "execution_mode": VIDEO_SPLIT_REVISION,
                        "immutable": True,
                        "source": "video_split",
                        "clip_index": clip.index,
                        "start_ms": clip.start_ms,
                        "duration_ms": clip.duration_ms,
                        "width": clip.width,
                        "height": clip.height,
                        "fps": clip.fps,
                        "normalized_config": resolved_node_config,
                    },
                    content=clip.data,
                    content_type="video/mp4",
                    filename=f"clip-{clip.index + 1:02d}.mp4",
                )
            )
            for clip in split.clips
        ]
        artifact_store.flush()
        manifest = {
            "schema_version": VIDEO_CLIP_LIST_SCHEMA,
            "source_artifact_id": source_id,
            "source_duration_ms": split.source_duration_ms,
            "clips": [
                {
                    "index": clip.index,
                    "artifact_id": artifact.id,
                    "start_ms": clip.start_ms,
                    "duration_ms": clip.duration_ms,
                }
                for clip, artifact in zip(split.clips, clip_artifacts, strict=True)
            ],
        }
        collection_inputs = [source_id, *(artifact.id for artifact in clip_artifacts)]
        collection_roles = {source_id: "source_video", **{artifact.id: "video_clip" for artifact in clip_artifacts}}
        collection = artifact_store.create(
            NodeArtifactWrite(
                artifact_type="VideoClipList",
                schema_id=VIDEO_CLIP_LIST_SCHEMA,
                input_artifact_ids=collection_inputs,
                input_artifact_roles=collection_roles,
                metadata={
                    "experiment_id": context.experiment_id,
                    "request_hash": context.request_hash,
                    "execution_mode": VIDEO_SPLIT_REVISION,
                    "immutable": True,
                    "source": "video_split",
                    "source_duration_ms": split.source_duration_ms,
                    "clip_count": len(clip_artifacts),
                    "clip_artifact_ids": [artifact.id for artifact in clip_artifacts],
                    "normalized_config": resolved_node_config,
                },
                content=json.dumps(manifest, ensure_ascii=False, separators=(",", ":")).encode(),
                content_type="application/json",
                filename="video-clips.json",
            )
        )
        artifact_store.flush()
        return NodeExecutionResult(
            output={
                "kind": "json",
                "title": f"{len(clip_artifacts)} video clips",
                "clipCount": len(clip_artifacts),
                "url": artifact_store.content_url(collection.id),
            },
            output_artifact_ids=[collection.id],
            provider_request_id=f"local_{context.request_hash[:20]}",
            metadata={
                "artifact_type": "VideoClipList",
                "schema_id": VIDEO_CLIP_LIST_SCHEMA,
                "input_artifact_ids": [source_id],
                "lineage_roles": {source_id: "source_video"},
                "retryable": False,
            },
        )


class VideoClipSelectExecutor:
    def execute(
        self,
        context: NodeExecutionContext,
        resolved_node_config: dict[str, Any],
        typed_inputs: list[dict[str, Any]],
    ) -> NodeExecutionResult:
        if context.definition.execution.revision != VIDEO_CLIP_SELECT_REVISION:
            raise RuntimeError("Video Clip Select executor revision does not match its Node Definition")
        collection = _resolve_artifact(
            context,
            typed_inputs,
            input_type="VideoClipList",
            artifact_types={"VideoClipList"},
            label="Video Clip Select",
        )
        try:
            manifest = json.loads(collection.data)
        except (TypeError, ValueError) as exc:
            raise ValueError("Video Clip Select requires a valid video.clip_list.v1 Artifact") from exc
        if manifest.get("schema_version") != VIDEO_CLIP_LIST_SCHEMA:
            raise ValueError("Video Clip Select requires a video.clip_list.v1 Artifact")
        clip_index = int(resolved_node_config["clip_index"])
        clip = next((item for item in manifest.get("clips") or [] if int(item.get("index", -1)) == clip_index), None)
        if not clip:
            available = len(manifest.get("clips") or [])
            raise ValueError(f"Video Clip Select index {clip_index} is outside the {available} available clips")
        artifact_store = context.require_artifact_store()
        artifact = artifact_store.read(str(clip.get("artifact_id") or ""))
        if artifact.record.type not in VIDEO_TYPES or artifact.record.schema_id != VIDEO_CLIP_SCHEMA:
            raise ValueError("Video Clip Select references an unavailable clip Artifact")
        artifact_id = artifact.record.id
        collection_id = collection.record.id
        return NodeExecutionResult(
            output={
                "kind": "video",
                "title": f"Video clip {clip_index + 1}",
                "mimeType": "video/mp4",
                "url": artifact_store.content_url(artifact_id),
            },
            output_artifact_ids=[artifact_id],
            provider_request_id=f"local_{context.request_hash[:20]}",
            metadata={
                "artifact_type": "Video",
                "schema_id": VIDEO_CLIP_SCHEMA,
                "input_artifact_ids": [collection_id, artifact_id],
                "lineage_roles": {collection_id: "clip_collection", artifact_id: "selected_clip"},
                "retryable": False,
            },
        )
