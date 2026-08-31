from __future__ import annotations

from copy import deepcopy
import time


def workflow_canvas_graph() -> tuple[list[dict], list[dict], dict]:
    nodes = [
        {
            "id": "prompt",
            "position": {"x": 40, "y": 80},
            "data": {
                "key": "prompt.input",
                "label": "Topic",
                "description": "Workflow topic",
                "executable": False,
                "outputType": "Prompt",
                "configText": "A cat making breakfast",
                "status": "SUCCEEDED",
            },
        },
        {
            "id": "image",
            "position": {"x": 360, "y": 80},
            "data": {
                "key": "image.generate",
                "label": "Hero image",
                "description": "Generate the hero frame",
                "model": "image.fast",
                "provider": "google",
                "inputTypes": ["Prompt"],
                "requiredInputTypes": ["Prompt"],
                "outputType": "Image",
                "resolution": "2K",
                "aspectRatio": "9:16",
                "status": "SUCCEEDED",
                "output": {"kind": "image", "title": "Old result", "url": "blob:old"},
                "outputArtifactIds": ["old_runtime_artifact"],
                "logs": ["runtime only"],
            },
        },
        {
            "id": "unused",
            "position": {"x": 360, "y": 320},
            "data": {
                "key": "llm.assistant",
                "label": "Unused assistant",
                "description": "Not connected to a declared output",
                "model": "text.quality",
                "provider": "google",
                "outputType": "Text",
            },
        },
        {
            "id": "memo",
            "position": {"x": 20, "y": 360},
            "data": {
                "key": "utility.sticky",
                "label": "Memo",
                "description": "Canvas memo",
                "configText": "검토 후 공개",
                "stickyColor": "pink",
                "executable": False,
            },
        },
        {
            "id": "folder",
            "position": {"x": 0, "y": 0},
            "data": {
                "key": "folder.group",
                "label": "Layout group",
                "description": "Canvas organization",
                "executable": False,
            },
        },
    ]
    edges = [
        {
            "id": "prompt-image",
            "source": "prompt",
            "target": "image",
            "targetHandle": "input-Prompt-0",
        }
    ]
    contract = {
        "schema_version": "workflow.contract.draft.v1",
        "inputs": [
            {"key": "topic", "label": "Topic", "type": "prompt", "required": True}
        ],
        "bindings": [
            {
                "target": {"node_id": "prompt", "path": "/config/text"},
                "value": {"kind": "input", "key": "topic"},
            }
        ],
        "outputs": [
            {"key": "hero_image", "label": "Hero image", "node_id": "image", "port_type": "Image", "primary": True}
        ],
    }
    return nodes, edges, contract


def create_configured_workflow(client):
    created = client.post("/workflows", json={
        "name": "Breakfast shorts",
        "description": "Reusable hero image workflow",
        "tags": ["shorts", "image", "shorts"],
    })
    assert created.status_code == 201
    workflow = created.json()
    assert workflow["version_count"] == 0
    assert workflow["current_version_id"] is None
    assert workflow["tags"] == ["shorts", "image"]

    canvas = client.get(f"/canvases/{workflow['draft_canvas_id']}").json()
    assert canvas["revision"] == 1
    assert canvas["workflow_definition_id"] == workflow["id"]
    nodes, edges, contract = workflow_canvas_graph()
    saved = client.put(f"/canvases/{canvas['id']}", json={
        "name": "Breakfast shorts",
        "nodes": nodes,
        "edges": edges,
        "expected_revision": 1,
        "draft_contract": contract,
    })
    assert saved.status_code == 200
    assert saved.json()["revision"] == 2
    return workflow, saved.json()


