from __future__ import annotations

import json
from types import SimpleNamespace

from app.canvas_operations import ArtifactData
from app.domain import ExperimentRunRequest
from app.nodes import node_registry
from app.nodes.contracts import NodeExecutionContext
from app.nodes.executors import sro_video as executor_module
from app.nodes.executors.sro_video import (
    FRAME_APPLY_SCHEMA,
    FRAME_APPLY_V2_SCHEMA,
    IMAGE_MOTION_SCHEMA,
    MEDIA_FRAME_SCHEMA,
    SUBTITLE_LAYOUT_SCHEMA,
    VIDEO_COMPOSE_SCHEMA,
    VIDEO_CONCATENATE_SCHEMA,
    ImageMotionExecutor,
    MediaFrameLayoutExecutor,
    SubtitleLayoutExecutor,
    VideoComposeExecutor,
    VideoConcatenateExecutor,
    VideoFrameApplyExecutor,
)


def _record(artifact_id: str, artifact_type: str, sha256: str = "a" * 64):
    return SimpleNamespace(
        id=artifact_id,
        type=artifact_type,
        sha256=sha256,
        uri=f"s3://bucket/{artifact_id}",
        metadata_json={"storage": {"content_type": "application/octet-stream"}},
    )


def _context(definition, db) -> NodeExecutionContext:
    return NodeExecutionContext(
        db=db,
        payload=ExperimentRunRequest(
            canvas_id="canvas_sro",
            node_id="node_sro",
            node_key=definition.type_key,
            node_contract_version=definition.contract_version,
            model_alias=definition.execution.model_alias,
            parameters={},
            inputs=[],
        ),
        definition=definition,
        request_hash="b" * 64,
        experiment_id="experiment_sro",
    )


def _capture_artifacts(monkeypatch):
    created = []

    def create_artifact(_, artifact_type, **kwargs):
        artifact = _record(f"artifact_{len(created) + 1}", artifact_type)
        created.append({"artifact": artifact, "artifact_type": artifact_type, **kwargs})
        return artifact

    monkeypatch.setattr(executor_module, "create_artifact", create_artifact)
    monkeypatch.setattr(executor_module, "artifact_content_url", lambda artifact_id: f"http://api/artifacts/{artifact_id}/content")
    return created


def test_sro_story_pipeline_uses_a_shared_frame_artifact_without_mutating_v1():
    motion = node_registry.get("image.motion", 1)
    frame_layout = node_registry.get("layout.media_frame", 1)
    frame_v1 = node_registry.get("video.frame_apply", 1)
    frame_v2 = node_registry.get("video.frame_apply", 2)
    concatenate = node_registry.get("video.concatenate", 1)
    captions = node_registry.get("subtitle.layout", 1)
    compose = node_registry.get("video.compose", 1)
    assert all((motion, frame_layout, frame_v1, frame_v2, concatenate, captions, compose))
    assert [(port.type, port.multiple) for port in motion.ports.inputs] == [("media.image.v1", False)]
    assert motion.ports.outputs[0].type == "data.media_motion.v1"
    assert frame_layout.ports.outputs[0].type == "data.media_frame.v1"
    assert [port.type for port in frame_v1.ports.inputs] == ["data.media_motion.v1"]
    assert [port.type for port in frame_v2.ports.inputs] == ["data.media_motion.v1", "data.media_frame.v1"]
    assert frame_v2.config_schema["properties"] == {}
    assert frame_v2.ports.outputs[0].type == "media.video.v1"
    assert [(port.type, port.multiple) for port in concatenate.ports.inputs] == [("media.video.v1", True)]
    assert captions.ports.inputs[0].type == "data.subtitle.v1"
    assert captions.ports.outputs[0].type == "data.caption_layout.v1"
    assert [port.type for port in compose.ports.inputs] == [
        "media.video.v1",
        "data.caption_layout.v1",
        "media.audio.v1",
    ]
    assert compose.artifact_contract.primary_type == "FinalVideo"
    assert node_registry.get("video.media_story", 1) is not None


def test_image_motion_executor_snapshots_one_image_and_start_end_transform(monkeypatch):
    definition = node_registry.get("image.motion", 1)
    image = _record("image_1", "Image")
    artifacts = [ArtifactData(image, b"image", "image/png")]
    monkeypatch.setattr(executor_module, "_read_artifacts", lambda *_: artifacts)
    created = _capture_artifacts(monkeypatch)
    db = SimpleNamespace(flush=lambda: None)
    config = node_registry.resolve_config(definition, {"end_x": 0.75, "end_scale": 1.25})
    result = ImageMotionExecutor().execute(_context(definition, db), config, [{"type": "Image", "artifact_ids": [image.id]}])

    plan = json.loads(created[0]["content"])
    assert created[0]["artifact_type"] == "MediaMotion"
    assert created[0]["schema_id"] == IMAGE_MOTION_SCHEMA
    assert plan["source"]["artifact_id"] == image.id
    assert plan["start"] == {"scale": 1.0, "x": 0.5, "y": 0.5}
    assert plan["end"] == {"scale": 1.25, "x": 0.75, "y": 0.5}
    assert result.metadata["retryable"] is False


