from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

from app.canvas_operations import ArtifactData
from app.domain import ExperimentRunRequest
from app.experiments import request_fingerprint
from app.image_story_video import _motion_filter
from app.nodes import node_registry
from app.nodes.contracts import NodeArtifactContent, NodeArtifactSnapshot, NodeExecutionContext
from app.nodes.executors import sro_video as executor_module
from app.nodes.executors.sro_video import (
    FRAME_APPLY_SCHEMA,
    FRAME_APPLY_V2_SCHEMA,
    FRAME_APPLY_V3_SCHEMA,
    FRAME_APPLY_V4_SCHEMA,
    FRAME_APPLY_V5_SCHEMA,
    IMAGE_MOTION_SCHEMA,
    IMAGE_MOTION_V2_SCHEMA,
    IMAGE_MOTION_V3_SCHEMA,
    IMAGE_MOTION_V4_SCHEMA,
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


def _context(definition, db, *, content_by_id=None, media_runtime=None) -> NodeExecutionContext:
    content_by_id = content_by_id or {}

    class FakeArtifactStore:
        def read(self, artifact_id):
            record = db.get(None, artifact_id)
            if record is None:
                raise ValueError(f"input artifact does not exist: {artifact_id}")
            data, content_type = content_by_id.get(
                artifact_id,
                (b"", "application/octet-stream"),
            )
            return NodeArtifactContent(
                NodeArtifactSnapshot(
                    id=record.id,
                    type=record.type,
                    schema_id=getattr(record, "schema_id", None),
                    sha256=getattr(record, "sha256", ""),
                ),
                data,
                content_type,
            )

        def flush(self):
            if hasattr(db, "flush"):
                db.flush()

        def content_url(self, artifact_id):
            return f"http://api/artifacts/{artifact_id}/content"

    return NodeExecutionContext(
        definition=definition,
        prompt="",
        model_alias=definition.execution.model_alias,
        request_hash="b" * 64,
        experiment_id="experiment_sro",
        artifact_store=FakeArtifactStore(),
        media_runtime=media_runtime,
    )


def _capture_artifacts(monkeypatch):
    created = []

    def create_artifact(_, artifact_type, **kwargs):
        artifact = _record(f"artifact_{len(created) + 1}", artifact_type)
        created.append({"artifact": artifact, "artifact_type": artifact_type, **kwargs})
        return artifact

    monkeypatch.setattr(executor_module, "create_artifact", create_artifact)
    return created


def test_sro_story_pipeline_uses_a_shared_frame_artifact_without_mutating_v1():
    motion = node_registry.get("image.motion", 1)
    motion_v2 = node_registry.get("image.motion", 2)
    motion_v3 = node_registry.get("image.motion", 3)
    motion_v4 = node_registry.get("image.motion", 4)
    frame_layout = node_registry.get("layout.media_frame", 1)
    frame_v1 = node_registry.get("video.frame_apply", 1)
    frame_v2 = node_registry.get("video.frame_apply", 2)
    frame_v3 = node_registry.get("video.frame_apply", 3)
    frame_v4 = node_registry.get("video.frame_apply", 4)
    frame_v5 = node_registry.get("video.frame_apply", 5)
    concatenate = node_registry.get("video.concatenate", 1)
    captions = node_registry.get("subtitle.layout", 1)
    compose = node_registry.get("video.compose", 1)
    assert all((motion, motion_v2, motion_v3, motion_v4, frame_layout, frame_v1, frame_v2, frame_v3, frame_v4, frame_v5, concatenate, captions, compose))
    assert [(port.type, port.multiple) for port in motion.ports.inputs] == [("media.image.v1", False)]
    assert motion.ports.outputs[0].type == "data.media_motion.v1"
    assert motion_v2.ports.outputs[0].type == "data.media_motion.v2"
    assert motion_v3.ports.outputs[0].type == "data.media_motion.v3"
    assert motion_v4.ports.outputs[0].type == "data.media_motion.v4"
    assert motion_v2.config_schema["properties"]["path_type"]["enum"] == ["linear", "cubic_bezier"]
    assert motion_v3.config_schema["properties"]["zoom_easing"]["enum"] == ["linear", "ease_in", "ease_out", "ease_in_out"]
    assert frame_layout.ports.outputs[0].type == "data.media_frame.v1"
    assert [port.type for port in frame_v1.ports.inputs] == ["data.media_motion.v1"]
    assert [port.type for port in frame_v2.ports.inputs] == ["data.media_motion.v1", "data.media_frame.v1"]
    assert [port.type for port in frame_v3.ports.inputs] == ["data.media_motion.v2", "data.media_frame.v1"]
    assert [port.type for port in frame_v4.ports.inputs] == ["data.media_motion.v3", "data.media_frame.v1"]
    assert [port.type for port in frame_v5.ports.inputs] == ["data.media_motion.v4", "data.media_frame.v1"]
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


def test_image_motion_v2_and_frame_apply_v3_snapshot_and_render_cubic_bezier_path(monkeypatch):
    motion_definition = node_registry.get("image.motion", 2)
    frame_definition = node_registry.get("video.frame_apply", 3)
    image = _record("image_curve", "Image")
    monkeypatch.setattr(executor_module, "_read_artifacts", lambda *_: [ArtifactData(image, b"image", "image/png")])
    created = _capture_artifacts(monkeypatch)
    db = SimpleNamespace(flush=lambda: None)
    config = node_registry.resolve_config(motion_definition, {
        "path_type": "cubic_bezier",
        "start_x": 0.15,
        "start_y": 0.2,
        "control_1_x": 0.15,
        "control_1_y": 0.8,
        "control_2_x": 0.85,
        "control_2_y": 0.2,
        "end_x": 0.85,
        "end_y": 0.8,
    })
    ImageMotionExecutor().execute(
        _context(motion_definition, db),
        config,
        [{"type": "Image", "artifact_ids": [image.id]}],
    )
    plan = json.loads(created[0]["content"])
    assert created[0]["schema_id"] == IMAGE_MOTION_V2_SCHEMA
    assert plan["path"] == {
        "type": "cubic_bezier",
        "control_1": {"x": 0.15, "y": 0.8},
        "control_2": {"x": 0.85, "y": 0.2},
    }

    motion_record = _record("motion_curve", "MediaMotion")
    frame_record = _record("frame_shared", "MediaFrame", "f" * 64)
    frame_layout = {
        "schema_version": MEDIA_FRAME_SCHEMA,
        "canvas": {"aspect_ratio": "9:16", "resolution": "1080p", "background_color": "#11100E"},
        "frame": {"x": 0.04, "y": 0.12, "width": 0.92, "height": 0.64, "media_fit": "cover"},
    }
    monkeypatch.setattr(executor_module, "_read_artifacts", lambda *_: [
        ArtifactData(motion_record, json.dumps(plan).encode(), "application/json"),
        ArtifactData(frame_record, json.dumps(frame_layout).encode(), "application/json"),
    ])
    monkeypatch.setattr(executor_module, "_source_image", lambda *_: (image, b"image", "image/png"))
    captured = []
    monkeypatch.setattr(executor_module, "render_framed_motion", lambda image_bytes, content_type, motion, render_config: (captured.append((motion, render_config)) or b"curve-video", {"width": 1080, "height": 1920, "duration_ms": 10_000}))
    VideoFrameApplyExecutor().execute(
        _context(frame_definition, db),
        {},
        [
            {"type": "MediaMotion", "artifact_ids": [motion_record.id]},
            {"type": "MediaFrame", "artifact_ids": [frame_record.id]},
        ],
    )
    assert created[1]["schema_id"] == FRAME_APPLY_V3_SCHEMA
    assert captured[0][0]["path"]["type"] == "cubic_bezier"
    assert captured[0][1]["frame_y"] == 0.12


def test_image_motion_v3_and_frame_apply_v4_snapshot_independent_path_zoom_timing(monkeypatch):
    motion_definition = node_registry.get("image.motion", 3)
    frame_definition = node_registry.get("video.frame_apply", 4)
    image = _record("image_keyframed", "Image")
    monkeypatch.setattr(executor_module, "_read_artifacts", lambda *_: [ArtifactData(image, b"image", "image/png")])
    created = _capture_artifacts(monkeypatch)
    db = SimpleNamespace(flush=lambda: None)
    config = node_registry.resolve_config(motion_definition, {
        "path_type": "cubic_bezier",
        "path_end_progress": 0.45,
        "zoom_end_progress": 0.65,
        "zoom_easing": "ease_in_out",
        "start_x": 0.2,
        "start_y": 0.25,
        "control_1_x": 0.2,
        "control_1_y": 0.7,
        "control_2_x": 0.8,
        "control_2_y": 0.3,
        "end_x": 0.8,
        "end_y": 0.75,
    })
    ImageMotionExecutor().execute(
        _context(motion_definition, db),
        config,
        [{"type": "Image", "artifact_ids": [image.id]}],
    )
    plan = json.loads(created[0]["content"])
    assert created[0]["schema_id"] == IMAGE_MOTION_V3_SCHEMA
    assert plan["path"]["end_progress"] == 0.45
    assert plan["zoom"] == {"end_progress": 0.65, "easing": "ease_in_out"}
    assert "easing" not in plan

    motion_record = _record("motion_keyframed", "MediaMotion")
    frame_record = _record("frame_shared", "MediaFrame", "f" * 64)
    frame_layout = {
        "schema_version": MEDIA_FRAME_SCHEMA,
        "canvas": {"aspect_ratio": "9:16", "resolution": "1080p", "background_color": "#11100E"},
        "frame": {"x": 0, "y": 0.1, "width": 1, "height": 0.65, "media_fit": "cover"},
    }
    monkeypatch.setattr(executor_module, "_read_artifacts", lambda *_: [
        ArtifactData(motion_record, json.dumps(plan).encode(), "application/json"),
        ArtifactData(frame_record, json.dumps(frame_layout).encode(), "application/json"),
    ])
    monkeypatch.setattr(executor_module, "_source_image", lambda *_: (image, b"image", "image/png"))
    captured = []
    monkeypatch.setattr(executor_module, "render_framed_motion", lambda image_bytes, content_type, motion, render_config: (captured.append(motion) or b"held-video", {"width": 1080, "height": 1920, "duration_ms": 10_000}))
    VideoFrameApplyExecutor().execute(
        _context(frame_definition, db),
        {},
        [
            {"type": "MediaMotion", "artifact_ids": [motion_record.id]},
            {"type": "MediaFrame", "artifact_ids": [frame_record.id]},
        ],
    )
    assert created[1]["schema_id"] == FRAME_APPLY_V4_SCHEMA
    assert captured[0]["path"]["end_progress"] == 0.45
    assert captured[0]["zoom"]["end_progress"] == 0.65


def test_image_motion_v4_and_frame_apply_v5_use_full_source_view_center_coordinates(monkeypatch):
    motion_definition = node_registry.get("image.motion", 4)
    frame_definition = node_registry.get("video.frame_apply", 5)
    image = _record("image_full_source", "Image")
    monkeypatch.setattr(executor_module, "_read_artifacts", lambda *_: [ArtifactData(image, b"image", "image/png")])
    created = _capture_artifacts(monkeypatch)
    db = SimpleNamespace(flush=lambda: None)
    config = node_registry.resolve_config(motion_definition, {
        "path_type": "cubic_bezier",
        "start_scale": 1.2,
        "start_x": 0.5,
        "start_y": 0.65,
        "control_1_x": 0.5,
        "control_1_y": 0.5,
        "control_2_x": 0.5,
        "control_2_y": 0.3,
        "end_scale": 2,
        "end_x": 0.5,
        "end_y": 0.16,
    })
    ImageMotionExecutor().execute(
        _context(motion_definition, db),
        config,
        [{"type": "Image", "artifact_ids": [image.id]}],
    )
    plan = json.loads(created[0]["content"])
    assert created[0]["schema_id"] == IMAGE_MOTION_V4_SCHEMA
    assert plan["coordinate_space"] == "source_image_view_center"
    assert plan["start"] == {"scale": 1.2, "x": 0.5, "y": 0.65}
    assert plan["end"] == {"scale": 2.0, "x": 0.5, "y": 0.16}

    motion_record = _record("motion_full_source", "MediaMotion")
    frame_record = _record("frame_shared", "MediaFrame", "f" * 64)
    frame_layout = {
        "schema_version": MEDIA_FRAME_SCHEMA,
        "canvas": {"aspect_ratio": "9:16", "resolution": "1080p", "background_color": "#11100E"},
        "frame": {"x": 0, "y": 0.1, "width": 1, "height": 0.65, "media_fit": "cover"},
    }
    monkeypatch.setattr(executor_module, "_read_artifacts", lambda *_: [
        ArtifactData(motion_record, json.dumps(plan).encode(), "application/json"),
        ArtifactData(frame_record, json.dumps(frame_layout).encode(), "application/json"),
    ])
    monkeypatch.setattr(executor_module, "_source_image", lambda *_: (image, b"image", "image/png"))
    captured = []
    monkeypatch.setattr(executor_module, "render_framed_motion", lambda image_bytes, content_type, motion, render_config: (captured.append(motion) or b"full-source-video", {"width": 1080, "height": 1920, "duration_ms": 10_000}))
    VideoFrameApplyExecutor().execute(
        _context(frame_definition, db),
        {},
        [
            {"type": "MediaMotion", "artifact_ids": [motion_record.id]},
            {"type": "MediaFrame", "artifact_ids": [frame_record.id]},
        ],
    )
    assert created[1]["schema_id"] == FRAME_APPLY_V5_SCHEMA
    assert captured[0]["coordinate_space"] == "source_image_view_center"


def test_motion_filter_emits_cubic_bezier_focus_expressions_without_changing_linear_default():
    curve = _motion_filter(
        motion="custom", amount=0, frames=25, width=360, height=640, fps=24,
        motion_start_scale=1.1, motion_end_scale=1.2,
        motion_start_x=0.1, motion_start_y=0.2,
        motion_control_1_x=0.2, motion_control_1_y=0.8,
        motion_control_2_x=0.8, motion_control_2_y=0.2,
        motion_end_x=0.9, motion_end_y=0.8,
        motion_path_type="cubic_bezier",
    )
    linear = _motion_filter(
        motion="custom", amount=0, frames=25, width=360, height=640, fps=24,
        motion_start_x=0.1, motion_start_y=0.2, motion_end_x=0.9, motion_end_y=0.8,
    )
    assert "3*(1-(min(1,(on/24)/1.00000000)))" in curve
    assert "(min(1,(on/24)/1.00000000))*0.20000000" in curve
    assert "0.10000000+(0.80000000)*(min(1,(on/24)/1.00000000))" in linear
    assert "3*(1-(min(1,(on/24)/1.00000000)))" not in linear


def test_cubic_bezier_motion_filter_is_accepted_by_ffmpeg():
    filter_graph = _motion_filter(
        motion="custom", amount=0, frames=25, width=180, height=320, fps=24,
        motion_start_scale=1.1, motion_end_scale=1.2,
        motion_start_x=0.1, motion_start_y=0.2,
        motion_control_1_x=0.2, motion_control_1_y=0.8,
        motion_control_2_x=0.8, motion_control_2_y=0.2,
        motion_end_x=0.9, motion_end_y=0.8,
        motion_path_type="cubic_bezier",
        motion_path_end_progress=0.45,
        motion_zoom_end_progress=0.65,
        motion_zoom_easing="ease_in_out",
    )
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "testsrc2=size=640x640:rate=1",
            "-vf", filter_graph, "-frames:v", "25", "-an", "-f", "null", "-",
        ],
        check=True,
        capture_output=True,
        timeout=90,
    )


