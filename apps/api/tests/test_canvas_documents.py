from __future__ import annotations

import ast
from copy import deepcopy
import json
from pathlib import Path

from app.canvas_documents import (
    CANVAS_DOCUMENT_SCHEMA_VERSION,
    CANVAS_GRAPH_SCHEMA_VERSION,
    CANVAS_RUNTIME_SCHEMA_VERSION,
    canonicalize_canvas_document,
    legacy_canvas_graph,
)
from app.database import CanvasRecord, SessionLocal


def test_canvas_document_canonicalizes_contract_runtime_and_canvas_elements(client):
    nodes = [
        {
            "id": "prompt",
            "type": "studio",
            "position": {"x": 40, "y": 80},
            "selected": True,
            "data": {
                "key": "prompt.input",
                "label": "Actual Prompt",
                "description": "Prompt description",
                "kind": "input",
                "executable": False,
                "configText": "Persist this graph",
                "status": "SUCCEEDED",
                "logs": ["runtime only"],
                "outputType": "Prompt",
            },
        },
        {
            "id": "image",
            "position": {"x": 360, "y": 80},
            "data": {
                "key": "image.generate",
                "label": "Image",
                "description": "Generate image",
                "model": "image.fast",
                "provider": "google",
                "resolution": "2K",
                "aspectRatio": "9:16",
                "status": "STALE",
                "outputArtifactIds": ["old-runtime-artifact"],
            },
        },
        {
            "id": "memo",
            "position": {"x": 20, "y": 300},
            "data": {
                "key": "utility.sticky",
                "label": "Memo",
                "description": "Canvas-only memo",
                "configText": "Review before publish",
                "stickyColor": "pink",
                "status": "READY",
            },
        },
        {
            "id": "unknown",
            "position": {"x": 640, "y": 80},
            "data": {
                "key": "custom.missing",
                "label": "Missing plugin node",
                "description": "Must survive a load/save round trip",
                "config": {"opaque": True},
                "status": "BLOCKED",
            },
        },
    ]
    edges = [
        {
            "id": "prompt-image",
            "source": "prompt",
            "target": "image",
            "targetHandle": "input-Prompt-0",
            "type": "adaptive",
            "selected": True,
        }
    ]

    created = client.post("/canvases", json={"name": "Canonical Canvas", "nodes": nodes, "edges": edges})
    assert created.status_code == 201, created.text
    payload = created.json()
    assert payload["storage_schema_version"] == CANVAS_DOCUMENT_SCHEMA_VERSION
    assert [node["id"] for node in payload["nodes"]] == ["prompt", "image", "memo", "unknown"]
    assert next(node for node in payload["nodes"] if node["id"] == "prompt")["data"]["status"] == "SUCCEEDED"
    assert next(node for node in payload["nodes"] if node["id"] == "unknown")["data"]["config"] == {"opaque": True}

    with SessionLocal() as db:
        record = db.get(CanvasRecord, payload["id"])
        assert record is not None
        stored = deepcopy(record.graph_json)
    assert stored["schema_version"] == CANVAS_DOCUMENT_SCHEMA_VERSION
    assert stored["graph"]["schema_version"] == CANVAS_GRAPH_SCHEMA_VERSION
    assert stored["runtime"]["schema_version"] == CANVAS_RUNTIME_SCHEMA_VERSION
    assert {node["id"] for node in stored["graph"]["nodes"]} == {"prompt", "image", "unknown"}
    assert [element["id"] for element in stored["graph"]["elements"]] == ["memo"]
    prompt = next(node for node in stored["graph"]["nodes"] if node["id"] == "prompt")
    image = next(node for node in stored["graph"]["nodes"] if node["id"] == "image")
    unknown = next(node for node in stored["graph"]["nodes"] if node["id"] == "unknown")
    assert prompt["config"] == {"text": "Persist this graph"}
    assert prompt["definition_digest"].startswith("sha256:")
    assert image["config"]["resolution"] == "2K"
    assert image["config"]["output_count"] == 1
    assert image["execution"] == {"model_alias": "google.image.fast", "provider": "google"}
    assert unknown["unknown"] is True
    assert stored["runtime"]["nodes"]["prompt"] == {"logs": ["runtime only"], "status": "SUCCEEDED"}
    assert "selected" not in prompt["ui"]["react_flow"]
    assert stored["graph"]["edges"][0]["target_port"] == "input-Prompt-0"
    assert "selected" not in stored["graph"]["edges"][0]["ui"]

    canonical_saved = client.put(f"/canvases/{payload['id']}", json={
        "name": payload["name"],
        "document": stored,
        "expected_revision": payload["revision"],
        "draft_contract": payload["draft_contract"],
    })
    assert canonical_saved.status_code == 200, canonical_saved.text
    assert canonical_saved.json()["revision"] == payload["revision"]
    with SessionLocal() as db:
        assert db.get(CanvasRecord, payload["id"]).graph_json == stored

    saved = client.put(f"/canvases/{payload['id']}", json={
        "name": payload["name"],
        "nodes": payload["nodes"],
        "edges": payload["edges"],
        "expected_revision": payload["revision"],
        "draft_contract": payload["draft_contract"],
    })
    assert saved.status_code == 200, saved.text
    assert saved.json()["revision"] == payload["revision"]
    with SessionLocal() as db:
        assert db.get(CanvasRecord, payload["id"]).graph_json == stored

    runtime_nodes = deepcopy(saved.json()["nodes"])
    runtime_prompt = next(node for node in runtime_nodes if node["id"] == "prompt")
    runtime_prompt["data"]["status"] = "FAILED"
    runtime_prompt["data"]["logs"] = ["new runtime state"]
    runtime_only = client.put(f"/canvases/{payload['id']}", json={
        "name": payload["name"],
        "nodes": runtime_nodes,
        "edges": saved.json()["edges"],
        "expected_revision": saved.json()["revision"],
        "draft_contract": saved.json()["draft_contract"],
    })
    assert runtime_only.status_code == 200
    assert runtime_only.json()["revision"] == payload["revision"]
    assert next(node for node in runtime_only.json()["nodes"] if node["id"] == "prompt")["data"]["status"] == "FAILED"

    definition_nodes = deepcopy(runtime_only.json()["nodes"])
    next_prompt = next(node for node in definition_nodes if node["id"] == "prompt")
    next_prompt["data"]["configText"] = "Changed definition"
    definition_save = client.put(f"/canvases/{payload['id']}", json={
        "name": payload["name"],
        "nodes": definition_nodes,
        "edges": runtime_only.json()["edges"],
        "expected_revision": runtime_only.json()["revision"],
        "draft_contract": runtime_only.json()["draft_contract"],
    })
    assert definition_save.status_code == 200
    assert definition_save.json()["revision"] == payload["revision"] + 1


