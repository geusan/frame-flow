from __future__ import annotations

import asyncio
import copy
import json
import struct
import zlib
from pathlib import Path

import httpx
import jsonschema
import pytest

from app import canvas_activities
from app.canvas_documents import canonicalize_canvas_document
from app.canvas_runs import create_canvas_run, execute_canvas_node, canvas_single_attempt_node_ids
from app.character_motion.providers import ImageTo3DResult
from app.character_motion.tripo import TripoClient, TripoProviderError, TripoUpload, TRIPO_VIEW_ORDER
from app.database import SessionLocal
from app.domain import CanvasRunRequest
from app.nodes import node_registry
from app.nodes.executors import character_motion, character_turnaround
from app.nodes.port_types import port_type_registry
from test_tripo_provider import minimal_glb


def test_canvas_workflow_sandbox_starts_with_provider_registry_installed():
    from temporalio.worker.workflow_sandbox import SandboxedWorkflowRunner
    from temporalio.workflow import _Definition
    from app.canvas_temporal import CanvasRunWorkflow

    async def prepare():
        SandboxedWorkflowRunner().prepare_workflow(_Definition.must_from_class(CanvasRunWorkflow))
    asyncio.run(prepare())


def png(color: int = 40, size: int = 256) -> bytes:
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    rows = (b"\x00" + bytes([color, 80, 120]) * size) * size
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")


def mock_client(requests, *, missing=False, corrupt=False, nested=False):
    def handler(request):
        path = request.url.path
        requests.append((request.method, path))
        if path == "/v3/files":
            assert request.headers["authorization"] == "Bearer test-key"
            return httpx.Response(200, json={"code": 0, "data": {"file_token": "file_source"}})
        if path == "/v3/generation/image-to-multiview":
            assert json.loads(request.content) == {"input": "file_source"}
            return httpx.Response(200, json={"code": 0, "data": {"task_id": "task_views_123"}})
        if path == "/v3/tasks/task_views_123":
            roles = TRIPO_VIEW_ORDER[:-1] if missing else TRIPO_VIEW_ORDER
            output = {f"{role}_view_url": f"https://cdn.tripo3d.ai/{role}.png" for role in roles}
            assert request.headers["cache-control"] == "no-cache"
            return httpx.Response(200, json={"code": 0, "data": {"status": "success", "type": "image_to_multiview", "progress": 100, "credits_consumed": 5, "output": {"generate_multiview_image": output} if nested else output}})
        if request.url.host == "cdn.tripo3d.ai":
            role = path[1:-4]
            data = b"invalid image" if corrupt and role == "back" else png(40 + 20 * TRIPO_VIEW_ORDER.index(role))
            return httpx.Response(200, content=data)
        raise AssertionError(str(request.url))
    return TripoClient(api_key="test-key", http_client=httpx.Client(transport=httpx.MockTransport(handler)))


@pytest.mark.parametrize("nested", [False, True])
def test_multiview_api_normalized_request_download_order_and_resume(nested):
    requests, checkpoints = [], []
    provider = mock_client(requests, nested=nested)
    source = TripoUpload("reference", png(), "image/png", "reference.png")
    result = provider.generate_multiview_images(source, timeout_seconds=60, on_task=lambda *args: checkpoints.append(args))
    assert tuple(view.role for view in result.views) == TRIPO_VIEW_ORDER
    assert result.task.credits_consumed == 5
    assert checkpoints == [("multiview", "pending"), ("multiview", "task_views_123")]
    requests.clear()
    provider.generate_multiview_images(source, timeout_seconds=60, resume_task_id="task_views_123")
    assert all(method == "GET" for method, _ in requests)


def test_multiview_incomplete_result_is_nonretryable():
    with pytest.raises(TripoProviderError, match="all four") as exc:
        mock_client([], missing=True).generate_multiview_images(TripoUpload("reference", png(), "image/png", "source.png"), timeout_seconds=60)
    assert exc.value.retryable is False


def test_turnaround_contract_and_legacy_port_isolation(client):
    definition = node_registry.get("character.turnaround.generate", 1)
    assert definition.editor.kind == "generic"
    assert node_registry.resolve_config(definition, {}) == {"minimum_resolution": 256, "timeout_seconds": 1200}
    assert definition.config_schema["properties"]["minimum_resolution"]["x-workflow-input"]["enabled"]
    with pytest.raises(ValueError, match="at least"):
        node_registry.resolve_config(definition, {"minimum_resolution": 128})
    with pytest.raises(ValueError, match="unknown"):
        node_registry.resolve_config(definition, {"pose": "t_pose"})
    output = definition.ports.outputs[0].type
    assert port_type_registry.compatible(output, node_registry.get("character.image_to_3d", 3).ports.inputs[0].type)
    assert not port_type_registry.compatible(output, node_registry.get("character.image_to_3d", 2).ports.inputs[0].type)
    assert node_registry.get("character.image_to_3d", 1).ports.inputs[0].type == "artifact.character_reference.v1"
    registry = client.get("/node-definitions").json()
    assert any(item["type_key"] == definition.type_key for item in registry)


