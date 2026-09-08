from __future__ import annotations

import base64
import copy
import json
import struct
import zlib
from pathlib import Path

import jsonschema
import pytest

from app.character_motion import blender as blender_module
from app.character_motion.blender import HttpBlenderExecutionProvider
from app.character_motion.bone_maps import resolve_bone_map
from app.character_motion.canonical_motion import (
    BONE_NAMES,
    canonical_motion_bytes,
    quaternion_dot,
    validate_canonical_motion,
)
from app.character_motion.cleanup import cleanup_motion
from app.character_motion.mediapipe_adapter import MediaPipeMotionAdapter
from app.character_motion.providers import AutoRigResult, ImageTo3DResult
from app.character_motion.tripo import TripoProviderError
from app.character_motion.validation import inspect_glb, parse_glb
from app.database import ExperimentRunRecord, SessionLocal
from app.experiments import request_fingerprint, resolve_model
from app.domain import ExperimentRunRequest
from app.infrastructure.node_execution.character_motion_runtime import (
    SqlAlchemyNodeCharacterMotionRuntime,
)
from app.media_preview import render_video_mp4
from app.nodes import node_registry
from app.nodes.executors import character_motion as character_motion_executor
from app.nodes.port_types import port_type_registry
from app.service import create_artifact


ROOT = Path(__file__).parents[3]


def minimal_glb(*, rigged: bool = True, bone_names: list[str] | None = None) -> bytes:
    selected_bones = bone_names or list(BONE_NAMES)
    document = {
        "asset": {"version": "2.0", "generator": "Frameflow test"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [
            {"name": "Fixture", "mesh": 0, **({"skin": 0} if rigged else {})},
            *([{"name": name, **({"children": [index + 2]} if index + 1 < len(selected_bones) else {})} for index, name in enumerate(selected_bones)] if rigged else []),
        ],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "material": 0}]}],
        "accessors": [{"componentType": 5126, "count": 24, "type": "VEC3", "min": [-0.5, 0.0, -0.3], "max": [0.5, 1.8, 0.3]}],
        "materials": [{"name": "Fixture"}],
        **({"skins": [{"joints": list(range(1, len(selected_bones) + 1)), "skeleton": 1}]} if rigged else {}),
    }
    body = json.dumps(document, separators=(",", ":")).encode()
    body += b" " * ((4 - len(body) % 4) % 4)
    return struct.pack("<4sII", b"glTF", 2, 12 + 8 + len(body)) + struct.pack("<II", len(body), 0x4E4F534A) + body


def png_bytes(width: int = 512, height: int = 512) -> bytes:
    def chunk(name: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + name + data + struct.pack(">I", zlib.crc32(name + data) & 0xFFFFFFFF)

    rows = b"".join(b"\x00" + b"\x7f\x9f\xdf" * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows, 9))
        + chunk(b"IEND", b"")
    )


def known_motion() -> dict:
    return json.loads((ROOT / "examples/3d-character-dance/known-motion.json").read_text())


