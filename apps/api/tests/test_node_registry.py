from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from app import canvas_activities
from app.domain import ExperimentRunRequest
from app.experiments import request_fingerprint, resolve_model
from app.motion_control_video import MOTION_CONTROL_VIDEO_REVISION, RenderedMotionControlVideo, parse_motion_track, render_motion_control_video
from app.nodes import node_registry
from app.nodes.contracts import NodeExecutionContext
from app.nodes.executors import lora_train as lora_train_module
from app.nodes.executors.lora_train import FalLoraTrainingExecutor
from app.nodes.executors import motion_control_video as motion_control_module
from app.nodes.executors.motion_control_video import MotionControlVideoExecutor


def test_lora_train_manifest_is_registered_and_digest_is_stable():
    definition = node_registry.get("lora.train", 1)
    assert definition is not None
    assert definition.lifecycle == "ACTIVE"
    assert definition.execution.executor == "fal-lora-training"
    assert definition.ports.inputs[0].type == "artifact.character.v1"
    assert definition.ports.inputs[0].required is True
    assert definition.ports.outputs[0].type == "artifact.character.v1"
    assert definition.definition_digest.startswith("sha256:")
    assert definition.public_payload()["definition_digest"] == definition.definition_digest


def test_lora_train_config_defaults_and_validation_come_from_manifest():
    definition = node_registry.get("lora.train", 1)
    assert definition is not None
    resolved = node_registry.resolve_config(definition, {"trigger_word": "mori_cat_v1"})
    assert resolved == {
        "trigger_word": "mori_cat_v1",
        "steps": 1000,
        "learning_rate": 0.00005,
        "timeout_seconds": 1800,
    }
    with pytest.raises(ValueError, match="invalid format"):
        node_registry.resolve_config(definition, {"trigger_word": "not allowed"})
    with pytest.raises(ValueError, match="must be one of"):
        node_registry.resolve_config(definition, {"trigger_word": "mori", "steps": 900})


def test_lora_train_executor_returns_trained_character_contract(monkeypatch):
    definition = node_registry.get("lora.train", 1)
    assert definition is not None
    character = SimpleNamespace(
        id="character_1",
        type="Character",
        metadata_json={
            "name": "Mori",
            "cover_artifact_id": "image_1",
            "lora_status": "UNTRAINED",
        },
    )

    class FakeDb:
        def get(self, _, artifact_id):
            return character if artifact_id == character.id else None

    monkeypatch.setattr(lora_train_module, "start_character_lora_training", lambda *args, **kwargs: {"status": "IN_QUEUE"})
    monkeypatch.setattr(lora_train_module, "wait_for_character_lora_training", lambda *args, **kwargs: {
        "status": "READY",
        "trigger_word": "mori_cat_v1",
        "lora_artifact_id": "lora_1",
        "weights_url": "https://weights.example/mori.safetensors",
        "request_id": "fal_request_1",
    })
    monkeypatch.setattr(lora_train_module, "require_character", lambda *args, **kwargs: character)
    monkeypatch.setattr(lora_train_module, "artifact_content_url", lambda artifact_id: f"http://api/artifacts/{artifact_id}/content")

    payload = ExperimentRunRequest(
        canvas_id="canvas_1",
        node_id="trainer_1",
        node_key="lora.train",
        prompt="",
        model_alias="fal.training.flux2-lora",
        parameters={},
        inputs=[],
    )
    context = NodeExecutionContext(db=FakeDb(), payload=payload, definition=definition, request_hash="digest", experiment_id="experiment_1")
    result = FalLoraTrainingExecutor().execute(
        context,
        {"trigger_word": "mori_cat_v1", "steps": 1000, "learning_rate": 0.00005, "timeout_seconds": 1800},
        [{"type": "Character", "artifact_ids": [character.id]}],
    )
    assert result.output_artifact_ids == ["character_1", "lora_1"]
    assert result.provider_request_id == "fal_request_1"
    assert result.output["characterId"] == "character_1"
    assert result.output["url"].endswith("/image_1/content")