def experiment_payload(source_id):
    return {"canvas_id": "turnaround_test", "node_id": "turnaround", "node_key": "character.turnaround.generate", "node_contract_version": 1, "model_alias": "tripo.image.multiview", "parameters": {}, "inputs": [{"type": "Image", "artifact_ids": [source_id]}]}


def test_turnaround_artifacts_preview_cache_and_3d_consumer(client, monkeypatch):
    requests = []
    monkeypatch.setattr(character_turnaround, "TripoClient", lambda: mock_client(requests))
    upload = client.post("/artifacts/upload", files={"file": ("source.png", png(), "image/png")}).json()
    payload = experiment_payload(upload["artifact_id"])
    response = client.post("/experiments", json=payload)
    assert response.status_code == 201, response.text
    run = response.json()
    assert run["status"] == "SUCCEEDED", json.dumps(run)
    assert run["exact_model_id"] == "provider-managed:image-to-multiview"
    assert run["provider_request_id"] == "tripo:multiview:task_views_123"
    assert [view["title"] for view in run["output"]["images"]] == [role.title() for role in TRIPO_VIEW_ORDER]
    bundle_id = run["output_artifact_ids"][0]
    bundle = client.get(f"/artifacts/{bundle_id}").json()
    manifest = client.get(f"/artifacts/{bundle_id}/content").json()
    schema = json.loads((Path(__file__).parents[3] / "packages/schemas/character.turnaround.v1.schema.json").read_text())
    jsonschema.validate(manifest, schema)
    assert bundle["metadata"]["provider_metadata"]["credits_consumed"] == 5
    assert bundle["metadata"]["normalized_config"] == {"minimum_resolution": 256, "timeout_seconds": 1200}
    assert manifest["source_image_id"] == upload["artifact_id"]
    for view in manifest["views"]:
        artifact = client.get(f"/artifacts/{view['artifact_id']}").json()
        assert artifact["input_artifact_ids"] == [upload["artifact_id"]]
        assert artifact["metadata"]["input_artifact_roles"][upload["artifact_id"]] == "source_character_image"
    requests.clear()
    cached = client.post("/experiments", json=payload).json()
    assert cached["cache_hit"] is True
    assert cached["output_artifact_ids"] == run["output_artifact_ids"]
    assert requests == []
    changed = copy.deepcopy(payload)
    changed["parameters"]["minimum_resolution"] = 512
    failed = client.post("/experiments", json=changed).json()
    assert failed["status"] == "FAILED"
    assert failed["request_hash"] != run["request_hash"]
    assert not requests  # reject before a billable API call

    class Provider:
        def generate(self, input):
            assert tuple(view.role for view in input.views) == TRIPO_VIEW_ORDER
            assert all(view.data.startswith(b"\x89PNG") for view in input.views)
            return ImageTo3DResult(glb=minimal_glb(rigged=False), provider="tripo", provider_revision="fixture", provider_request_id="tripo:generate:task_mesh_123", metadata={"credits_consumed": 60})
    monkeypatch.setattr(character_motion, "image_to_3d_provider", lambda _: Provider())
    generated = client.post("/experiments", json={"canvas_id": "turnaround_test", "node_id": "mesh", "node_key": "character.image_to_3d", "node_contract_version": 3, "model_alias": "tripo.3d.p1", "inputs": [{"type": "CharacterTurnaround", "artifact_ids": [bundle_id]}]}).json()
    assert generated["status"] == "SUCCEEDED", generated
    artifact = client.get(f"/artifacts/{generated['output_artifact_ids'][0]}").json()
    assert artifact["schema_id"] == "character.3d.glb.v1"
    assert artifact["input_artifact_ids"] == [bundle_id]


def test_corrupt_view_does_not_publish_a_partial_turnaround(client, monkeypatch):
    monkeypatch.setattr(character_turnaround, "TripoClient", lambda: mock_client([], corrupt=True))
    source_id = client.post("/artifacts/upload", files={"file": ("source.png", png(), "image/png")}).json()["artifact_id"]
    run = client.post("/experiments", json=experiment_payload(source_id)).json()
    assert run["status"] == "FAILED"
    assert run["output_artifact_ids"] == []
    assert run["provider_request_id"] == "tripo:multiview:task_views_123"