def mediapipe_track_fixture() -> dict:
    pose = [{"x": 0.0, "y": 0.0, "z": 0.0, "visibility": 1.0, "presence": 1.0} for _ in range(33)]
    coordinates = {
        0: (0.0, -1.86, 0.0), 7: (0.08, -1.72, 0.0), 8: (-0.08, -1.72, 0.0),
        11: (0.28, -1.5, 0.0), 12: (-0.28, -1.5, 0.0),
        13: (0.6, -1.45, 0.0), 14: (-0.6, -1.45, 0.0),
        15: (0.9, -1.4, 0.0), 16: (-0.9, -1.4, 0.0),
        17: (1.0, -1.4, 0.0), 18: (-1.0, -1.4, 0.0), 19: (1.0, -1.42, 0.0), 20: (-1.0, -1.42, 0.0),
        23: (0.14, -0.92, 0.0), 24: (-0.14, -0.92, 0.0),
        25: (0.14, -0.52, 0.0), 26: (-0.14, -0.52, 0.0),
        27: (0.14, -0.12, 0.0), 28: (-0.14, -0.12, 0.0),
        31: (0.14, -0.05, -0.2), 32: (-0.14, -0.05, -0.2),
    }
    for index, (x, y, z) in coordinates.items():
        pose[index].update({"x": x, "y": y, "z": z})
    frames = []
    for timestamp in (0, 125, 250):
        shifted = copy.deepcopy(pose)
        for index in (11, 13, 15, 17, 19):
            shifted[index]["y"] -= timestamp / 1000 * 0.2
        frames.append({
            "timestamp_ms": timestamp,
            "pose_world_landmarks": shifted,
            "pose_landmarks": shifted,
            "left_hand_landmarks": [], "left_hand_world_landmarks": [],
            "right_hand_landmarks": [], "right_hand_world_landmarks": [],
            "face_blendshapes": [], "channels": {},
        })
    return {
        "schema_version": "motion.track.v1",
        "extractor": {"name": "fixture", "revision": "fixture.v1"},
        "source": {"sample_fps": 8, "duration_ms": 250},
        "summary": {"coverage": {"pose": 1.0}},
        "frames": frames,
    }


def test_new_node_contracts_are_registered_with_versioned_ports():
    expected = {
        "character.reference.validate": ("media.image.v1", "artifact.character_reference.v1"),
        "character.image_to_3d": ("artifact.character_reference.v1", "model.character_3d.v1"),
        "character.model.validate": ("model.character_3d.v1", "model.character_3d_validated.v1"),
        "character.auto_rig": ("model.character_3d_validated.v1", "model.character_rigged.v1"),
        "motion.video.validate": ("media.video.v1", "media.motion_source_video.v1"),
        "motion.humanoid.extract": ("media.motion_source_video.v1", "data.humanoid_motion_raw.v1"),
        "motion.humanoid.cleanup": ("data.humanoid_motion_raw.v1", "data.humanoid_motion_clean.v1"),
        "motion.humanoid.retarget": ("model.character_rigged.v1", "model.character_animated.v1"),
        "video.blender_render": ("model.character_animated.v1", "media.video.v1"),
    }
    for type_key, (input_type, output_type) in expected.items():
        definition = node_registry.get(type_key, 1)
        assert definition is not None
        assert definition.lifecycle == "ACTIVE"
        assert definition.editor.kind == "generic"
        assert definition.ports.inputs[0].type == input_type
        assert definition.ports.outputs[0].type == output_type
        assert node_registry.resolve_config(definition, {})


def test_tripo_contracts_add_multiview_and_new_versions_without_mutating_v1():
    reference = node_registry.get("character.reference.multiview", 1)
    image_v1 = node_registry.get("character.image_to_3d", 1)
    image_v2 = node_registry.get("character.image_to_3d", 2)
    rig_v1 = node_registry.get("character.auto_rig", 1)
    rig_v2 = node_registry.get("character.auto_rig", 2)
    assert all((reference, image_v1, image_v2, rig_v1, rig_v2))
    assert reference.ports.inputs[0].type == "artifact.character.v1"
    assert reference.ports.outputs[0].type == "artifact.character_reference_set.v1"
    assert image_v1.config_schema["properties"]["provider"]["enum"] == ["manual"]
    assert image_v2.execution.provider == "tripo"
    assert image_v2.ports.inputs[0].type == "artifact.character_reference_set.v1"
    assert image_v2.config_schema["properties"]["model_alias"]["default"] == "tripo.3d.p1"
    assert rig_v1.config_schema["properties"]["provider"]["enum"] == ["passthrough", "manual"]
    assert rig_v2.execution.provider == "tripo"
    assert rig_v2.config_schema["properties"]["rig_profile"]["default"] == "mixamo"