def test_publish_freezes_reachable_graph_and_extracts_mutable_annotations(client):
    workflow, canvas = create_configured_workflow(client)
    published = client.post(f"/workflows/{workflow['id']}/publish", json={
        "expected_canvas_revision": canvas["revision"],
        "release_notes": "Initial version",
    })
    assert published.status_code == 201, published.text
    version = published.json()
    assert version["version_number"] == 1
    assert version["schema_version"] == "workflow.version.v1"
    assert len(version["content_hash"]) == 64
    assert version["warnings"] == ["Unused Canvas Node excluded: unused"]
    assert [node["id"] for node in version["graph"]["nodes"]] == ["prompt", "image"]
    assert all("status" not in node and "output" not in node for node in version["graph"]["nodes"])
    image = next(node for node in version["graph"]["nodes"] if node["id"] == "image")
    assert image["type_key"] == "image.generate"
    assert image["contract_version"] == 1
    assert image["definition_digest"].startswith("sha256:")
    assert image["config"]["resolution"] == "2K"
    assert image["config"]["output_count"] == 1

    annotations = client.get(f"/workflows/{workflow['id']}/versions/1/annotations").json()
    assert len(annotations) == 1
    assert annotations[0]["body"] == "검토 후 공개"
    assert annotations[0]["position"] == {"x": 20, "y": 360}
    assert annotations[0]["color"] == "pink"

    current = client.get(f"/workflows/{workflow['id']}").json()
    assert current["current_version_id"] == version["id"]
    assert current["current_version_number"] == 1
    assert current["version_count"] == 1
    frozen_canvas = client.get(f"/canvases/{canvas['id']}").json()
    assert frozen_canvas["base_version_id"] == version["id"]

    retried = client.post(f"/workflows/{workflow['id']}/publish", json={
        "expected_canvas_revision": canvas["revision"],
        "release_notes": "retry must be idempotent",
    })
    assert retried.status_code == 201
    assert retried.json()["id"] == version["id"]
    assert len(client.get(f"/workflows/{workflow['id']}/versions").json()) == 1


def test_annotation_changes_do_not_change_frozen_version_hash(client):
    workflow, canvas = create_configured_workflow(client)
    version = client.post(f"/workflows/{workflow['id']}/publish", json={"expected_canvas_revision": canvas["revision"]}).json()
    initial_hash = version["content_hash"]
    initial = client.get(f"/workflows/{workflow['id']}/versions/1/annotations").json()[0]

    updated = client.patch(f"/workflow-annotations/{initial['id']}", json={
        "expected_revision": 1,
        "body": "수정 가능한 운영 메모",
        "position": {"x": 44, "y": 55},
        "color": "green",
    })
    assert updated.status_code == 200
    assert updated.json()["revision"] == 2
    assert updated.json()["body"] == "수정 가능한 운영 메모"
    conflict = client.patch(f"/workflow-annotations/{initial['id']}", json={
        "expected_revision": 1,
        "body": "stale write",
    })
    assert conflict.status_code == 409
    assert client.get(f"/workflows/{workflow['id']}/versions/1").json()["content_hash"] == initial_hash

    definition_note = client.post(f"/workflows/{workflow['id']}/annotations", json={
        "body": "모든 버전에 보이는 메모",
        "position": {"x": 1, "y": 2},
    })
    assert definition_note.status_code == 201
    assert len(client.get(f"/workflows/{workflow['id']}/annotations").json()) == 1
    deleted = client.delete(f"/workflow-annotations/{definition_note.json()['id']}")
    assert deleted.status_code == 204
    assert client.get(f"/workflows/{workflow['id']}/annotations").json() == []


def test_editing_draft_creates_v2_without_mutating_v1(client):
    workflow, canvas = create_configured_workflow(client)
    v1 = client.post(f"/workflows/{workflow['id']}/publish", json={"expected_canvas_revision": canvas["revision"]}).json()
    original_graph = deepcopy(v1["graph"])
    draft = client.get(f"/canvases/{canvas['id']}").json()
    nodes = deepcopy(draft["nodes"])
    image = next(node for node in nodes if node["id"] == "image")
    image["data"]["aspectRatio"] = "1:1"
    saved = client.put(f"/canvases/{canvas['id']}", json={
        "name": draft["name"],
        "nodes": nodes,
        "edges": draft["edges"],
        "expected_revision": draft["revision"],
        "draft_contract": draft["draft_contract"],
    })
    assert saved.status_code == 200
    assert saved.json()["revision"] == 3
    v2 = client.post(f"/workflows/{workflow['id']}/publish", json={
        "expected_canvas_revision": 3,
        "release_notes": "Square variant",
    })
    assert v2.status_code == 201
    assert v2.json()["version_number"] == 2
    assert v2.json()["content_hash"] != v1["content_hash"]
    assert client.get(f"/workflows/{workflow['id']}/versions/1").json()["graph"] == original_graph
    assert client.get(f"/workflows/{workflow['id']}").json()["current_version_number"] == 2


