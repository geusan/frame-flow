from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import zipfile

from app.canvas_packages import (
    CHECKSUMS_PATH,
    CONTRACT_PATH,
    DOCUMENT_PATH,
    MANIFEST_PATH,
    PACKAGE_MEDIA_TYPE,
)


def _package_files(content: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(content)) as package:
        return {name: package.read(name) for name in package.namelist()}


def _rewrite_package(files: dict[str, bytes]) -> bytes:
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as package:
        for name, content in files.items():
            package.writestr(name, content)
    return archive.getvalue()


def test_frameflow_package_manifest_schema_is_versioned():
    schema_path = Path(__file__).parents[3] / "packages" / "schemas" / "frameflow.package.v1.schema.json"
    schema = json.loads(schema_path.read_text())
    assert schema["properties"]["schema_version"]["const"] == "frameflow.package.v1"
    assert schema["properties"]["package_kind"]["const"] == "canvas.template"


def test_canvas_template_export_import_round_trip_excludes_runtime_and_local_artifacts(client):
    uploaded = client.post(
        "/artifacts/upload",
        files={"file": ("reference.png", b"\x89PNG\r\n\x1a\n-package", "image/png")},
    ).json()
    nodes = [
        {
            "id": "prompt",
            "position": {"x": 40, "y": 80},
            "data": {
                "key": "prompt.input",
                "label": "Prompt",
                "configText": "Portable prompt",
                "status": "SUCCEEDED",
                "logs": ["must not be exported"],
                "output": {"kind": "text", "title": "Runtime", "text": "runtime output"},
            },
        },
        {
            "id": "asset",
            "position": {"x": 40, "y": 240},
            "data": {
                "key": "asset.select",
                "label": "Local asset",
                "configText": uploaded["artifact_id"],
                "outputType": "Image",
                "outputArtifactIds": [uploaded["artifact_id"]],
                "status": "SUCCEEDED",
            },
        },
        {
            "id": "image",
            "position": {"x": 360, "y": 80},
            "data": {
                "key": "image.generate",
                "label": "Image",
                "provider": "google",
                "model": "image.fast",
                "aspectRatio": "9:16",
                "resolution": "2K",
                "status": "STALE",
                "outputArtifactIds": ["runtime-output"],
            },
        },
        {
            "id": "memo",
            "position": {"x": 20, "y": 420},
            "data": {
                "key": "utility.sticky",
                "label": "Memo",
                "configText": "Portable annotation",
                "stickyColor": "yellow",
                "status": "READY",
            },
        },
        {
            "id": "unknown",
            "position": {"x": 680, "y": 80},
            "data": {
                "key": "plugin.not_installed",
                "label": "Unknown plugin node",
                "config": {"opaque": "preserved"},
                "status": "BLOCKED",
            },
        },
    ]
    edges = [{"id": "prompt-image", "source": "prompt", "target": "image", "targetHandle": "input-Prompt-0"}]
    contract = {
        "schema_version": "workflow.contract.draft.v1",
        "inputs": [{
            "key": "source_image",
            "label": "Source image",
            "type": "artifact",
            "required": False,
            "default": uploaded["artifact_id"],
        }],
        "bindings": [],
        "outputs": [],
    }
    created = client.post("/canvases", json={
        "name": "Portable Canvas",
        "nodes": nodes,
        "edges": edges,
        "draft_contract": contract,
    })
    assert created.status_code == 201, created.text

    exported = client.get(f"/canvases/{created.json()['id']}/export")
    assert exported.status_code == 200, exported.text
    assert exported.headers["content-type"] == PACKAGE_MEDIA_TYPE
    assert exported.headers["content-disposition"].endswith('.frameflow"')
    files = _package_files(exported.content)
    assert set(files) == {MANIFEST_PATH, DOCUMENT_PATH, CONTRACT_PATH, CHECKSUMS_PATH}
    manifest = json.loads(files[MANIFEST_PATH])
    document = json.loads(files[DOCUMENT_PATH])
    exported_contract = json.loads(files[CONTRACT_PATH])
    assert manifest["schema_version"] == "frameflow.package.v1"
    assert manifest["package_kind"] == "canvas.template"
    assert document["runtime"]["nodes"] == {}
    assert "must not be exported" not in files[DOCUMENT_PATH].decode()
    assert "runtime-output" not in files[DOCUMENT_PATH].decode()
    asset = next(node for node in document["graph"]["nodes"] if node["id"] == "asset")
    unknown = next(node for node in document["graph"]["nodes"] if node["id"] == "unknown")
    assert asset["config"]["artifact_id"] == ""
    assert unknown["unknown"] is True
    assert exported_contract["inputs"][0]["required"] is True
    assert "default" not in exported_contract["inputs"][0]
    assert any("artifact_id cleared" in warning for warning in manifest["warnings"])
    assert any("Local default removed" in warning for warning in manifest["warnings"])

    imported = client.post(
        "/canvases/import",
        data={"name": "Imported copy"},
        files={"file": ("portable.frameflow", exported.content, PACKAGE_MEDIA_TYPE)},
    )
    assert imported.status_code == 201, imported.text
    imported_payload = imported.json()
    assert imported_payload["id"] != created.json()["id"]
    assert imported_payload["name"] == "Imported copy"
    assert imported_payload["storage_schema_version"] == "canvas.document.v1"
    assert [node["id"] for node in imported_payload["nodes"]] == ["prompt", "asset", "image", "memo", "unknown"]
    imported_asset = next(node for node in imported_payload["nodes"] if node["id"] == "asset")
    imported_unknown = next(node for node in imported_payload["nodes"] if node["id"] == "unknown")
    assert imported_asset["data"]["configText"] == ""
    assert imported_unknown["data"]["config"] == {"opaque": "preserved"}
    assert any("preserved read-only" in warning for warning in imported_payload["import_warnings"])

    reexported = client.get(f"/canvases/{imported_payload['id']}/export")
    assert reexported.status_code == 200
    reexported_files = _package_files(reexported.content)
    assert json.loads(reexported_files[DOCUMENT_PATH]) == document
    assert json.loads(reexported_files[CONTRACT_PATH]) == exported_contract