def test_unknown_tripo_submission_outcome_blocks_automatic_resubmission(client):
    del client
    request_hash = "f" * 64
    with SessionLocal() as db:
        prior = ExperimentRunRecord(
            id="exp_tripo_pending_prior",
            canvas_id="canvas_tripo",
            node_id="image-to-3d",
            node_key="character.image_to_3d",
            status="FAILED",
            execution_mode="tripo-multiview-image-to-3d.v1",
            prompt="",
            model_alias="tripo.3d.p1",
            exact_model_id="P1-20260311",
            parameters={},
            input_snapshot=[],
            request_hash=request_hash,
            provider_request_id="tripo:generate:pending",
        )
        current = ExperimentRunRecord(
            id="exp_tripo_pending_current",
            canvas_id="canvas_tripo",
            node_id="image-to-3d",
            node_key="character.image_to_3d",
            status="RUNNING",
            execution_mode="tripo-multiview-image-to-3d.v1",
            prompt="",
            model_alias="tripo.3d.p1",
            exact_model_id="P1-20260311",
            parameters={},
            input_snapshot=[],
            request_hash=request_hash,
        )
        db.add_all([prior, current])
        db.commit()
        runtime = SqlAlchemyNodeCharacterMotionRuntime(db)
        context = type("Context", (), {
            "request_hash": request_hash,
            "experiment_id": current.id,
            "require_character_motion_runtime": lambda self: runtime,
        })()
        with pytest.raises(TripoProviderError, match="Automatic resubmission is blocked") as error:
            character_motion_executor._resume_tripo_task(context, {"generate"})
        assert error.value.retryable is False


def test_identical_tripo_submission_claim_blocks_second_billable_post(client):
    del client
    request_hash = "e" * 64
    with SessionLocal() as db:
        records = []
        for suffix in ("first", "second"):
            records.append(ExperimentRunRecord(
                id=f"exp_tripo_claim_{suffix}",
                canvas_id="canvas_tripo",
                node_id=f"image-to-3d-{suffix}",
                node_key="character.image_to_3d",
                status="RUNNING",
                execution_mode="tripo-multiview-image-to-3d.v1",
                prompt="",
                model_alias="tripo.3d.p1",
                exact_model_id="P1-20260311",
                parameters={},
                input_snapshot=[],
                request_hash=request_hash,
            ))
        db.add_all(records)
        db.commit()
        runtime = SqlAlchemyNodeCharacterMotionRuntime(db)
        first = type("Context", (), {
            "request_hash": request_hash,
            "experiment_id": records[0].id,
            "require_character_motion_runtime": lambda self: runtime,
        })()
        second = type("Context", (), {
            "request_hash": request_hash,
            "experiment_id": records[1].id,
            "require_character_motion_runtime": lambda self: runtime,
        })()

        character_motion_executor._remember_tripo_task(first, "generate", "pending")
        with pytest.raises(TripoProviderError, match="second billable request was blocked") as error:
            character_motion_executor._remember_tripo_task(second, "generate", "pending")

        assert error.value.retryable is False
        character_motion_executor._remember_tripo_task(second, "rig", "pending")
        db.refresh(records[0])
        db.refresh(records[1])
        assert records[0].provider_request_id == "tripo:generate:pending"
        assert records[1].provider_request_id == "tripo:rig:pending"


def test_uploaded_model_port_is_explicitly_compatible_with_character_3d():
    assert port_type_registry.compatible("model.source_3d.v1", "model.character_3d.v1") is True
    assert port_type_registry.compatible("model.character_3d.v1", "model.character_rigged.v1") is False


def test_canonical_motion_matches_schema_and_rejects_invalid_time():
    motion = known_motion()
    validate_canonical_motion(motion)
    schema = json.loads((ROOT / "packages/schemas/humanoid.motion.v1.schema.json").read_text())
    jsonschema.Draft202012Validator(schema).validate(motion)
    broken = copy.deepcopy(motion)
    broken["frames"][1]["time"] = 0
    try:
        validate_canonical_motion(broken)
    except ValueError as exc:
        assert "strictly increasing" in str(exc)
    else:
        raise AssertionError("invalid frame timing was accepted")


