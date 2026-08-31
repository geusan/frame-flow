from __future__ import annotations

import hashlib
import io
import json
from copy import deepcopy
from dataclasses import dataclass
from pathlib import PurePosixPath
import re
from typing import Any
from urllib.parse import parse_qsl, urlparse
import zipfile

from .canvas_documents import (
    CANVAS_DOCUMENT_SCHEMA_VERSION,
    CANVAS_GRAPH_SCHEMA_VERSION,
    CANVAS_RUNTIME_SCHEMA_VERSION,
    canonical_canvas_graph,
)
from .nodes import node_registry


PACKAGE_SCHEMA_VERSION = "frameflow.package.v1"
PACKAGE_KIND = "canvas.template"
PACKAGE_MEDIA_TYPE = "application/vnd.frameflow.package+zip"
PACKAGE_EXPORTER_VERSION = "frameflow-api.v1"
PACKAGE_MAX_BYTES = 20 * 1024 * 1024
PACKAGE_MAX_FILES = 32
PACKAGE_MAX_COMPRESSION_RATIO = 100

MANIFEST_PATH = "manifest.json"
DOCUMENT_PATH = "canvas/document.json"
CONTRACT_PATH = "canvas/contract.json"
CHECKSUMS_PATH = "checksums.json"
PACKAGE_PATHS = frozenset({MANIFEST_PATH, DOCUMENT_PATH, CONTRACT_PATH, CHECKSUMS_PATH})

LOCAL_REFERENCE_CONFIG_FIELDS = frozenset({"artifact_id", "character_id", "format_id"})
SECRET_KEY_NAMES = frozenset({
    "apikey",
    "authorization",
    "credential",
    "credentials",
    "password",
    "privatekey",
    "secret",
    "secretkey",
    "token",
})
SIGNED_URL_QUERY_KEYS = frozenset({
    "awsaccesskeyid",
    "googleaccessid",
    "keypairid",
    "signature",
    "xamzcredential",
    "xamzsecuritytoken",
    "xamzsignature",
    "xgoogcredential",
    "xgoogsignature",
})


class CanvasPackageError(ValueError):
    pass


@dataclass(frozen=True)
class ImportedCanvasPackage:
    name: str
    document: dict[str, Any]
    draft_contract: dict[str, Any]
    warnings: list[str]
    source: dict[str, Any]


