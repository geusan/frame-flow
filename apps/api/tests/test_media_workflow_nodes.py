from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.media_workflow import (
    AUDIO_EXTRACT_REVISION,
    ExtractedAudio,
    SplitVideo,
    SplitVideoClip,
    VIDEO_CLIP_LIST_SCHEMA,
    VIDEO_CLIP_SCHEMA,
    VIDEO_CLIP_SELECT_REVISION,
    VIDEO_SPLIT_REVISION,
    extract_audio_stream,
    split_video,
)
from app.domain import ExperimentRunRequest
from app.nodes import node_registry
from app.nodes.contracts import NodeExecutionContext
from app.nodes.executors import media_workflow as executor_module
from app.nodes.executors.media_workflow import AudioExtractExecutor, VideoClipSelectExecutor, VideoSplitExecutor


def _fixture_video(path: Path, *, duration_seconds: float = 1.1) -> bytes:
    try:
        subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "color=c=#382f65:s=90x160:r=24",
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
                "-t", str(duration_seconds), "-map", "0:v:0", "-map", "1:a:0",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
                "-movflags", "+faststart", str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=90,
        )
    except FileNotFoundError:
        pytest.skip("ffmpeg is not installed")
    return path.read_bytes()


def test_media_workflow_manifests_are_registered_with_versioned_ports():
    audio = node_registry.get("audio.extract", 1)
    split = node_registry.get("video.split", 1)
    select = node_registry.get("video.clip.select", 1)
    assert audio is not None and split is not None and select is not None

    assert audio.execution.revision == AUDIO_EXTRACT_REVISION
    assert audio.ports.inputs[0].type == "media.video.v1"
    assert audio.ports.outputs[0].type == "media.audio.v1"
    assert audio.artifact_contract.schema_id == "audio.extracted.v1"
    assert node_registry.resolve_config(audio, {}) == {}

    assert split.execution.revision == VIDEO_SPLIT_REVISION
    assert split.ports.outputs[0].type == "media.video_clip_list.v1"
    assert split.artifact_contract.schema_id == VIDEO_CLIP_LIST_SCHEMA
    assert node_registry.resolve_config(split, {}) == {
        "segment_duration_seconds": 8,
        "remainder_policy": "keep",
        "output_fps": 24,
        "max_segments": 16,
    }

    assert select.execution.revision == VIDEO_CLIP_SELECT_REVISION
    assert select.ports.inputs[0].type == "media.video_clip_list.v1"
    assert select.ports.outputs[0].type == "media.video.v1"
    assert select.artifact_contract.schema_id == VIDEO_CLIP_SCHEMA
    assert node_registry.resolve_config(select, {}) == {"clip_index": 0}


def test_audio_extract_stream_copies_the_original_aac_track(tmp_path):
    source = _fixture_video(tmp_path / "source.mp4")
    audio = extract_audio_stream(source, "video/mp4")
    assert audio.codec == "aac"
    assert audio.content_type == "audio/mp4"
    assert audio.filename.endswith(".m4a")
    assert audio.duration_ms >= 1000
    assert audio.sample_rate == 48000
    assert audio.channels == 1
    assert audio.data[4:8] == b"ftyp"


def test_video_split_emits_ordered_silent_clips_and_handles_remainder(tmp_path):
    source = _fixture_video(tmp_path / "source.mp4")
    result = split_video(
        source,
        "video/mp4",
        segment_duration_seconds=0.4,
        remainder_policy="keep",
        output_fps=24,
        max_segments=4,
    )
    assert result.source_duration_ms >= 1000
    assert len(result.clips) == 3
    assert [clip.index for clip in result.clips] == [0, 1, 2]
    assert [clip.start_ms for clip in result.clips] == [0, 400, 800]
    assert all(clip.width == 90 and clip.height == 160 and clip.fps == 24 for clip in result.clips)
    assert all(clip.data[4:8] == b"ftyp" for clip in result.clips)
    assert result.clips[-1].duration_ms < 400

    dropped = split_video(
        source,
        "video/mp4",
        segment_duration_seconds=0.4,
        remainder_policy="drop",
        output_fps=24,
        max_segments=4,
    )
    assert len(dropped.clips) == 2


def test_video_split_rejects_unbounded_fan_out(tmp_path):
    source = _fixture_video(tmp_path / "source.mp4")
    with pytest.raises(ValueError, match="exceeding max_segments"):
        split_video(
            source,
            "video/mp4",
            segment_duration_seconds=0.2,
            remainder_policy="keep",
            output_fps=24,
            max_segments=2,
        )


def _context(definition, db, *, parameters=None):
    return NodeExecutionContext(
        db=db,
        payload=ExperimentRunRequest(
            canvas_id="canvas_media",
            node_id="node_media",
            node_key=definition.type_key,
            node_contract_version=definition.contract_version,
            prompt="",
            model_alias=definition.execution.model_alias,
            parameters=parameters or {},
            inputs=[],
        ),
        definition=definition,
        request_hash="abcdef0123456789",
        experiment_id="experiment_media",
    )