def test_mediapipe_adapter_outputs_parent_space_quaternions_not_landmarks():
    motion = MediaPipeMotionAdapter().convert(mediapipe_track_fixture(), source_artifact_id="video_1")
    assert motion["schema_version"] == "humanoid.motion.v1"
    assert motion["skeleton"]["rotation_space"] == "parent"
    assert motion["source"]["source_artifact_id"] == "video_1"
    assert len(motion["frames"]) == 3
    assert set(motion["frames"][0]["bones"]) == set(BONE_NAMES)
    assert "pose_world_landmarks" not in json.dumps(motion)
    assert abs(quaternion_dot(motion["frames"][0]["bones"]["leftUpperArm"]["rotation"], [0, 0, 0, 1])) > 0.5


def test_motion_cleanup_is_deterministic_and_interpolates_invalid_frames():
    motion = known_motion()
    motion["frames"][4]["valid"] = False
    motion["frames"][4]["root"]["confidence"] = 0.1
    motion["frames"][4]["bones"]["leftUpperArm"]["confidence"] = 0.1
    options = dict(
        smoothing=0.25, confidence_threshold=0.5, invalid_frame_policy="interpolate",
        joint_limits=True, root_stabilization=True, foot_lock=True,
    )
    first = cleanup_motion(motion, **options)
    second = cleanup_motion(motion, **options)
    assert canonical_motion_bytes(first) == canonical_motion_bytes(second)
    assert first["frames"][4]["valid"] is True
    assert first["metadata"]["cleanup"]["repaired_frame_count"] == 1
    assert first["source"]["provider"] == "frameflow-cleanup"


def test_bone_map_profiles_are_separate_from_motion_and_require_core_bones():
    semantic = resolve_bone_map("semantic")
    mixamo = resolve_bone_map("mixamo")
    assert semantic["leftUpperArm"] == "leftUpperArm"
    assert mixamo["leftUpperArm"] == "mixamorig:LeftArm"
    assert "mixamorig" not in json.dumps(known_motion())


def test_glb_parser_surfaces_mesh_rig_bounds_and_missing_rig():
    rigged = minimal_glb(rigged=True)
    assert parse_glb(rigged)["asset"]["version"] == "2.0"
    report = inspect_glb(rigged)
    assert report["valid"] is True
    assert report["metadata"]["vertex_count"] == 24
    assert report["metadata"]["skeleton_exists"] is True
    assert report["metadata"]["humanoid_proportions"] is True
    unrigged = inspect_glb(minimal_glb(rigged=False))
    assert unrigged["metadata"]["skeleton_exists"] is False
    assert "No humanoid skeleton found." in unrigged["warnings"]


def test_http_blender_provider_uses_structured_payload_and_decodes_render(monkeypatch):
    captured = {}

    class Response:
        status_code = 200
        text = ""

        @staticmethod
        def json():
            return {
                "video": base64.b64encode(b"encoded-mp4").decode("ascii"),
                "metadata": {"frame_count": 3},
                "logs": ["rendered"],
            }

    def fake_post(url, *, json, timeout):
        captured.update({"url": url, "json": json, "timeout": timeout})
        return Response()

    monkeypatch.setattr(blender_module.httpx, "post", fake_post)
    progress = []
    result = HttpBlenderExecutionProvider("http://blender-worker:8090/").render(
        b"blend-bytes",
        width=360,
        height=640,
        fps=24,
        render_style="toon",
        camera_preset="full_body",
        background="#181A20",
        samples=8,
        quality="preview",
        timeout_seconds=90,
        progress=lambda value, message: progress.append((value, message)),
    )
    assert captured["url"] == "http://blender-worker:8090/render"
    assert base64.b64decode(captured["json"]["animation_blend"]) == b"blend-bytes"
    assert captured["json"]["config"]["render_style"] == "toon"
    assert result.video == b"encoded-mp4"
    assert result.metadata == {"frame_count": 3}
    assert result.logs == ["rendered"]
    assert progress[0][0] == 15 and progress[-1][0] == 92