def test_full_source_center_motion_filter_traverses_without_pre_crop_and_is_accepted_by_ffmpeg():
    filter_graph = _motion_filter(
        motion="custom", amount=0, frames=25, width=180, height=200, fps=24,
        motion_start_scale=1.2, motion_end_scale=2,
        motion_start_x=0.5, motion_start_y=0.65,
        motion_control_1_x=0.5, motion_control_1_y=0.5,
        motion_control_2_x=0.5, motion_control_2_y=0.3,
        motion_end_x=0.5, motion_end_y=0.16,
        motion_path_type="cubic_bezier",
        motion_path_end_progress=0.7,
        motion_zoom_end_progress=0.7,
        motion_zoom_easing="ease_in_out",
        motion_coordinate_space="source_image_view_center",
    )
    assert "force_original_aspect_ratio=increase" in filter_graph
    assert "scale=w='trunc(iw*" in filter_graph
    assert "clip((" in filter_graph
    assert "n/24" in filter_graph
    assert "zoompan=" not in filter_graph
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "testsrc2=size=360x640:rate=24",
            "-vf", filter_graph, "-frames:v", "25", "-an", "-f", "null", "-",
        ],
        check=True,
        capture_output=True,
        timeout=90,
    )


def test_bezier_path_changes_the_v2_motion_request_hash():
    definition = node_registry.get("image.motion", 2)
    linear_config = node_registry.resolve_config(definition, {})
    linear = ExperimentRunRequest(
        canvas_id="canvas_curve",
        node_id="motion_curve",
        node_key="image.motion",
        node_contract_version=2,
        model_alias=definition.execution.model_alias,
        parameters=linear_config,
        inputs=[{"type": "Image", "artifact_ids": ["image_1"]}],
    )
    curve = linear.model_copy(update={"parameters": {
        **linear_config,
        "path_type": "cubic_bezier",
        "control_1_x": 0.2,
        "control_1_y": 0.8,
        "control_2_x": 0.8,
        "control_2_y": 0.2,
    }})
    assert request_fingerprint(linear, "local.image-motion", "local.image-motion") != request_fingerprint(curve, "local.image-motion", "local.image-motion")