def motion_track_fixture() -> dict:
    pose = [{"x": 0.5, "y": 0.5, "z": 0.0, "visibility": 1.0} for _ in range(33)]
    hand = [{"x": 0.35 + index * 0.01, "y": 0.45 + index * 0.005, "z": 0.0} for index in range(21)]
    face = [{"x": 0.48, "y": 0.3, "z": 0.0} for _ in range(478)]
    return {
        "schema_version": "motion.track.v1",
        "extractor": {
            "name": "fixture",
            "revision": "fixture.v1",
            "model": "fixture",
            "min_confidence": 0.5,
            "output_face_blendshapes": False,
        },
        "source": {
            "duration_ms": 250,
            "width": 90,
            "height": 160,
            "sample_fps": 4,
            "sample_width": 90,
            "sample_height": 160,
            "sha256": "0" * 64,
        },
        "summary": {"frame_count": 2, "coverage": {"face": 1, "pose": 1, "left_hand": 1, "right_hand": 1}},
        "frames": [
            {
                "timestamp_ms": timestamp,
                "face_landmarks": face,
                "pose_landmarks": pose,
                "pose_world_landmarks": pose,
                "left_hand_landmarks": hand,
                "left_hand_world_landmarks": hand,
                "right_hand_landmarks": hand,
                "right_hand_world_landmarks": hand,
                "face_blendshapes": [],
                "channels": {},
            }
            for timestamp in (0, 250)
        ],
    }


def test_motion_control_manifest_is_registered_with_versioned_ports():
    definition = node_registry.get("motion.control_video", 1)
    assert definition is not None
    assert definition.lifecycle == "ACTIVE"
    assert definition.execution.kind == "local"
    assert definition.execution.executor == "motion-control-video"
    assert definition.execution.revision == MOTION_CONTROL_VIDEO_REVISION
    assert definition.ports.inputs[0].type == "data.motion_track.v1"
    assert definition.ports.inputs[0].required is True
    assert definition.ports.outputs[0].type == "media.video.v1"
    assert definition.artifact_contract.schema_id == "motion.control_video.v1"
    assert definition.definition_digest == "sha256:2ed2a81b5b586b7384dd32473b3ea0466d1fe5a124f49b18ec3703417144999a"


def test_motion_control_manifest_is_exposed_by_registry_api(client):
    response = client.get("/node-definitions")
    assert response.status_code == 200
    definition = next(item for item in response.json() if item["type_key"] == "motion.control_video")
    assert definition["contract_version"] == 1
    assert definition["definition_digest"].startswith("sha256:")
    assert definition["ports"]["inputs"][0]["type"] == "data.motion_track.v1"


def test_motion_control_config_defaults_validation_and_cache_hash_are_normalized():
    definition = node_registry.get("motion.control_video", 1)
    assert definition is not None
    defaults = node_registry.resolve_config(definition, {})
    assert defaults == {
        "width": 720,
        "output_fps": 24,
        "theme": "dark",
        "draw_pose": True,
        "draw_face": True,
        "draw_hands": True,
        "line_width": 5,
        "point_radius": 4,
    }
    with pytest.raises(ValueError, match="must be one of"):
        node_registry.resolve_config(definition, {"width": 800})
    with pytest.raises(ValueError, match="at least"):
        node_registry.resolve_config(definition, {"line_width": 1})
    base = ExperimentRunRequest(
        canvas_id="canvas_1",
        node_id="control_1",
        node_key="motion.control_video",
        prompt="",
        model_alias="local.motion-control-video",
        parameters={},
        inputs=[{"type": "MotionTrack", "artifact_ids": ["motion_1"]}],
    )
    explicit = base.model_copy(update={"parameters": defaults})
    model_alias, exact_model_id = resolve_model(base.model_alias, base.node_key)
    assert model_alias == "local.motion-control-video"
    assert exact_model_id == "motion-control-video.v1"
    with pytest.raises(ValueError, match="requires model alias"):
        resolve_model("local.wrong", base.node_key)
    assert request_fingerprint(base, model_alias, exact_model_id) == request_fingerprint(explicit, model_alias, exact_model_id)


def test_motion_control_renderer_creates_playable_mp4():
    rendered = render_motion_control_video(
        motion_track_fixture(),
        width=90,
        output_fps=24,
        theme="dark",
        draw_pose=True,
        draw_face=True,
        draw_hands=True,
        line_width=3,
        point_radius=2,
    )
    assert rendered.width == 90
    assert rendered.height == 160
    assert rendered.frame_count == 6
    assert rendered.data[4:8] == b"ftyp"
    assert len(rendered.data) > 1000