def test_publish_rejects_revision_conflict_incomplete_upload_and_archive(client):
    workflow, canvas = create_configured_workflow(client)
    conflict = client.post(f"/workflows/{workflow['id']}/publish", json={"expected_canvas_revision": 1})
    assert conflict.status_code == 409

    draft = client.get(f"/canvases/{canvas['id']}").json()
    nodes = deepcopy(draft["nodes"])
    nodes.append({
        "id": "upload",
        "position": {"x": 80, "y": 500},
        "data": {"key": "asset.upload", "label": "Upload", "description": "Incomplete", "executable": False},
    })
    contract = deepcopy(draft["draft_contract"])
    contract["outputs"] = [{"key": "upload", "label": "Upload", "node_id": "upload", "port_type": "Image", "primary": True}]
    saved = client.put(f"/canvases/{canvas['id']}", json={
        "name": draft["name"], "nodes": nodes, "edges": draft["edges"],
        "expected_revision": draft["revision"], "draft_contract": contract,
    }).json()
    rejected = client.post(f"/workflows/{workflow['id']}/publish", json={"expected_canvas_revision": saved["revision"]})
    assert rejected.status_code == 422
    assert "saved as an Artifact" in rejected.json()["detail"]

    archived = client.post(f"/workflows/{workflow['id']}/archive")
    assert archived.status_code == 200
    assert archived.json()["status"] == "ARCHIVED"
    rejected_archived = client.post(f"/workflows/{workflow['id']}/publish", json={"expected_canvas_revision": saved["revision"]})
    assert rejected_archived.status_code == 422
    assert client.post(f"/workflows/{workflow['id']}/activate").json()["status"] == "ACTIVE"


def test_canvas_autosave_uses_optimistic_revision(client):
    workflow, canvas = create_configured_workflow(client)
    stale = client.put(f"/canvases/{canvas['id']}", json={
        "name": "stale",
        "nodes": canvas["nodes"],
        "edges": canvas["edges"],
        "expected_revision": 1,
    })
    assert stale.status_code == 409
    assert client.get(f"/canvases/{workflow['draft_canvas_id']}").json()["revision"] == 2


def test_published_workflow_runs_from_version_and_validated_inputs(client):
    workflow, canvas = create_configured_workflow(client)
    version = client.post(f"/workflows/{workflow['id']}/publish", json={"expected_canvas_revision": canvas["revision"]}).json()
    missing = client.post(f"/workflows/{workflow['id']}/runs", json={"inputs": {}})
    assert missing.status_code == 422
    unknown = client.post(f"/workflows/{workflow['id']}/runs", json={"inputs": {"topic": "hello", "unknown": True}})
    assert unknown.status_code == 422

    started = client.post(f"/workflows/{workflow['id']}/runs", json={
        "version": 1,
        "inputs": {"topic": "A dog making a midnight snack"},
    })
    assert started.status_code == 201, started.text
    run = started.json()
    assert run["source_type"] == "WORKFLOW_VERSION"
    assert run["workflow_definition_id"] == workflow["id"]
    assert run["workflow_version_id"] == version["id"]
    assert run["inputs"] == {"topic": "A dog making a midnight snack"}
    assert run["compiler_version"] == "workflow-compiler.v1"
    assert run["model_snapshot"]["image"]["model_alias"] == "google.image.fast"
    assert run["model_snapshot"]["image"]["exact_model_id"] == "gemini-3.1-flash-image"
    prompt = next(node for node in run["graph"]["nodes"] if node["id"] == "prompt")
    assert prompt["data"]["configText"] == "A dog making a midnight snack"
    assert {node["id"] for node in run["graph"]["nodes"]} == {"prompt", "image"}

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        run = client.get(f"/canvas-runs/{run['id']}").json()
        if run["status"] in {"SUCCEEDED", "FAILED"}:
            break
        time.sleep(0.03)
    assert run["status"] == "SUCCEEDED"
    assert next(node for node in run["node_runs"] if node["canvas_node_id"] == "image")["output_artifact_ids"]
    listed = client.get("/workflow-runs").json()
    listed_run = next(item for item in listed if item["id"] == run["id"])
    assert listed_run["run_type"] == "workflow"
    assert listed_run["workflow_version_id"] == version["id"]