def test_audio_extract_executor_records_stream_copy_and_source_lineage(monkeypatch):
    definition = node_registry.get("audio.extract", 1)
    assert definition is not None
    source = SimpleNamespace(id="video_1", type="Video", uri="s3://bucket/video.mp4", metadata_json={})

    class FakeDb:
        flushed = False

        def get(self, _, artifact_id):
            return source if artifact_id == source.id else None

        def flush(self):
            self.flushed = True

    db = FakeDb()
    captured = {}
    monkeypatch.setattr(executor_module, "_read_artifact", lambda _: (b"video", "video/mp4"))
    monkeypatch.setattr(executor_module, "extract_audio_stream", lambda *_: ExtractedAudio(
        data=b"audio",
        content_type="audio/mp4",
        filename="extracted.m4a",
        codec="aac",
        duration_ms=35641,
        sample_rate=48000,
        channels=2,
    ))

    def create_artifact(_, artifact_type, **kwargs):
        captured.update({"artifact_type": artifact_type, **kwargs})
        return SimpleNamespace(id="audio_1")

    monkeypatch.setattr(executor_module, "create_artifact", create_artifact)
    monkeypatch.setattr(executor_module, "artifact_content_url", lambda artifact_id: f"http://api/artifacts/{artifact_id}/content")
    result = AudioExtractExecutor().execute(
        _context(definition, db),
        node_registry.resolve_config(definition, {}),
        [{"type": "Video", "artifact_ids": [source.id]}],
    )
    assert result.output_artifact_ids == ["audio_1"]
    assert result.output["mimeType"] == "audio/mp4"
    assert result.metadata["retryable"] is False
    assert captured["artifact_type"] == "Audio"
    assert captured["schema_id"] == "audio.extracted.v1"
    assert captured["input_artifact_roles"] == {source.id: "source_video"}
    assert captured["metadata"]["stream_copy"] is True
    assert db.flushed is True


def test_video_split_and_clip_select_executors_preserve_ordered_collection(monkeypatch):
    split_definition = node_registry.get("video.split", 1)
    select_definition = node_registry.get("video.clip.select", 1)
    assert split_definition is not None and select_definition is not None
    source = SimpleNamespace(id="video_1", type="Video", schema_id=None, uri="s3://bucket/video.mp4", metadata_json={})
    stored = {source.id: source}

    class FakeDb:
        def get(self, _, artifact_id):
            return stored.get(artifact_id)

        def flush(self):
            return None

    db = FakeDb()
    monkeypatch.setattr(executor_module, "_read_artifact", lambda artifact: (
        json.dumps({
            "schema_version": VIDEO_CLIP_LIST_SCHEMA,
            "clips": [
                {"index": 0, "artifact_id": "clip_1", "start_ms": 0, "duration_ms": 8000},
                {"index": 1, "artifact_id": "clip_2", "start_ms": 8000, "duration_ms": 8000},
            ],
        }).encode() if artifact.type == "VideoClipList" else b"video",
        "application/json" if artifact.type == "VideoClipList" else "video/mp4",
    ))
    monkeypatch.setattr(executor_module, "split_video", lambda *_, **__: SplitVideo((
        SplitVideoClip(b"clip-one", 0, 0, 8000, 1080, 1920, 24),
        SplitVideoClip(b"clip-two", 1, 8000, 8000, 1080, 1920, 24),
    ), 16000))
    created = []

    def create_artifact(_, artifact_type, **kwargs):
        artifact_id = "collection_1" if artifact_type == "VideoClipList" else f"clip_{len([item for item in created if item['artifact_type'] == 'Video']) + 1}"
        artifact = SimpleNamespace(id=artifact_id, type=artifact_type, schema_id=kwargs.get("schema_id"), uri=f"s3://bucket/{artifact_id}", metadata_json={})
        created.append({"artifact_type": artifact_type, "artifact": artifact, **kwargs})
        stored[artifact_id] = artifact
        return artifact

    monkeypatch.setattr(executor_module, "create_artifact", create_artifact)
    monkeypatch.setattr(executor_module, "artifact_content_url", lambda artifact_id: f"http://api/artifacts/{artifact_id}/content")
    split_result = VideoSplitExecutor().execute(
        _context(split_definition, db),
        node_registry.resolve_config(split_definition, {"segment_duration_seconds": 8}),
        [{"type": "Video", "artifact_ids": [source.id]}],
    )
    assert split_result.output_artifact_ids == ["collection_1"]
    assert split_result.output["clipCount"] == 2
    assert split_result.metadata["retryable"] is False
    collection_call = created[-1]
    assert collection_call["schema_id"] == VIDEO_CLIP_LIST_SCHEMA
    assert collection_call["input_artifact_ids"] == ["video_1", "clip_1", "clip_2"]
    assert [item["metadata"]["clip_index"] for item in created[:2]] == [0, 1]
    assert all(item["schema_id"] == VIDEO_CLIP_SCHEMA for item in created[:2])

    selected = VideoClipSelectExecutor().execute(
        _context(select_definition, db, parameters={"clip_index": 1}),
        {"clip_index": 1},
        [{"type": "VideoClipList", "artifact_ids": ["collection_1"]}],
    )
    assert selected.output_artifact_ids == ["clip_2"]
    assert selected.output["title"] == "Video clip 2"
    assert selected.metadata["schema_id"] == VIDEO_CLIP_SCHEMA
    assert selected.metadata["retryable"] is False