def test_media_frame_executor_materializes_a_reusable_layout_artifact(monkeypatch):
    definition = node_registry.get("layout.media_frame", 1)
    created = _capture_artifacts(monkeypatch)
    db = SimpleNamespace(flush=lambda: None)
    config = node_registry.resolve_config(definition, {
        "frame_x": 0.1,
        "frame_y": 0.15,
        "frame_width": 0.8,
        "frame_height": 0.5,
    })
    result = MediaFrameLayoutExecutor().execute(_context(definition, db), config, [])

    layout = json.loads(created[0]["content"])
    assert created[0]["artifact_type"] == "MediaFrame"
    assert created[0]["schema_id"] == MEDIA_FRAME_SCHEMA
    assert created[0]["input_artifact_ids"] == []
    assert layout["canvas"] == {
        "aspect_ratio": "9:16",
        "resolution": "1080p",
        "background_color": "#11100E",
    }
    assert layout["frame"] == {
        "x": 0.1,
        "y": 0.15,
        "width": 0.8,
        "height": 0.5,
        "media_fit": "cover",
    }
    assert result.output_artifact_ids == ["artifact_1"]


def test_two_frame_apply_v2_nodes_can_render_different_images_with_one_frame_artifact(monkeypatch):
    definition = node_registry.get("video.frame_apply", 2)
    frame_record = _record("frame_shared", "MediaFrame", "f" * 64)
    frame_layout = {
        "schema_version": MEDIA_FRAME_SCHEMA,
        "canvas": {"aspect_ratio": "9:16", "resolution": "1080p", "background_color": "#11100E"},
        "frame": {"x": 0.08, "y": 0.04, "width": 0.84, "height": 0.6, "media_fit": "cover"},
    }
    frame_data = ArtifactData(frame_record, json.dumps(frame_layout).encode(), "application/json")
    created = _capture_artifacts(monkeypatch)
    captured_configs = []
    monkeypatch.setattr(executor_module, "render_framed_motion", lambda image, content_type, plan, config: (captured_configs.append(config.copy()) or b"clip", {"width": 1080, "height": 1920, "duration_ms": 4000}))
    monkeypatch.setattr(executor_module, "_source_image", lambda context, source: (_record(source["artifact_id"], "Image"), b"image", "image/png"))
    db = SimpleNamespace(flush=lambda: None)

    for index in (1, 2):
        motion_record = _record(f"motion_{index}", "MediaMotion", str(index) * 64)
        motion = {
            "schema_version": IMAGE_MOTION_SCHEMA,
            "source": {"artifact_id": f"image_{index}", "sha256": str(index) * 64},
            "duration_seconds": 4,
            "fps": 24,
            "start": {"scale": 1, "x": 0.5, "y": 0.5},
            "end": {"scale": 1.2, "x": 0.5, "y": 0.5},
        }
        motion_data = ArtifactData(motion_record, json.dumps(motion).encode(), "application/json")
        monkeypatch.setattr(executor_module, "_read_artifacts", lambda *_, current=motion_data: [current, frame_data])
        result = VideoFrameApplyExecutor().execute(
            _context(definition, db),
            {},
            [
                {"type": "MediaMotion", "artifact_ids": [motion_record.id]},
                {"type": "MediaFrame", "artifact_ids": [frame_record.id]},
            ],
        )
        assert result.output["kind"] == "video"

    assert captured_configs == [
        {
            "aspect_ratio": "9:16", "resolution": "1080p", "background_color": "#11100E",
            "frame_x": 0.08, "frame_y": 0.04, "frame_width": 0.84, "frame_height": 0.6, "media_fit": "cover",
        },
    ] * 2
    assert [item["schema_id"] for item in created] == [FRAME_APPLY_V2_SCHEMA, FRAME_APPLY_V2_SCHEMA]
    assert [item["input_artifact_roles"][frame_record.id] for item in created] == ["media_frame", "media_frame"]
    assert [item["input_artifact_ids"] for item in created] == [
        ["motion_1", "frame_shared", "image_1"],
        ["motion_2", "frame_shared", "image_2"],
    ]