def test_http_blender_provider_surfaces_worker_error(monkeypatch):
    class Response:
        status_code = 422
        text = ""

        @staticmethod
        def json():
            return {"error": "Missing required bone mapping: leftUpperArm"}

    monkeypatch.setattr(blender_module.httpx, "post", lambda *args, **kwargs: Response())
    provider = HttpBlenderExecutionProvider("http://blender-worker:8090")
    with pytest.raises(RuntimeError, match="Missing required bone mapping: leftUpperArm"):
        provider.render(
            b"blend-bytes",
            width=360,
            height=640,
            fps=24,
            render_style="toon",
            camera_preset="full_body",
            background="#181A20",
            samples=8,
            quality="preview",
            timeout_seconds=90,
        )


def test_cache_key_changes_with_cleanup_settings_and_reuses_materialized_defaults():
    definition = node_registry.get("motion.humanoid.cleanup", 1)
    defaults = node_registry.resolve_config(definition, {})
    base = ExperimentRunRequest(
        canvas_id="canvas_1", node_id="cleanup_1", node_key=definition.type_key,
        model_alias=definition.execution.model_alias, parameters={},
        inputs=[{"type": "MotionRaw", "artifact_ids": ["motion_1"]}],
    )
    model_alias, exact_model = resolve_model(base.model_alias, base.node_key)
    explicit = base.model_copy(update={"parameters": defaults})
    changed = base.model_copy(update={"parameters": {**defaults, "smoothing": 0.5}})
    assert request_fingerprint(base, model_alias, exact_model) == request_fingerprint(explicit, model_alias, exact_model)
    assert request_fingerprint(base, model_alias, exact_model) != request_fingerprint(changed, model_alias, exact_model)


def test_glb_upload_uses_existing_artifact_api(client):
    response = client.post(
        "/artifacts/upload",
        files={"file": ("fixture.glb", minimal_glb(), "model/gltf-binary")},
    )
    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["type"] == "Model3D"
    detail = client.get(f"/artifacts/{payload['artifact_id']}")
    assert detail.status_code == 200
    assert detail.json()["sha256"]
    assert detail.json()["metadata"]["validation"]["metadata"]["skeleton_exists"] is True


def test_manual_character_pipeline_executes_through_registry_and_preserves_lineage(client):
    image = client.post(
        "/artifacts/upload",
        files={"file": ("character.png", png_bytes(), "image/png")},
    ).json()
    model = client.post(
        "/artifacts/upload",
        files={"file": ("character.glb", minimal_glb(), "model/gltf-binary")},
    ).json()

    reference = client.post("/experiments", json={
        "canvas_id": "character_pipeline", "node_id": "reference",
        "node_key": "character.reference.validate", "model_alias": "local.character-reference-validation",
        "parameters": {"character_name": "Fixture"},
        "inputs": [{"type": "Image", "artifact_ids": [image["artifact_id"]]}],
    })
    assert reference.status_code == 201, reference.text
    assert reference.json()["status"] == "SUCCEEDED"

    generated = client.post("/experiments", json={
        "canvas_id": "character_pipeline", "node_id": "image_to_3d",
        "node_key": "character.image_to_3d", "model_alias": "local.image-to-3d-manual",
        "parameters": {"manual_3d_artifact_id": model["artifact_id"]},
        "inputs": [{"type": "CharacterReference", "artifact_ids": reference.json()["output_artifact_ids"]}],
    })
    assert generated.status_code == 201, generated.text
    assert generated.json()["status"] == "SUCCEEDED"

    validated = client.post("/experiments", json={
        "canvas_id": "character_pipeline", "node_id": "validation",
        "node_key": "character.model.validate", "model_alias": "local.character-3d-validation",
        "parameters": {},
        "inputs": [{"type": "Character3D", "artifact_ids": generated.json()["output_artifact_ids"]}],
    })
    assert validated.status_code == 201, validated.text
    assert validated.json()["status"] == "SUCCEEDED"

    rigged = client.post("/experiments", json={
        "canvas_id": "character_pipeline", "node_id": "rig",
        "node_key": "character.auto_rig", "model_alias": "local.character-auto-rig",
        "parameters": {},
        "inputs": [{"type": "Character3DValidated", "artifact_ids": validated.json()["output_artifact_ids"]}],
    })
    assert rigged.status_code == 201, rigged.text
    assert rigged.json()["status"] == "SUCCEEDED"
    rigged_artifact = client.get(f"/artifacts/{rigged.json()['output_artifact_ids'][0]}").json()
    assert rigged_artifact["type"] == "CharacterRigged"
    assert rigged_artifact["schema_id"] == "character.rigged.glb.v1"
    assert rigged_artifact["input_artifact_ids"][0] == validated.json()["output_artifact_ids"][0]