def test_canvas_template_export_rejects_secret_fields_and_signed_urls(client):
    secret_canvas = client.post("/canvases", json={
        "name": "Secret Canvas",
        "nodes": [{
            "id": "unknown",
            "data": {"key": "plugin.secret", "label": "Secret", "config": {"api_key": "do-not-export"}},
        }],
        "edges": [],
    }).json()
    rejected_secret = client.get(f"/canvases/{secret_canvas['id']}/export")
    assert rejected_secret.status_code == 422
    assert "Secret-like field" in rejected_secret.json()["detail"]

    signed_canvas = client.post("/canvases", json={
        "name": "Signed URL Canvas",
        "nodes": [{
            "id": "lora",
            "data": {
                "key": "lora.image.generate",
                "label": "LoRA",
                "loraUrl": "https://example.com/model.safetensors?X-Amz-Signature=secret",
            },
        }],
        "edges": [],
    }).json()
    rejected_url = client.get(f"/canvases/{signed_canvas['id']}/export")
    assert rejected_url.status_code == 422
    assert "Signed URL" in rejected_url.json()["detail"]


def test_canvas_template_import_rejects_unsafe_paths_and_checksum_mismatch(client):
    unsafe = io.BytesIO()
    with zipfile.ZipFile(unsafe, "w") as package:
        package.writestr("../manifest.json", "{}")
    rejected_path = client.post(
        "/canvases/import",
        files={"file": ("unsafe.frameflow", unsafe.getvalue(), PACKAGE_MEDIA_TYPE)},
    )
    assert rejected_path.status_code == 422
    assert "Unsafe package path" in rejected_path.json()["detail"]

    created = client.post("/canvases", json={
        "name": "Checksum source",
        "nodes": [{"id": "prompt", "data": {"key": "prompt.input", "configText": "hello"}}],
        "edges": [],
    }).json()
    exported = client.get(f"/canvases/{created['id']}/export").content
    files = _package_files(exported)
    document = json.loads(files[DOCUMENT_PATH])
    document["graph"]["nodes"][0]["config"]["text"] = "tampered"
    files[DOCUMENT_PATH] = json.dumps(document).encode()
    tampered = _rewrite_package(files)
    rejected_checksum = client.post(
        "/canvases/import",
        files={"file": ("tampered.frameflow", tampered, PACKAGE_MEDIA_TYPE)},
    )
    assert rejected_checksum.status_code == 422
    assert "checksum mismatch" in rejected_checksum.json()["detail"]

    malformed_files = _package_files(exported)
    malformed_document = json.loads(malformed_files[DOCUMENT_PATH])
    malformed_document["graph"]["nodes"] = {"not": "an array"}
    malformed_files[DOCUMENT_PATH] = json.dumps(malformed_document, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    checksums = json.loads(malformed_files[CHECKSUMS_PATH])
    checksums["files"][DOCUMENT_PATH] = hashlib.sha256(malformed_files[DOCUMENT_PATH]).hexdigest()
    malformed_files[CHECKSUMS_PATH] = json.dumps(checksums, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    malformed = client.post(
        "/canvases/import",
        files={"file": ("malformed.frameflow", _rewrite_package(malformed_files), PACKAGE_MEDIA_TYPE)},
    )
    assert malformed.status_code == 422
    assert "Canvas nodes must be an array of objects" in malformed.json()["detail"]