def test_motion_control_executor_records_artifact_contract_and_lineage(monkeypatch):
    definition = node_registry.get("motion.control_video", 1)
    assert definition is not None
    source = SimpleNamespace(id="motion_1", type="MotionTrack", uri="s3://bucket/motion.json", metadata_json={})
    output = SimpleNamespace(id="video_1", type="Video")
    captured = {}

    class FakeDb:
        def get(self, _, artifact_id):
            return source if artifact_id == source.id else output if artifact_id == output.id else None

        def flush(self):
            captured["flushed"] = True

    class FakeStorage:
        def get_bytes(self, **_):
            return json.dumps(motion_track_fixture()).encode()

    monkeypatch.setattr(motion_control_module, "get_storage", lambda: FakeStorage())
    monkeypatch.setattr(motion_control_module, "storage_location", lambda *_: ("bucket", "motion.json"))
    monkeypatch.setattr(motion_control_module, "render_motion_control_video", lambda *args, **kwargs: RenderedMotionControlVideo(
        data=b"video", width=720, height=1280, fps=24, duration_ms=250, frame_count=6,
    ))

    def fake_create_artifact(db, artifact_type, **kwargs):
        captured.update({"artifact_type": artifact_type, **kwargs})
        return output

    monkeypatch.setattr(motion_control_module, "create_artifact", fake_create_artifact)
    monkeypatch.setattr(motion_control_module, "artifact_content_url", lambda artifact_id: f"http://api/artifacts/{artifact_id}/content")
    payload = ExperimentRunRequest(
        canvas_id="canvas_1",
        node_id="control_1",
        node_key="motion.control_video",
        prompt="",
        model_alias="local.motion-control-video",
        parameters={},
        inputs=[],
    )
    context = NodeExecutionContext(
        db=FakeDb(),
        payload=payload,
        definition=definition,
        request_hash="abcd1234",
        experiment_id="experiment_1",
    )
    result = MotionControlVideoExecutor().execute(
        context,
        node_registry.resolve_config(definition, {}),
        [{"type": "MotionTrack", "artifact_ids": [source.id]}],
    )
    assert result.output_artifact_ids == ["video_1"]
    assert result.output["url"].endswith("/video_1/content")
    assert result.metadata["schema_id"] == "motion.control_video.v1"
    assert captured["artifact_type"] == "Video"
    assert captured["schema_id"] == "motion.control_video.v1"
    assert captured["input_artifact_ids"] == ["motion_1"]
    assert captured["input_artifact_roles"] == {"motion_1": "motion_track"}
    assert captured["metadata"]["experiment_id"] == "experiment_1"
    assert captured["flushed"] is True


def test_motion_control_rejects_missing_or_invalid_motion_track():
    definition = node_registry.get("motion.control_video", 1)
    assert definition is not None
    payload = ExperimentRunRequest(
        canvas_id="canvas_1",
        node_id="control_1",
        node_key="motion.control_video",
        prompt="",
        model_alias="local.motion-control-video",
        parameters={},
        inputs=[],
    )
    context = NodeExecutionContext(
        db=SimpleNamespace(get=lambda *_: None),
        payload=payload,
        definition=definition,
        request_hash="digest",
        experiment_id="experiment_1",
    )
    with pytest.raises(ValueError, match="connected MotionTrack"):
        MotionControlVideoExecutor().execute(context, node_registry.resolve_config(definition, {}), [])
    with pytest.raises(ValueError, match="valid JSON"):
        parse_motion_track(b"not-json")
    with pytest.raises(ValueError, match="motion.track.v1"):
        parse_motion_track(b'{"schema_version":"motion.track.v2"}')


def test_temporal_canvas_activity_uses_the_same_canvas_node_dispatch(monkeypatch):
    calls = []
    monkeypatch.setattr(canvas_activities, "refresh_provider_environment", lambda: None)
    monkeypatch.setattr(canvas_activities, "execute_canvas_node", lambda run_id, node_id: calls.append((run_id, node_id)) or {"artifact_ids": ["video_1"]})
    monkeypatch.setattr(canvas_activities.activity, "heartbeat", lambda *_: None)
    result = asyncio.run(canvas_activities.execute_canvas_node_activity("run_1", "control_1"))
    assert result == {"artifact_ids": ["video_1"]}
    assert calls == [("run_1", "control_1")]