def test_tripo_multiview_and_rig_contracts_execute_with_provider_adapters(client, monkeypatch):
    roles = ["front_full", "profile", "back_three_quarter", "three_quarter_full"]
    image_ids = []
    for role in roles:
        uploaded = client.post(
            "/artifacts/upload",
            files={"file": (f"{role}.png", png_bytes(), "image/png")},
        )
        assert uploaded.status_code == 201, uploaded.text
        image_ids.append(uploaded.json()["artifact_id"])
    with SessionLocal() as db:
        character = create_artifact(
            db,
            "Character",
            schema_id="character.bundle.v1",
            input_artifact_ids=image_ids,
            input_artifact_roles={artifact_id: "character_view" for artifact_id in image_ids},
            metadata={
                "name": "Tripo Fixture",
                "image_artifact_ids": image_ids,
                "image_roles": roles,
                "cover_artifact_id": image_ids[0],
            },
            content=json.dumps({"schema_version": "character.bundle.v1"}).encode(),
            content_type="application/json",
            filename="character.json",
        )
        db.commit()
        character_id = character.id

    reference = client.post("/experiments", json={
        "canvas_id": "tripo_pipeline",
        "node_id": "reference_set",
        "node_key": "character.reference.multiview",
        "node_contract_version": 1,
        "model_alias": "local.character-reference-set",
        "parameters": {},
        "inputs": [{"type": "Character", "artifact_ids": [character_id]}],
    })
    assert reference.status_code == 201, reference.text
    assert reference.json()["status"] == "SUCCEEDED"
    reference_id = reference.json()["output_artifact_ids"][0]
    reference_detail = client.get(f"/artifacts/{reference_id}").json()
    assert reference_detail["type"] == "CharacterReferenceSet"
    assert [view["provider_role"] for view in reference_detail["metadata"]["views"]] == [
        "front", "left", "back", "right",
    ]
    assert set(reference_detail["input_artifact_ids"]) == {character_id, *image_ids}
    reference_manifest = client.get(f"/artifacts/{reference_id}/content").json()
    reference_schema = json.loads(
        (ROOT / "packages/schemas/character.reference_set.v1.schema.json").read_text()
    )
    jsonschema.Draft202012Validator(reference_schema).validate(reference_manifest)

    class FakeTripoImageProvider:
        name = "tripo"
        revision = "tripo-fixture.v1"

        @staticmethod
        def generate(input):
            assert [view.role for view in input.views] == ["front", "left", "back", "right"]
            assert input.model_id == "P1-20260311"
            assert input.face_limit == 20_000
            input.task_callback("generate", "task_generate_fixture")
            input.progress_callback(80, "Tripo multiview generation: running 80%")
            return ImageTo3DResult(
                glb=minimal_glb(rigged=False),
                provider="tripo",
                provider_revision="tripo-fixture.v1",
                provider_request_id="tripo:generate:task_generate_fixture",
                metadata={"task_id": "task_generate_fixture", "credits_consumed": 60},
            )

    monkeypatch.setattr(
        character_motion_executor,
        "image_to_3d_provider",
        lambda name: FakeTripoImageProvider() if name == "tripo" else None,
    )
    generated = client.post("/experiments", json={
        "canvas_id": "tripo_pipeline",
        "node_id": "image_to_3d",
        "node_key": "character.image_to_3d",
        "node_contract_version": 2,
        "model_alias": "tripo.3d.p1",
        "parameters": {},
        "inputs": [{"type": "CharacterReferenceSet", "artifact_ids": [reference_id]}],
    })
    assert generated.status_code == 201, generated.text
    assert generated.json()["status"] == "SUCCEEDED"
    assert generated.json()["exact_model_id"] == "P1-20260311"
    assert generated.json()["provider_request_id"] == "tripo:generate:task_generate_fixture"
    generated_id = generated.json()["output_artifact_ids"][0]
    generated_detail = client.get(f"/artifacts/{generated_id}").json()
    assert generated_detail["metadata"]["provider"] == "tripo"
    assert generated_detail["metadata"]["provider_metadata"]["credits_consumed"] == 60
    assert generated_detail["input_artifact_ids"] == [reference_id]

    validated = client.post("/experiments", json={
        "canvas_id": "tripo_pipeline",
        "node_id": "validation",
        "node_key": "character.model.validate",
        "node_contract_version": 1,
        "model_alias": "local.character-3d-validation",
        "parameters": {},
        "inputs": [{"type": "Character3D", "artifact_ids": [generated_id]}],
    })
    assert validated.json()["status"] == "SUCCEEDED"
    validated_id = validated.json()["output_artifact_ids"][0]

    mixamo_bones = list(resolve_bone_map("mixamo").values())

    class FakeTripoRigProvider:
        name = "tripo"
        revision = "tripo-fixture.v1"

        @staticmethod
        def rig(input):
            assert input.model_id == "v1.0-20240301"
            assert input.rig_profile == "mixamo"
            assert input.run_rig_check is True
            input.task_callback("rig_check", "task_check_fixture")
            input.task_callback("rig", "task_rig_fixture")
            input.progress_callback(85, "Tripo auto rig: running 85%")
            return AutoRigResult(
                glb=minimal_glb(rigged=True, bone_names=mixamo_bones),
                provider="tripo",
                provider_revision="tripo-fixture.v1",
                provider_request_id="tripo:rig:task_rig_fixture",
                skeleton_metadata={
                    "rig_profile": "mixamo",
                    "bone_count": len(mixamo_bones),
                    "bone_names": mixamo_bones,
                    "skin_count": 1,
                    "credits_consumed": 30,
                },
            )

    monkeypatch.setattr(
        character_motion_executor,
        "auto_rig_provider",
        lambda name: FakeTripoRigProvider() if name == "tripo" else None,
    )
    rigged = client.post("/experiments", json={
        "canvas_id": "tripo_pipeline",
        "node_id": "auto_rig",
        "node_key": "character.auto_rig",
        "node_contract_version": 2,
        "model_alias": "tripo.rig.biped",
        "parameters": {},
        "inputs": [{"type": "Character3DValidated", "artifact_ids": [validated_id]}],
    })
    assert rigged.status_code == 201, rigged.text
    assert rigged.json()["status"] == "SUCCEEDED"
    assert rigged.json()["exact_model_id"] == "v1.0-20240301"
    assert rigged.json()["provider_request_id"] == "tripo:rig:task_rig_fixture"
    rigged_detail = client.get(f"/artifacts/{rigged.json()['output_artifact_ids'][0]}").json()
    assert rigged_detail["type"] == "CharacterRigged"
    assert rigged_detail["metadata"]["skeleton"]["rig_profile"] == "mixamo"
    assert rigged_detail["input_artifact_ids"] == [validated_id]