def test_publish_rejects_binding_with_incompatible_input_type(client):
    workflow, canvas = create_configured_workflow(client)
    contract = deepcopy(canvas["draft_contract"])
    contract["inputs"][0]["type"] = "number"
    saved = client.put(f"/canvases/{canvas['id']}", json={
        "name": canvas["name"],
        "nodes": canvas["nodes"],
        "edges": canvas["edges"],
        "expected_revision": canvas["revision"],
        "draft_contract": contract,
    }).json()
    rejected = client.post(f"/workflows/{workflow['id']}/publish", json={"expected_canvas_revision": saved["revision"]})
    assert rejected.status_code == 422
    assert "incompatible" in rejected.json()["detail"]


def test_publish_rejects_edges_with_incompatible_manifest_ports(client):
    workflow, canvas = create_configured_workflow(client)
    nodes = deepcopy(canvas["nodes"])
    nodes.append({
        "id": "voice",
        "position": {"x": 40, "y": 220},
        "data": {
            "key": "tts.generate",
            "label": "Voice",
            "description": "Audio cannot feed a Prompt port",
            "model": "google.tts.fast",
            "provider": "google",
            "inputTypes": ["Prompt"],
            "requiredInputTypes": ["Prompt"],
            "outputType": "Audio",
        },
    })
    edges = [{"id": "audio-image", "source": "voice", "target": "image", "targetHandle": "input-Prompt-0"}]
    saved = client.put(f"/canvases/{canvas['id']}", json={
        "name": canvas["name"],
        "nodes": nodes,
        "edges": edges,
        "expected_revision": canvas["revision"],
        "draft_contract": canvas["draft_contract"],
    }).json()
    rejected = client.post(f"/workflows/{workflow['id']}/publish", json={"expected_canvas_revision": saved["revision"]})
    assert rejected.status_code == 422
    assert rejected.json()["detail"] == "Incompatible Node ports: media.audio.v1 → prompt.text.v1"


def test_artifact_workflow_input_hydrates_a_typed_source_node(client):
    uploaded = client.post(
        "/artifacts/upload",
        files={"file": ("workflow-source.png", b"\x89PNG\r\n\x1a\n-workflow", "image/png")},
    ).json()
    workflow = client.post("/workflows", json={"name": "Artifact input workflow"}).json()
    canvas = client.get(f"/canvases/{workflow['draft_canvas_id']}").json()
    nodes = [{
        "id": "asset",
        "position": {"x": 80, "y": 100},
        "data": {
            "key": "asset.select",
            "label": "Runtime image",
            "description": "Selected when the Workflow starts",
            "executable": False,
            "outputType": "ReferenceAsset",
            "configText": "",
        },
    }]
    contract = {
        "schema_version": "workflow.contract.draft.v1",
        "inputs": [{
            "key": "source_image",
            "label": "Source image",
            "type": "artifact",
            "required": True,
            "validation": {"artifact_types": ["Image"]},
        }],
        "bindings": [{
            "target": {"node_id": "asset", "path": "/config/artifact_id"},
            "value": {"kind": "input", "key": "source_image"},
        }],
        "outputs": [{
            "key": "selected_image",
            "label": "Selected image",
            "node_id": "asset",
            "port_type": "ReferenceAsset",
            "primary": True,
        }],
    }
    saved = client.put(f"/canvases/{canvas['id']}", json={
        "name": canvas["name"], "nodes": nodes, "edges": [],
        "expected_revision": 1, "draft_contract": contract,
    }).json()
    version = client.post(f"/workflows/{workflow['id']}/publish", json={"expected_canvas_revision": saved["revision"]})
    assert version.status_code == 201, version.text
    wrong_type = client.post(f"/workflows/{workflow['id']}/runs", json={"inputs": {"source_image": "missing"}})
    assert wrong_type.status_code == 422
    started = client.post(f"/workflows/{workflow['id']}/runs", json={"inputs": {"source_image": uploaded["artifact_id"]}})
    assert started.status_code == 201, started.text
    run = started.json()
    source = next(node for node in run["graph"]["nodes"] if node["id"] == "asset")
    assert source["data"]["outputArtifactIds"] == [uploaded["artifact_id"]]
    assert source["data"]["outputType"] == "Image"