@pytest.mark.parametrize("temporal", [False, True])
def test_turnaround_stored_canvas_local_temporal_parity(client, monkeypatch, temporal):
    monkeypatch.setattr(character_turnaround, "TripoClient", lambda: mock_client([]))
    monkeypatch.setattr(canvas_activities, "refresh_provider_environment", lambda: None)
    monkeypatch.setattr(canvas_activities.activity, "heartbeat", lambda *_: None)
    source_id = client.post("/artifacts/upload", files={"file": ("source.png", png(), "image/png")}).json()["artifact_id"]
    nodes = [
        {"id": "source", "position": {"x": 0, "y": 0}, "data": {"key": "asset.select", "contractVersion": 2, "config": {"artifact_id": source_id, "artifact_type": "Image"}, "outputArtifactIds": [source_id]}},
        {"id": "turnaround", "position": {"x": 300, "y": 0}, "data": {"key": "character.turnaround.generate", "contractVersion": 1, "config": {}}},
    ]
    edges = [{"id": "reference", "source": "source", "target": "turnaround", "targetHandle": "input-Image-0"}]
    document = canonicalize_canvas_document(nodes, edges)
    saved = client.post("/canvases", json={"name": "Turnaround", "document": document}).json()
    assert canvas_single_attempt_node_ids(saved["nodes"]) == ["turnaround"]
    with SessionLocal() as db:
        run = create_canvas_run(db, CanvasRunRequest(canvas_id=saved["id"], canvas_revision=saved["revision"], target_node_id="turnaround"))
        db.commit()
        run_id = run.id
    if temporal:
        result = asyncio.run(canvas_activities.execute_canvas_node_activity(run_id, "turnaround"))
    else:
        result = execute_canvas_node(run_id, "turnaround")
    assert len(result["artifact_ids"]) == 1, result
    artifact = client.get(f"/artifacts/{result['artifact_ids'][0]}").json()
    assert artifact["type"] == "CharacterTurnaround"
    assert artifact["metadata"]["pose_policy"] == "preserve_source"
    assert [view["provider_role"] for view in artifact["metadata"]["views"]] == list(TRIPO_VIEW_ORDER)


def test_turnaround_publish_pins_contracts_bindings_and_reachable_outputs(client):
    image_id = client.post("/artifacts/upload", files={"file": ("source.png", png(), "image/png")}).json()["artifact_id"]
    workflow = client.post("/workflows", json={"name": "3D turnaround"}).json()
    nodes = [
        {"id": "source", "data": {"key": "asset.select", "contractVersion": 2, "config": {"artifact_id": image_id, "artifact_type": "Image"}}},
        {"id": "views", "data": {"key": "character.turnaround.generate", "contractVersion": 1, "config": {}}},
        {"id": "mesh", "data": {"key": "character.image_to_3d", "contractVersion": 3, "config": {}}},
        {"id": "unused", "data": {"key": "character.reference.multiview", "contractVersion": 1, "config": {}}},
    ]
    edges = [
        {"id": "source-views", "source": "source", "target": "views", "targetHandle": "input-Image-0"},
        {"id": "views-mesh", "source": "views", "target": "mesh", "targetHandle": "input-CharacterTurnaround-0"},
    ]
    contract = {"schema_version": "workflow.contract.draft.v1", "inputs": [{"key": "minimum_size", "label": "Minimum resolution", "type": "integer", "required": False, "default": 256}], "bindings": [{"target": {"node_id": "views", "path": "/config/minimum_resolution"}, "value": {"kind": "input", "key": "minimum_size"}}], "outputs": [{"key": "model", "label": "3D Character", "node_id": "mesh", "port_type": "model.character_3d.v1", "primary": True}]}
    saved = client.put(f"/canvases/{workflow['draft_canvas_id']}", json={"name": "3D turnaround", "document": canonicalize_canvas_document(nodes, edges), "expected_revision": 1, "draft_contract": contract})
    assert saved.status_code == 200, saved.text
    published = client.post(f"/workflows/{workflow['id']}/publish", json={"expected_canvas_revision": saved.json()["revision"]})
    assert published.status_code == 201, published.text
    version = published.json()
    assert {node["id"] for node in version["graph"]["nodes"]} == {"source", "views", "mesh"}
    assert "Unused Canvas Node excluded: unused" in version["warnings"]
    for node in version["graph"]["nodes"]:
        definition = node_registry.get(node["type_key"], node["contract_version"])
        assert node["definition_digest"] == definition.definition_digest
    assert next(node for node in version["graph"]["nodes"] if node["id"] == "views")["config"]["minimum_resolution"] == 256