def test_legacy_canvas_document_reads_without_rewrite_and_upgrades_on_save(client):
    with SessionLocal() as db:
        record = CanvasRecord(
            id="canvas_legacy_fixture",
            name="Legacy fixture",
            graph_json={
                "nodes": [{
                    "id": "prompt",
                    "position": {"x": 1, "y": 2},
                    "data": {"key": "prompt.input", "label": "Prompt", "configText": "legacy"},
                }],
                "edges": [],
            },
            revision=1,
            draft_contract_json={},
        )
        db.add(record)
        db.commit()

    opened = client.get("/canvases/canvas_legacy_fixture")
    assert opened.status_code == 200
    assert opened.json()["storage_schema_version"] == "canvas.legacy.v1"
    assert opened.json()["nodes"][0]["data"]["configText"] == "legacy"
    with SessionLocal() as db:
        assert "schema_version" not in db.get(CanvasRecord, "canvas_legacy_fixture").graph_json

    upgraded = client.put("/canvases/canvas_legacy_fixture", json={
        "name": "Legacy fixture",
        "nodes": opened.json()["nodes"],
        "edges": [],
        "expected_revision": 1,
    })
    assert upgraded.status_code == 200
    assert upgraded.json()["storage_schema_version"] == CANVAS_DOCUMENT_SCHEMA_VERSION
    with SessionLocal() as db:
        assert db.get(CanvasRecord, "canvas_legacy_fixture").graph_json["schema_version"] == CANVAS_DOCUMENT_SCHEMA_VERSION


def test_canvas_api_accepts_canonical_document_writes_and_rejects_invalid_schema(client):
    canonical = canonicalize_canvas_document([{
        "id": "prompt",
        "position": {"x": 8, "y": 12},
        "data": {
            "key": "prompt.input",
            "label": "Prompt",
            "description": "Canonical write",
            "configText": "write canonical directly",
            "status": "SUCCEEDED",
            "outputType": "Prompt",
        },
    }], [])
    created = client.post("/canvases", json={"name": "Canonical direct", "document": canonical})
    assert created.status_code == 201, created.text
    assert created.json()["storage_schema_version"] == CANVAS_DOCUMENT_SCHEMA_VERSION
    assert created.json()["nodes"][0]["data"]["configText"] == "write canonical directly"
    with SessionLocal() as db:
        assert db.get(CanvasRecord, created.json()["id"]).graph_json == canonical

    invalid = deepcopy(canonical)
    invalid["graph"]["schema_version"] = "canvas.graph.v0"
    rejected = client.put(f"/canvases/{created.json()['id']}", json={
        "name": "Canonical direct",
        "document": invalid,
        "expected_revision": created.json()["revision"],
    })
    assert rejected.status_code == 422
    assert rejected.json()["detail"] == "document.graph.schema_version must be canvas.graph.v1"


def test_canvas_document_schema_and_adapter_fixture_are_stable():
    schema_path = Path(__file__).parents[3] / "packages" / "schemas" / "canvas.document.v1.schema.json"
    schema = json.loads(schema_path.read_text())
    assert schema["properties"]["schema_version"]["const"] == CANVAS_DOCUMENT_SCHEMA_VERSION

    legacy = {
        "nodes": [{"id": "prompt", "position": {"x": 1, "y": 2}, "data": {"key": "prompt.input", "configText": "hello"}}],
        "edges": [],
    }
    canonical = canonicalize_canvas_document(legacy["nodes"], legacy["edges"])
    restored = legacy_canvas_graph(canonical)
    assert restored["nodes"][0]["id"] == "prompt"
    assert restored["nodes"][0]["data"]["configText"] == "hello"


def test_canvas_record_writes_do_not_introduce_legacy_graph_literals():
    app_root = Path(__file__).parents[1] / "app"
    violations: list[str] = []
    for path in app_root.rglob("*.py"):
        if path.name == "canvas_documents.py":
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            value = None
            if isinstance(node, ast.keyword) and node.arg == "graph_json":
                value = node.value
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                if any(isinstance(target, ast.Attribute) and target.attr == "graph_json" for target in targets):
                    value = node.value
            if not isinstance(value, ast.Dict):
                continue
            keys = {item.value for item in value.keys if isinstance(item, ast.Constant)}
            if "nodes" in keys or "edges" in keys:
                violations.append(str(path.relative_to(app_root)))
    assert violations == []