def test_hold_and_zoom_timing_change_the_v3_motion_request_hash():
    definition = node_registry.get("image.motion", 3)
    base_config = node_registry.resolve_config(definition, {})
    base = ExperimentRunRequest(
        canvas_id="canvas_hold",
        node_id="motion_hold",
        node_key="image.motion",
        node_contract_version=3,
        model_alias=definition.execution.model_alias,
        parameters=base_config,
        inputs=[{"type": "Image", "artifact_ids": ["image_1"]}],
    )
    changed = base.model_copy(update={"parameters": {
        **base_config,
        "path_end_progress": 0.4,
        "zoom_end_progress": 0.8,
        "zoom_easing": "ease_out",
    }})
    assert request_fingerprint(base, "local.image-motion", "local.image-motion") != request_fingerprint(changed, "local.image-motion", "local.image-motion")


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
    concatenate_result = VideoConcatenateExecutor().execute(
        _context(
            concatenate_definition,
            db,
            media_runtime=SimpleNamespace(edit_videos=lambda artifacts, config: b"joined"),
        ),
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
    monkeypatch.setattr(executor_module, "compose_video", lambda *args: (b"final", {"width": 1080, "height": 1920, "duration_ms": 1000}))
    compose_result = VideoComposeExecutor().execute(
        _context(
            compose_definition,
            FakeDb(),
            content_by_id={subtitle.id: (srt, "application/x-subrip")},
        ),
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