def test_example_canvas_loads_and_publishes_with_real_artifact_ids(client):
    model = client.post(
        "/artifacts/upload",
        files={"file": ("fixture.glb", minimal_glb(), "model/gltf-binary")},
    ).json()
    video_bytes = render_video_mp4("a" * 64)
    video_response = client.post(
        "/artifacts/upload",
        files={"file": ("dance.mp4", video_bytes, "video/mp4")},
    )
    assert video_response.status_code == 201, video_response.text
    video = video_response.json()
    template = (ROOT / "examples/3d-character-dance/canvas-request.json").read_text()
    request = json.loads(
        template
        .replace("REPLACE_WITH_RIGGED_GLB_ARTIFACT_ID", model["artifact_id"])
        .replace("REPLACE_WITH_DANCE_VIDEO_ARTIFACT_ID", video["artifact_id"])
    )
    created = client.post("/canvases", json=request)
    assert created.status_code == 201, created.text
    canvas = created.json()
    assert canvas["node_count"] == 10
    workflow = client.post("/workflows", json={
        "name": "3D Character Dance",
        "source_canvas_id": canvas["id"],
    })
    assert workflow.status_code == 201, workflow.text
    published = client.post(
        f"/workflows/{workflow.json()['id']}/publish",
        json={"expected_canvas_revision": canvas["revision"]},
    )
    assert published.status_code == 201, published.text
    assert published.json()["graph"]["schema_version"] == "workflow.graph.v1"
    assert len(published.json()["graph"]["nodes"]) == 10


