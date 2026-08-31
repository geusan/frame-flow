from __future__ import annotations

import asyncio
import json
import re
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import canvas_activities
from app.domain import ExperimentRunRequest
from app.experiments import request_fingerprint, resolve_model
from app.motion_control_video import MOTION_CONTROL_VIDEO_REVISION, RenderedMotionControlVideo, parse_motion_track, render_motion_control_video
from app.motion_segmentation import MOTION_SEGMENT_REVISION, segment_motion_track
from app.nodes import node_registry
from app.nodes.contracts import NodeDefinition, NodeExecutionContext
from app.nodes.editor_refs import node_editor_ref_registry
from app.nodes.inventory import canvas_only_keys, load_node_inventory, production_node_keys
from app.nodes.port_types import port_type_registry
from app.nodes.registry import NodeRegistry
from app.nodes.executors import lora_train as lora_train_module
from app.nodes.executors.lora_train import FalLoraTrainingExecutor
from app.nodes.executors import motion_control_video as motion_control_module
from app.nodes.executors.motion_control_video import MotionControlVideoExecutor
from app.video_retime import VIDEO_RETIME_REVISION, retime_video


def test_node_inventory_characterizes_every_canvas_key_and_registry_definition():
    inventory = load_node_inventory()
    production = production_node_keys()
    canvas_only = canvas_only_keys()
    assert inventory["schema_version"] == "node.inventory.v1"
    assert not production & canvas_only

    canvas_model = Path(__file__).parents[2] / "web/src/lib/canvas-model.ts"
    template_keys = re.findall(r'key: "([a-z][a-z0-9_.-]+)"', canvas_model.read_text())
    counts = Counter(template_keys)
    registry_only = {definition.type_key for definition in node_registry.list() if definition.editor.kind == "generic"}
    assert set(template_keys) == (production - registry_only) | canvas_only
    assert inventory["library_duplicates"] == {
        key: count for key, count in sorted(counts.items()) if count > 1
    }

    registered = {definition.type_key for definition in node_registry.list()}
    assert registered <= production
    assert {"lora.train", "motion.control_video", "motion.segment", "video.retime"} <= registered


def test_node_inventory_lifecycle_groups_only_reference_production_nodes():
    inventory = load_node_inventory()
    production = production_node_keys()
    assert set(inventory["legacy_pipeline"]) <= production
    assert set(inventory["production_nodes"]) == {"source", "provider", "local", "human_gate", "composite"}


def test_every_production_node_has_a_v1_manifest_and_canvas_only_elements_do_not():
    inventory = load_node_inventory()
    registered = {definition.type_key for definition in node_registry.list()}
    assert registered == production_node_keys()
    assert not registered & canvas_only_keys()
    assert all(node_registry.get(type_key, 1) is not None for type_key in production_node_keys())
    assert {definition.type_key for definition in node_registry.list(lifecycle="DEPRECATED")} == set(inventory["legacy_pipeline"])
    assert all(definition.editor.kind == "legacy" for definition in node_registry.list(lifecycle="DEPRECATED"))


def test_text_generation_v2_adds_xai_without_mutating_v1_contracts():
    for type_key in ("llm.assistant", "skill.execute", "script.generate"):
        v1 = node_registry.get(type_key, 1)
        v2 = node_registry.get(type_key, 2)
        assert v1 is not None and v2 is not None
        assert "xai.text." not in v1.execution.model_families
        assert "xai.text." in v2.execution.model_families
        assert v1.ports == v2.ports
        assert v1.config_schema == v2.config_schema
    v1_payload = ExperimentRunRequest(
        canvas_id="canvas_1",
        node_id="assistant_1",
        node_key="llm.assistant",
        node_contract_version=1,
        prompt="Summarize this",
        model_alias="google.text.quality",
        parameters={},
        inputs=[],
    )
    v2_payload = v1_payload.model_copy(update={"node_contract_version": 2})
    model_alias, exact_model_id = resolve_model(v1_payload.model_alias, v1_payload.node_key, 1)
    assert request_fingerprint(v1_payload, model_alias, exact_model_id) != request_fingerprint(v2_payload, model_alias, exact_model_id)


def test_every_node_manifest_materializes_a_closed_config():
    for definition in node_registry.list():
        resolved = node_registry.resolve_config(definition, {})
        assert set(resolved) <= set(definition.config_schema["properties"])
        assert set(definition.config_schema.get("required", [])) <= set(resolved)


def test_all_node_definition_digests_match_the_v1_golden_snapshot():
    fixture = Path(__file__).parent / "fixtures/node_definition_digests.v1.json"
    expected = json.loads(fixture.read_text())
    actual = {
        f"{definition.type_key}@{definition.contract_version}": definition.definition_digest
        for definition in node_registry.list()
    }
    assert actual == expected