def _canonical_json(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _normalized_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _assert_portable_value(value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = _normalized_key(str(key))
            if normalized in SECRET_KEY_NAMES or normalized.endswith(("accesskey", "apikey", "credential", "password", "privatekey", "secret", "token")):
                raise CanvasPackageError(f"Secret-like field cannot be exported: {path}.{key}")
            _assert_portable_value(item, f"{path}.{key}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _assert_portable_value(item, f"{path}[{index}]")
        return
    if not isinstance(value, str) or not value.startswith(("http://", "https://")):
        return
    query_keys = {_normalized_key(key) for key, _ in parse_qsl(urlparse(value).query, keep_blank_values=True)}
    if query_keys & SIGNED_URL_QUERY_KEYS:
        raise CanvasPackageError(f"Signed URL cannot be exported: {path}")


def _template_contract(raw_contract: dict[str, Any] | None) -> tuple[dict[str, Any], list[str]]:
    contract = deepcopy(raw_contract or {
        "schema_version": "workflow.contract.draft.v1",
        "inputs": [],
        "bindings": [],
        "outputs": [],
    })
    warnings: list[str] = []
    for definition in contract.get("inputs") or []:
        if definition.get("type") not in {"artifact", "character"} or not definition.get("default"):
            continue
        definition.pop("default", None)
        definition["required"] = True
        warnings.append(f"Local default removed from Workflow input: {definition.get('key') or '<unknown>'}")
    _assert_portable_value(contract, "$.canvas.contract")
    return contract, warnings


def _template_document(raw_document: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    graph = canonical_canvas_graph(raw_document)
    if graph.get("schema_version") != CANVAS_GRAPH_SCHEMA_VERSION:
        raise CanvasPackageError("Canvas graph is not canonical")
    warnings: list[str] = []
    for node in graph.get("nodes") or []:
        config = dict(node.get("config") or {})
        for key in LOCAL_REFERENCE_CONFIG_FIELDS:
            if config.get(key):
                warnings.append(f"Local {key} cleared from Node {node.get('id')}")
                config[key] = ""
        node["config"] = config
    document = {
        "schema_version": CANVAS_DOCUMENT_SCHEMA_VERSION,
        "graph": graph,
        "runtime": {"schema_version": CANVAS_RUNTIME_SCHEMA_VERSION, "nodes": {}},
    }
    _assert_portable_value(document, "$.canvas.document")
    return document, warnings


def _package_requirements(document: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    node_contracts: dict[tuple[str, int, str], dict[str, Any]] = {}
    skills: dict[tuple[str, str], dict[str, str]] = {}
    for node in (document.get("graph") or {}).get("nodes") or []:
        type_key = str(node.get("type_key") or "")
        contract_version = int(node.get("contract_version") or 1)
        digest = str(node.get("definition_digest") or "")
        node_contracts[(type_key, contract_version, digest)] = {
            "type_key": type_key,
            "contract_version": contract_version,
            "definition_digest": digest,
        }
        if type_key == "skill.execute":
            config = dict(node.get("config") or {})
            skill_id = str(config.get("skill_id") or "")
            skill_version = str(config.get("skill_version") or "")
            if skill_id:
                skills[(skill_id, skill_version)] = {"skill_id": skill_id, "skill_version": skill_version}
    return {
        "node_contracts": [node_contracts[key] for key in sorted(node_contracts)],
        "skills": [skills[key] for key in sorted(skills)],
    }


def _zip_entry(name: str, content: bytes) -> tuple[zipfile.ZipInfo, bytes]:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    return info, content


def export_canvas_template(
    *,
    canvas_id: str,
    name: str,
    revision: int,
    graph_document: dict[str, Any],
    draft_contract: dict[str, Any] | None,
) -> bytes:
    document, graph_warnings = _template_document(graph_document)
    contract, contract_warnings = _template_contract(draft_contract)
    warnings = [*graph_warnings, *contract_warnings]
    manifest = {
        "schema_version": PACKAGE_SCHEMA_VERSION,
        "package_kind": PACKAGE_KIND,
        "exporter_version": PACKAGE_EXPORTER_VERSION,
        "source": {"canvas_id": canvas_id, "name": name, "revision": revision},
        "requirements": _package_requirements(document),
        "warnings": warnings,
        "files": [DOCUMENT_PATH, CONTRACT_PATH],
    }
    files = {
        MANIFEST_PATH: _canonical_json(manifest),
        DOCUMENT_PATH: _canonical_json(document),
        CONTRACT_PATH: _canonical_json(contract),
    }
    checksums = {path: _sha256(content) for path, content in sorted(files.items())}
    files[CHECKSUMS_PATH] = _canonical_json({"schema_version": "frameflow.checksums.v1", "files": checksums})
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as package:
        for path in (MANIFEST_PATH, DOCUMENT_PATH, CONTRACT_PATH, CHECKSUMS_PATH):
            package.writestr(*_zip_entry(path, files[path]))
    return archive.getvalue()


def _read_json(files: dict[str, bytes], path: str) -> dict[str, Any]:
    try:
        value = json.loads(files[path])
    except (KeyError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise CanvasPackageError(f"Invalid package JSON: {path}") from exc
    if not isinstance(value, dict):
        raise CanvasPackageError(f"Package JSON must be an object: {path}")
    return value


def _safe_package_files(content: bytes) -> dict[str, bytes]:
    if not content:
        raise CanvasPackageError("Canvas package is empty")
    if len(content) > PACKAGE_MAX_BYTES:
        raise CanvasPackageError("Canvas package exceeds the 20 MB template limit")
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as exc:
        raise CanvasPackageError("Canvas package is not a valid ZIP archive") from exc
    with archive:
        infos = archive.infolist()
        if len(infos) > PACKAGE_MAX_FILES:
            raise CanvasPackageError("Canvas package contains too many files")
        names: set[str] = set()
        total_size = 0
        for info in infos:
            path = PurePosixPath(info.filename)
            if info.is_dir() or path.is_absolute() or ".." in path.parts or str(path) != info.filename:
                raise CanvasPackageError(f"Unsafe package path: {info.filename}")
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise CanvasPackageError(f"Package symlink is not allowed: {info.filename}")
            if info.filename in names:
                raise CanvasPackageError(f"Duplicate package path: {info.filename}")
            names.add(info.filename)
            total_size += info.file_size
            if total_size > PACKAGE_MAX_BYTES:
                raise CanvasPackageError("Canvas package expands beyond the 20 MB template limit")
            if info.file_size > 1_000_000 and info.file_size > max(1, info.compress_size) * PACKAGE_MAX_COMPRESSION_RATIO:
                raise CanvasPackageError(f"Canvas package compression ratio is unsafe: {info.filename}")
        if names != PACKAGE_PATHS:
            missing = sorted(PACKAGE_PATHS - names)
            extra = sorted(names - PACKAGE_PATHS)
            detail = ", ".join([*(f"missing {item}" for item in missing), *(f"unexpected {item}" for item in extra)])
            raise CanvasPackageError(f"Canvas package file set is invalid: {detail}")
        return {info.filename: archive.read(info) for info in infos}


def _validate_checksums(files: dict[str, bytes]) -> None:
    checksums = _read_json(files, CHECKSUMS_PATH)
    if checksums.get("schema_version") != "frameflow.checksums.v1":
        raise CanvasPackageError("Unsupported package checksum schema")
    if not isinstance(checksums.get("files"), dict):
        raise CanvasPackageError("Package checksums must be an object")
    expected = dict(checksums["files"])
    checked_paths = PACKAGE_PATHS - {CHECKSUMS_PATH}
    if set(expected) != checked_paths:
        raise CanvasPackageError("Package checksum file set does not match the package")
    for path in checked_paths:
        if str(expected.get(path) or "") != _sha256(files[path]):
            raise CanvasPackageError(f"Package checksum mismatch: {path}")


def _object_list(value: Any, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise CanvasPackageError(f"{label} must be an array of objects")
    return deepcopy(value)


def _migrate_imported_document(document: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    if document.get("schema_version") != CANVAS_DOCUMENT_SCHEMA_VERSION:
        raise CanvasPackageError("Unsupported Canvas document schema")
    if not isinstance(document.get("graph"), dict):
        raise CanvasPackageError("Canvas graph must be an object")
    graph = deepcopy(document["graph"])
    if graph.get("schema_version") != CANVAS_GRAPH_SCHEMA_VERSION:
        raise CanvasPackageError("Unsupported Canvas graph schema")
    runtime = document.get("runtime")
    if not isinstance(runtime, dict) or runtime.get("schema_version") != CANVAS_RUNTIME_SCHEMA_VERSION:
        raise CanvasPackageError("Unsupported Canvas Runtime schema")
    if runtime.get("nodes"):
        raise CanvasPackageError("Canvas template package must not contain Runtime state")
    nodes = _object_list(graph.get("nodes"), "Canvas nodes")
    elements = _object_list(graph.get("elements"), "Canvas elements")
    edges = _object_list(graph.get("edges"), "Canvas edges")
    ids = [str(item.get("id") or "") for item in [*nodes, *elements]]
    if any(not item for item in ids) or len(ids) != len(set(ids)):
        raise CanvasPackageError("Imported Canvas IDs must be present and unique")
    known_ids = set(ids)
    if any(str(edge.get("source") or "") not in known_ids or str(edge.get("target") or "") not in known_ids for edge in edges):
        raise CanvasPackageError("Imported Canvas edge references an unknown item")

    warnings: list[str] = []
    for node in nodes:
        type_key = str(node.get("type_key") or "")
        try:
            contract_version = int(node.get("contract_version") or 1)
        except (TypeError, ValueError) as exc:
            raise CanvasPackageError(f"Invalid Node contract version: {type_key or '<unknown>'}") from exc
        definition = node_registry.get(type_key, contract_version)
        if not definition:
            node["unknown"] = True
            warnings.append(f"Node Definition is not installed and was preserved read-only: {type_key}@{contract_version}")
            continue
        if definition.lifecycle == "BLOCKED":
            raise CanvasPackageError(f"Blocked Node cannot be imported: {type_key}@{contract_version}")
        if definition.lifecycle in {"DEPRECATED", "RETIRED"}:
            warnings.append(f"Imported Node is {definition.lifecycle}: {type_key}@{contract_version}")
        incoming_digest = str(node.get("definition_digest") or "")
        if incoming_digest != definition.definition_digest:
            warnings.append(f"Node Definition metadata updated for Draft import: {type_key}@{contract_version}")
            node["definition_digest"] = definition.definition_digest
        try:
            node["config"] = node_registry.resolve_config(definition, dict(node.get("config") or {}))
        except ValueError as exc:
            raise CanvasPackageError(f"Invalid imported Node config for {type_key}@{contract_version}: {exc}") from exc
        node.pop("unknown", None)
    migrated = {
        "schema_version": CANVAS_DOCUMENT_SCHEMA_VERSION,
        "graph": {**graph, "nodes": nodes, "elements": elements, "edges": edges},
        "runtime": {"schema_version": CANVAS_RUNTIME_SCHEMA_VERSION, "nodes": {}},
    }
    _assert_portable_value(migrated, "$.canvas.document")
    return migrated, warnings


def import_canvas_template(content: bytes) -> ImportedCanvasPackage:
    files = _safe_package_files(content)
    _validate_checksums(files)
    manifest = _read_json(files, MANIFEST_PATH)
    if manifest.get("schema_version") != PACKAGE_SCHEMA_VERSION or manifest.get("package_kind") != PACKAGE_KIND:
        raise CanvasPackageError("Unsupported Frameflow package")
    if not isinstance(manifest.get("files"), list) or any(not isinstance(item, str) for item in manifest["files"]):
        raise CanvasPackageError("Package manifest files must be an array of paths")
    if set(manifest["files"]) != {DOCUMENT_PATH, CONTRACT_PATH}:
        raise CanvasPackageError("Package manifest file list is invalid")
    if not isinstance(manifest.get("source"), dict) or not isinstance(manifest.get("requirements"), dict):
        raise CanvasPackageError("Package manifest source and requirements must be objects")
    if not isinstance(manifest.get("warnings"), list) or any(not isinstance(item, str) for item in manifest["warnings"]):
        raise CanvasPackageError("Package manifest warnings must be an array of strings")
    document, migration_warnings = _migrate_imported_document(_read_json(files, DOCUMENT_PATH))
    contract = _read_json(files, CONTRACT_PATH)
    if contract.get("schema_version") != "workflow.contract.draft.v1":
        raise CanvasPackageError("Unsupported Workflow draft contract schema")
    for key in ("inputs", "bindings", "outputs"):
        _object_list(contract.get(key), f"Workflow contract {key}")
    _assert_portable_value(contract, "$.canvas.contract")
    source = dict(manifest["source"])
    name = str(source.get("name") or "Imported Canvas").strip()[:255] or "Imported Canvas"
    warnings = list(manifest["warnings"])
    warnings.extend(migration_warnings)
    return ImportedCanvasPackage(
        name=name,
        document=document,
        draft_contract=contract,
        warnings=list(dict.fromkeys(warnings)),
        source=source,
    )