def test_tripo_example_canvas_loads_with_versioned_provider_contracts(client):
    image_ids = [
        client.post(
            "/artifacts/upload",
            files={"file": (f"view-{index}.png", png_bytes(), "image/png")},
        ).json()["artifact_id"]
        for index in range(4)
    ]
    with SessionLocal() as db:
        character = create_artifact(
            db,
            "Character",
            schema_id="character.bundle.v1",
            input_artifact_ids=image_ids,
            input_artifact_roles={artifact_id: "character_view" for artifact_id in image_ids},
            metadata={
                "name": "Canvas Tripo Fixture",
                "image_artifact_ids": image_ids,
                "image_roles": ["front_full", "profile", "back_three_quarter", "three_quarter_full"],
                "cover_artifact_id": image_ids[0],
            },
            content=b'{"schema_version":"character.bundle.v1"}',
            content_type="application/json",
            filename="character.json",
        )
        db.commit()
        character_id = character.id
    video = client.post(
        "/artifacts/upload",
        files={"file": ("dance.mp4", render_video_mp4("a1b2c3d4e5f6" * 6), "video/mp4")},
    ).json()
    template = (ROOT / "examples/3d-character-dance/canvas-tripo-request.json").read_text()
    request = json.loads(
        template
        .replace("REPLACE_WITH_CHARACTER_ARTIFACT_ID", character_id)
        .replace("REPLACE_WITH_DANCE_VIDEO_ARTIFACT_ID", video["artifact_id"])
    )
    created = client.post("/canvases", json=request)
    assert created.status_code == 201, created.text
    canvas = created.json()
    assert canvas["node_count"] == 11
    by_id = {node["id"]: node["data"] for node in canvas["nodes"]}
    assert by_id["character-reference-set"]["key"] == "character.reference.multiview"
    assert by_id["image-to-3d"]["contractVersion"] == 2
    assert by_id["image-to-3d"]["model"] == "tripo.3d.p1"
    assert by_id["auto-rig"]["contractVersion"] == 2
    assert by_id["retarget"]["config"]["rig_profile"] == "mixamo"