def test_custom_editor_contract_requires_a_registered_ref(tmp_path):
    source = node_registry.get("image.generate", 1)
    assert source is not None
    payload = source.model_dump(mode="json")
    payload["editor"] = {"kind": "custom", "ref": "provider-generation"}
    definition = NodeDefinition.model_validate(payload)
    assert definition.editor.ref == "provider-generation"
    assert node_editor_ref_registry.contains("provider-generation")
    assert definition.public_payload()["editor"] == {"kind": "custom", "ref": "provider-generation"}

    payload["editor"] = {"kind": "custom"}
    with pytest.raises(ValueError, match="custom editor requires ref"):
        NodeDefinition.model_validate(payload)

    payload["editor"] = {"kind": "generic", "ref": "provider-generation"}
    with pytest.raises(ValueError, match="generic editor cannot declare ref"):
        NodeDefinition.model_validate(payload)

    payload["editor"] = {"kind": "custom", "ref": "missing-editor"}
    (tmp_path / "custom.json").write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="unregistered Node editor ref: missing-editor"):
        NodeRegistry(definitions_dir=tmp_path, executors={"legacy-compatibility": object()})
    payload["editor"]["ref"] = "provider-generation"
    (tmp_path / "custom.json").write_text(json.dumps(payload))
    assert NodeRegistry(definitions_dir=tmp_path, executors={"legacy-compatibility": object()}).get("image.generate", 1) is not None


def test_legacy_editor_payload_and_digest_remain_backward_compatible():
    definition = node_registry.get("image.generate", 1)
    assert definition is not None
    assert definition.editor.kind == "legacy"
    assert definition.editor.ref is None
    assert definition.public_payload()["editor"] == {"kind": "legacy"}


def test_node_definition_api_exposes_active_contracts_only(client):
    response = client.get("/node-definitions")
    assert response.status_code == 200
    payload = response.json()
    assert {item["type_key"] for item in payload} == {
        definition.type_key for definition in node_registry.list(lifecycle="ACTIVE")
    }
    assert not {item["type_key"] for item in payload} & set(load_node_inventory()["legacy_pipeline"])


def test_port_type_registry_covers_legacy_canvas_contracts():
    assert len(port_type_registry.ids) == 26
    assert port_type_registry.compatible("media.video.v1", "media.video.v1") is True
    assert port_type_registry.compatible("media.video.v1", "media.image.v1") is False
    assert port_type_registry.get("data.motion_track.v1").legacy_type == "MotionTrack"
    assert port_type_registry.get("data.timeline.v1").legacy_type == "Timeline"
    assert port_type_registry.get("data.reference_asset.v1").legacy_type == "ReferenceAsset"


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
    with pytest.raises(ValueError, match="unknown config fields"):
        node_registry.resolve_config(definition, {"trigger_word": "mori", "legacy_extra": "nope"})


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


def test_motion_segment_and_video_retime_manifests_are_registered():
    segment = node_registry.get("motion.segment", 1)
    retime = node_registry.get("video.retime", 1)
    assert segment is not None and retime is not None
    assert segment.execution.revision == MOTION_SEGMENT_REVISION
    assert segment.ports.inputs[0].type == "data.motion_track.v1"
    assert segment.ports.outputs[0].type == "data.motion_track.v1"
    assert segment.artifact_contract.schema_id == "motion.track.segment.v1"
    assert node_registry.resolve_config(segment, {}) == {
        "start_seconds": 0,
        "duration_seconds": 5,
        "time_scale": 2,
    }
    assert retime.execution.revision == VIDEO_RETIME_REVISION
    assert retime.ports.inputs[0].type == "media.video.v1"
    assert retime.ports.outputs[0].type == "media.video.v1"
    assert retime.artifact_contract.schema_id == "video.retime.v1"
    assert node_registry.resolve_config(retime, {}) == {
        "speed_multiplier": 2,
        "output_fps": 24,
        "preserve_audio": False,
    }


def test_motion_segment_rebases_and_scales_timestamps():
    source = motion_track_fixture()
    segmented = segment_motion_track(
        source,
        start_seconds=0,
        duration_seconds=0.25,
        time_scale=2,
    )
    assert segmented["schema_version"] == "motion.track.v1"
    assert segmented["source"]["duration_ms"] == 500
    assert segmented["source"]["sample_fps"] == 2
    assert segmented["frames"][0]["timestamp_ms"] == 0
    assert segmented["frames"][-1]["timestamp_ms"] == 500
    assert segmented["summary"]["frame_count"] == len(segmented["frames"])
    with pytest.raises(ValueError, match="before the MotionTrack duration"):
        segment_motion_track(source, start_seconds=1, duration_seconds=1, time_scale=2)


def test_video_retime_changes_duration_and_keeps_video_contract():
    source = render_motion_control_video(
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
    retimed = retime_video(
        source.data,
        "video/mp4",
        speed_multiplier=2,
        output_fps=24,
        preserve_audio=False,
    )
    assert retimed.width == 90
    assert retimed.height == 160
    assert retimed.fps == 24
    assert retimed.has_audio is False
    assert retimed.duration_ms < retimed.source_duration_ms
    assert retimed.data[4:8] == b"ftyp"


def test_temporal_canvas_activity_uses_the_same_canvas_node_dispatch(monkeypatch):
    calls = []
    monkeypatch.setattr(canvas_activities, "refresh_provider_environment", lambda: None)
    monkeypatch.setattr(canvas_activities, "execute_canvas_node", lambda run_id, node_id: calls.append((run_id, node_id)) or {"artifact_ids": ["video_1"]})
    monkeypatch.setattr(canvas_activities.activity, "heartbeat", lambda *_: None)
    result = asyncio.run(canvas_activities.execute_canvas_node_activity("run_1", "control_1"))
    assert result == {"artifact_ids": ["video_1"]}
    assert calls == [("run_1", "control_1")]