def test_frame_apply_and_concatenate_executors_only_render_and_join(monkeypatch):
    frame_definition = node_registry.get("video.frame_apply", 1)
    concatenate_definition = node_registry.get("video.concatenate", 1)
    motion_record = _record("motion_1", "MediaMotion")
    image_record = _record("image_1", "Image")
    motion = {
        "schema_version": IMAGE_MOTION_SCHEMA,
        "source": {"artifact_id": image_record.id, "sha256": image_record.sha256},
        "duration_seconds": 4,
        "fps": 24,
        "start": {"scale": 1, "x": 0.5, "y": 0.5},
        "end": {"scale": 1.2, "x": 0.7, "y": 0.5},
    }
    motion_data = ArtifactData(motion_record, json.dumps(motion).encode(), "application/json")
    monkeypatch.setattr(executor_module, "_read_artifacts", lambda *_: [motion_data])
    monkeypatch.setattr(executor_module, "_source_image", lambda *_: (image_record, b"image", "image/png"))
    monkeypatch.setattr(executor_module, "render_framed_motion", lambda *args: (b"clip", {"width": 1080, "height": 1920, "duration_ms": 4000}))
    created = _capture_artifacts(monkeypatch)
    db = SimpleNamespace(flush=lambda: None)
    frame_result = VideoFrameApplyExecutor().execute(
        _context(frame_definition, db),
        node_registry.resolve_config(frame_definition, {}),
        [{"type": "MediaMotion", "artifact_ids": [motion_record.id]}],
    )
    assert created[0]["schema_id"] == FRAME_APPLY_SCHEMA
    assert created[0]["input_artifact_ids"] == [motion_record.id, image_record.id]
    assert frame_result.output["kind"] == "video"

    first = _record("clip_1", "Video")
    second = _record("clip_2", "Video")
    videos = [ArtifactData(first, b"one", "video/mp4"), ArtifactData(second, b"two", "video/mp4")]
    monkeypatch.setattr(executor_module, "_read_artifacts", lambda *_: videos)
    monkeypatch.setattr(executor_module, "_edit_videos", lambda artifacts, config: b"joined")
    concatenate_result = VideoConcatenateExecutor().execute(
        _context(concatenate_definition, db),
        {},
        [{"type": "Video", "artifact_ids": [first.id, second.id]}],
    )
    assert created[1]["schema_id"] == VIDEO_CONCATENATE_SCHEMA
    assert created[1]["metadata"]["clip_count"] == 2
    assert concatenate_result.output["title"] == "Connected video · 2 clips"


def test_subtitle_layout_and_final_compose_keep_layout_and_mux_responsibilities_separate(monkeypatch):
    layout_definition = node_registry.get("subtitle.layout", 1)
    compose_definition = node_registry.get("video.compose", 1)
    subtitle = _record("subtitle_1", "Subtitle")
    srt = b"1\n00:00:00,000 --> 00:00:01,000\nHello\n"
    subtitle_data = ArtifactData(subtitle, srt, "application/x-subrip")
    monkeypatch.setattr(executor_module, "_read_artifacts", lambda *_: [subtitle_data])
    created = _capture_artifacts(monkeypatch)
    db = SimpleNamespace(flush=lambda: None)
    config = node_registry.resolve_config(layout_definition, {"frame_y": 0.7, "frame_height": 0.2})
    layout_result = SubtitleLayoutExecutor().execute(
        _context(layout_definition, db),
        config,
        [{"type": "Subtitle", "artifact_ids": [subtitle.id]}],
    )
    layout = json.loads(created[0]["content"])
    assert created[0]["schema_id"] == SUBTITLE_LAYOUT_SCHEMA
    assert layout["subtitle"]["artifact_id"] == subtitle.id
    assert layout["frame"]["y"] == 0.7
    assert layout_result.output["title"] == "Subtitle region · 1 cues"

    video = _record("video_1", "Video")
    layout_record = _record("layout_1", "CaptionLayout")
    audio = _record("audio_1", "Audio")
    compose_inputs = [
        ArtifactData(video, b"video", "video/mp4"),
        ArtifactData(layout_record, json.dumps(layout).encode(), "application/json"),
        ArtifactData(audio, b"audio", "audio/wav"),
    ]

    class FakeDb:
        def get(self, _, artifact_id):
            return subtitle if artifact_id == subtitle.id else None

        def flush(self):
            return None

    monkeypatch.setattr(executor_module, "_read_artifacts", lambda *_: compose_inputs)
    monkeypatch.setattr(executor_module, "storage_location", lambda *_: ("bucket", "subtitle.srt"))
    monkeypatch.setattr(executor_module, "get_storage", lambda: SimpleNamespace(get_bytes=lambda **_: srt))
    monkeypatch.setattr(executor_module, "compose_video", lambda *args: (b"final", {"width": 1080, "height": 1920, "duration_ms": 1000}))
    compose_result = VideoComposeExecutor().execute(
        _context(compose_definition, FakeDb()),
        {},
        [
            {"type": "Video", "artifact_ids": [video.id]},
            {"type": "CaptionLayout", "artifact_ids": [layout_record.id]},
            {"type": "Audio", "artifact_ids": [audio.id]},
        ],
    )
    assert created[1]["schema_id"] == VIDEO_COMPOSE_SCHEMA
    assert created[1]["input_artifact_roles"] == {
        video.id: "video",
        layout_record.id: "caption_layout",
        audio.id: "narration_audio",
        subtitle.id: "subtitle_snapshot",
    }
    assert compose_result.output["kind"] == "video"
