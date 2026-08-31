from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .database import (
    ArtifactRecord,
    CanvasRecord,
    WorkflowAnnotationRecord,
    WorkflowDefinitionRecord,
    WorkflowVersionRecord,
)
from .domain import (
    WorkflowAnnotationCreateRequest,
    WorkflowAnnotationUpdateRequest,
    WorkflowCreateRequest,
    WorkflowPublishRequest,
    WorkflowUpdateRequest,
    WorkflowVersionRunRequest,
    CanvasRunRequest,
    utc_now,
)
from .nodes import node_registry
from .nodes.inventory import canvas_only_keys
from .nodes.port_types import port_type_registry
from .service import audit, new_id


WORKFLOW_COMPILER_VERSION = "workflow-compiler.v1"
INPUT_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
DEFAULT_DRAFT_CONTRACT = {
    "schema_version": "workflow.contract.draft.v1",
    "inputs": [],
    "bindings": [],
    "outputs": [],
}

LEGACY_CONFIG_FIELDS = {
    "resolution": "resolution",
    "aspectRatio": "aspect_ratio",
    "batchSize": "output_count",
    "characterName": "character_name",
    "shotCount": "shot_count",
    "durationSeconds": "duration_seconds",
    "loraUrl": "lora_url",
    "loraScale": "lora_scale",
    "triggerWord": "trigger_word",
    "transition": "transition",
    "targetDurationSeconds": "target_duration_seconds",
    "sourceLanguage": "source_language",
    "separateMusic": "separate_music",
    "sceneThreshold": "scene_threshold",
    "motionSampleFps": "motion_sample_fps",
    "motionMaxWidth": "motion_max_width",
    "motionMinConfidence": "motion_min_confidence",
    "motionFaceBlendshapes": "motion_face_blendshapes",
    "targetLanguage": "target_language",
    "voiceName": "voice_name",
    "captionX": "caption_x",
    "captionY": "caption_y",
    "captionAlign": "caption_align",
    "captionFontSize": "caption_font_size",
    "skillId": "skill_id",
}


class WorkflowContractError(ValueError):
    pass


@dataclass(frozen=True)
class CompiledWorkflowVersion:
    graph: dict[str, Any]
    input_schema: dict[str, Any]
    bindings: dict[str, Any]
    output_schema: dict[str, Any]
    content_hash: str
    annotations: list[dict[str, Any]]
    warnings: list[str]


def workflow_definition_payload(record: WorkflowDefinitionRecord, db: Session) -> dict[str, Any]:
    versions = db.scalars(
        select(WorkflowVersionRecord)
        .where(WorkflowVersionRecord.workflow_definition_id == record.id)
        .order_by(WorkflowVersionRecord.version_number.desc())
    ).all()
    return {
        "id": record.id,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "name": record.name,
        "description": record.description,
        "status": record.status,
        "draft_canvas_id": record.draft_canvas_id,
        "current_version_id": record.current_version_id,
        "current_version_number": next((item.version_number for item in versions if item.id == record.current_version_id), None),
        "version_count": len(versions),
        "tags": record.tags or [],
    }


def workflow_version_payload(record: WorkflowVersionRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "created_at": record.created_at,
        "workflow_definition_id": record.workflow_definition_id,
        "version_number": record.version_number,
        "schema_version": record.schema_version,
        "graph": record.graph_json or {},
        "input_schema": record.input_schema_json or {},
        "bindings": record.bindings_json or {},
        "output_schema": record.output_schema_json or {},
        "content_hash": record.content_hash,
        "source_canvas_id": record.source_canvas_id,
        "source_canvas_revision": record.source_canvas_revision,
        "release_notes": record.release_notes,
        "published_by": record.published_by,
        "published_at": record.published_at,
    }


def workflow_annotation_payload(record: WorkflowAnnotationRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "workflow_definition_id": record.workflow_definition_id,
        "workflow_version_id": record.workflow_version_id,
        "node_id": record.node_id,
        "body": record.body,
        "position": record.position_json or {},
        "color": record.color,
        "revision": record.revision,
        "created_by": record.created_by,
        "updated_by": record.updated_by,
    }


def create_workflow_definition(db: Session, payload: WorkflowCreateRequest) -> WorkflowDefinitionRecord:
    if payload.source_canvas_id:
        canvas = db.get(CanvasRecord, payload.source_canvas_id)
        if not canvas:
            raise WorkflowContractError("source Canvas was not found")
        if canvas.workflow_definition_id:
            raise WorkflowContractError("source Canvas already belongs to a Workflow")
    else:
        canvas = CanvasRecord(
            id=new_id("canvas"),
            name=payload.name,
            graph_json={"nodes": [], "edges": []},
            active_run_id=None,
            revision=1,
            draft_contract_json=deepcopy(DEFAULT_DRAFT_CONTRACT),
            updated_at=utc_now(),
        )
        db.add(canvas)
        db.flush()
    definition = WorkflowDefinitionRecord(
        id=new_id("workflow"),
        name=payload.name,
        description=payload.description,
        status="ACTIVE",
        draft_canvas_id=canvas.id,
        current_version_id=None,
        tags=list(dict.fromkeys(payload.tags)),
        updated_at=utc_now(),
    )
    db.add(definition)
    db.flush()
    canvas.workflow_definition_id = definition.id
    if not canvas.draft_contract_json:
        canvas.draft_contract_json = deepcopy(DEFAULT_DRAFT_CONTRACT)
    audit(db, "workflow.created", definition.id, {"draft_canvas_id": canvas.id})
    db.commit()
    db.refresh(definition)
    return definition


def update_workflow_definition(db: Session, record: WorkflowDefinitionRecord, payload: WorkflowUpdateRequest) -> WorkflowDefinitionRecord:
    if payload.name is not None:
        record.name = payload.name
    if payload.description is not None:
        record.description = payload.description
    if payload.tags is not None:
        record.tags = list(dict.fromkeys(payload.tags))
    record.updated_at = utc_now()
    audit(db, "workflow.updated", record.id)
    db.commit()
    db.refresh(record)
    return record


def _legacy_config(data: dict[str, Any], type_key: str) -> dict[str, Any]:
    config = dict(data.get("config") or data.get("parameters") or {})
    for source, target in LEGACY_CONFIG_FIELDS.items():
        if target not in config and data.get(source) is not None:
            config[target] = data[source]
    if type_key in {"prompt.input", "generation.brief"}:
        config.setdefault("text", str(data.get("configText") or ""))
    if type_key == "asset.select":
        artifact_ids = list(data.get("outputArtifactIds") or [])
        config.setdefault("artifact_id", str(data.get("configText") or (artifact_ids[0] if artifact_ids else "")))
        config.setdefault("artifact_type", str(data.get("outputType") or "ReferenceAsset"))
    if type_key == "character.select":
        artifact_ids = list(data.get("outputArtifactIds") or [])
        config.setdefault("character_id", str(data.get("configText") or (artifact_ids[0] if artifact_ids else "")))
    if type_key == "format.profile":
        config.setdefault("format_id", str(data.get("configText") or ""))
    return config


def _logical_model_alias(data: dict[str, Any], default_alias: str, provider: str) -> str:
    value = str(data.get("model") or default_alias)
    if value.startswith(("google.", "openai.", "fal.", "local.", "reference-analysis.")):
        return value
    selected_provider = str(data.get("provider") or provider or "google")
    return f"{selected_provider}.{value}" if selected_provider in {"google", "openai", "fal"} else value


def _normalize_contract(raw: dict[str, Any] | None) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    contract = raw or DEFAULT_DRAFT_CONTRACT
    inputs = list(contract.get("inputs") or [])
    bindings = list(contract.get("bindings") or [])
    outputs = list(contract.get("outputs") or [])
    input_keys: set[str] = set()
    for item in inputs:
        key = str(item.get("key") or "")
        if not INPUT_KEY_PATTERN.fullmatch(key):
            raise WorkflowContractError(f"invalid Workflow input key: {key or '<empty>'}")
        if key in input_keys:
            raise WorkflowContractError(f"duplicate Workflow input key: {key}")
        if item.get("required") is True and "default" in item:
            raise WorkflowContractError(f"required Workflow input cannot have a default: {key}")
        input_keys.add(key)
    return (
        {"schema_version": "workflow.inputs.v1", "inputs": inputs},
        {"schema_version": "workflow.bindings.v1", "bindings": bindings},
        {"schema_version": "workflow.outputs.v1", "outputs": outputs},
    )


def _validate_bindings(bindings: dict[str, Any], input_schema: dict[str, Any], nodes: dict[str, dict[str, Any]]) -> None:
    input_definitions = {str(item["key"]): item for item in input_schema["inputs"]}
    input_keys = set(input_definitions)
    targets: set[tuple[str, str]] = set()
    for binding in bindings["bindings"]:
        target = dict(binding.get("target") or {})
        node_id = str(target.get("node_id") or "")
        path = str(target.get("path") or "")
        if node_id not in nodes or not path.startswith("/config/"):
            raise WorkflowContractError(f"invalid Workflow binding target: {node_id}{path}")
        property_name = path.removeprefix("/config/")
        definition = node_registry.get(nodes[node_id]["type_key"], int(nodes[node_id]["contract_version"]))
        field = dict((definition.config_schema.get("properties") or {}).get(property_name) or {}) if definition else {}
        if not (field.get("x-workflow-input") or {}).get("enabled"):
            raise WorkflowContractError(f"Node field is not exposed as a Workflow input: {node_id}{path}")
        target_key = (node_id, path)
        if target_key in targets:
            raise WorkflowContractError(f"duplicate Workflow binding target: {node_id}{path}")
        targets.add(target_key)
        value = dict(binding.get("value") or {})
        referenced = [str(value.get("key") or "")] if value.get("kind") == "input" else [str(item) for item in value.get("input_keys") or []]
        unknown = [key for key in referenced if key not in input_keys]
        if unknown:
            raise WorkflowContractError(f"Workflow binding references unknown inputs: {', '.join(unknown)}")
        if value.get("kind") == "input" and referenced:
            expected_type = str((field.get("x-workflow-input") or {}).get("type") or "")
            actual_type = str(input_definitions[referenced[0]].get("type") or "")
            compatible = actual_type == expected_type or (expected_type == "number" and actual_type == "integer")
            if not compatible:
                raise WorkflowContractError(f"Workflow input type {actual_type} is incompatible with {node_id}{path} ({expected_type})")
        elif value.get("kind") == "template":
            if field.get("type") != "string":
                raise WorkflowContractError(f"Template binding requires a string field: {node_id}{path}")
            template = str(value.get("template") or "")
            missing_tokens = [key for key in referenced if f"{{{{{key}}}}}" not in template]
            if missing_tokens:
                raise WorkflowContractError(f"Template binding is missing tokens: {', '.join(missing_tokens)}")
        else:
            raise WorkflowContractError("unsupported Workflow binding expression")


def _assert_acyclic(node_ids: set[str], edges: list[dict[str, Any]]) -> None:
    indegree = {node_id: 0 for node_id in node_ids}
    outgoing = {node_id: [] for node_id in node_ids}
    for edge in edges:
        source, target = str(edge.get("source") or ""), str(edge.get("target") or "")
        if source not in node_ids or target not in node_ids:
            raise WorkflowContractError("Canvas edge references an unknown Node")
        outgoing[source].append(target)
        indegree[target] += 1
    queue = [node_id for node_id, count in indegree.items() if count == 0]
    visited = 0
    while queue:
        source = queue.pop()
        visited += 1
        for target in outgoing[source]:
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)
    if visited != len(node_ids):
        raise WorkflowContractError("Canvas graph contains a cycle")


def compile_canvas_version(db: Session, canvas: CanvasRecord) -> CompiledWorkflowVersion:
    raw_graph = canvas.graph_json or {}
    raw_nodes = list(raw_graph.get("nodes") or [])
    raw_edges = list(raw_graph.get("edges") or [])
    raw_ids = [str(node.get("id") or "") for node in raw_nodes]
    if any(not node_id for node_id in raw_ids) or len(raw_ids) != len(set(raw_ids)):
        raise WorkflowContractError("Canvas Node IDs must be present and unique")
    _assert_acyclic(set(raw_ids), raw_edges)

    annotations: list[dict[str, Any]] = []
    canonical_by_id: dict[str, dict[str, Any]] = {}
    for raw_node in raw_nodes:
        node_id = str(raw_node["id"])
        data = dict(raw_node.get("data") or {})
        type_key = str(data.get("key") or "")
        if type_key in {"utility.sticky", "utility.text"}:
            annotations.append({
                "body": str(data.get("configText") or data.get("description") or "").strip() or "Memo",
                "position": dict(raw_node.get("position") or {}),
                "color": str(data.get("stickyColor") or "yellow"),
            })
            continue
        if type_key == "folder.group":
            continue
        if type_key in {"asset.upload", "utility.drawing"}:
            artifact_ids = list(data.get("outputArtifactIds") or [])
            if not artifact_ids:
                raise WorkflowContractError(f"{type_key} must be saved as an Artifact before Publish")
            type_key = "asset.select"
            data = {
                **data,
                "key": type_key,
                "configText": str(artifact_ids[0]),
                "outputArtifactIds": artifact_ids,
                "outputType": data.get("outputType") or ("Image" if str(data.get("key")) == "utility.drawing" else "ReferenceAsset"),
            }
        if type_key in canvas_only_keys():
            continue
        contract_version = int(data.get("contractVersion") or 1)
        definition = node_registry.get(type_key, contract_version)
        if not definition:
            raise WorkflowContractError(f"Node Definition was not found: {type_key}@{contract_version}")
        if definition.lifecycle in {"RETIRED", "BLOCKED"}:
            raise WorkflowContractError(f"Node cannot be published: {type_key}@{contract_version} is {definition.lifecycle}")
        config = node_registry.resolve_config(definition, _legacy_config(data, type_key))
        if type_key == "asset.select" and config.get("artifact_id"):
            if not db.get(ArtifactRecord, str(config["artifact_id"])):
                raise WorkflowContractError(f"input Artifact was not found: {config['artifact_id']}")
        if type_key == "character.select" and config.get("character_id"):
            if not db.get(ArtifactRecord, str(config["character_id"])):
                raise WorkflowContractError(f"Character Artifact was not found: {config['character_id']}")
        canonical_by_id[node_id] = {
            "id": node_id,
            "type_key": type_key,
            "contract_version": contract_version,
            "definition_digest": definition.definition_digest,
            "config": config,
            "runtime": {
                "model_alias": _logical_model_alias(data, definition.execution.model_alias, definition.execution.provider),
                "provider": str(data.get("provider") or definition.execution.provider),
            },
            "ui": {
                "position": dict(raw_node.get("position") or {}),
                "label": str(data.get("label") or definition.display.label),
                "description": str(data.get("description") or definition.display.description),
            },
        }

    input_schema, bindings, output_schema = _normalize_contract(canvas.draft_contract_json)
    outputs = output_schema["outputs"]
    primary = [item for item in outputs if item.get("primary") is True]
    if len(primary) != 1:
        raise WorkflowContractError("Workflow must declare exactly one Primary output")
    output_ids = {str(item.get("node_id") or "") for item in outputs}
    if not output_ids or not output_ids <= set(canonical_by_id):
        raise WorkflowContractError("Workflow output references a missing or Canvas-only Node")

    canonical_edges = [
        {
            "id": str(edge.get("id") or f"{edge.get('source')}->{edge.get('target')}"),
            "source": str(edge.get("source")),
            "target": str(edge.get("target")),
            "source_port": edge.get("sourceHandle"),
            "target_port": edge.get("targetHandle"),
        }
        for edge in raw_edges
        if str(edge.get("source")) in canonical_by_id and str(edge.get("target")) in canonical_by_id
    ]
    incoming: dict[str, list[str]] = {node_id: [] for node_id in canonical_by_id}
    for edge in canonical_edges:
        incoming[edge["target"]].append(edge["source"])
    reachable = set(output_ids)
    queue = list(output_ids)
    while queue:
        target = queue.pop()
        for source in incoming.get(target, []):
            if source not in reachable:
                reachable.add(source)
                queue.append(source)
    warnings = [f"Unused Canvas Node excluded: {node_id}" for node_id in canonical_by_id if node_id not in reachable]
    graph = {
        "schema_version": "workflow.graph.v1",
        "nodes": [canonical_by_id[node_id] for node_id in raw_ids if node_id in reachable],
        "edges": [edge for edge in canonical_edges if edge["source"] in reachable and edge["target"] in reachable],
    }
    graph_nodes = {node["id"]: node for node in graph["nodes"]}
    _validate_bindings(bindings, input_schema, graph_nodes)
    for output in outputs:
        node = graph_nodes[str(output["node_id"])]
        definition = node_registry.get(node["type_key"], int(node["contract_version"]))
        requested_type = str(output.get("port_type") or "")
        allowed_types = {
            port.type for port in definition.ports.outputs
        } | {
            port_type_registry.get(port.type).legacy_type for port in definition.ports.outputs if port_type_registry.get(port.type)
        }
        if requested_type and requested_type not in allowed_types:
            raise WorkflowContractError(f"Workflow output type does not match Node contract: {output.get('key')}")

    version_document = {
        "schema_version": "workflow.version.v1",
        "compiler_version": WORKFLOW_COMPILER_VERSION,
        "graph": graph,
        "input_schema": input_schema,
        "bindings": bindings,
        "output_schema": output_schema,
    }
    canonical = json.dumps(version_document, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return CompiledWorkflowVersion(
        graph=graph,
        input_schema=input_schema,
        bindings=bindings,
        output_schema=output_schema,
        content_hash=hashlib.sha256(canonical.encode()).hexdigest(),
        annotations=annotations,
        warnings=warnings,
    )


def publish_workflow_version(db: Session, definition_id: str, payload: WorkflowPublishRequest) -> tuple[WorkflowVersionRecord, list[str]]:
    definition = db.scalar(
        select(WorkflowDefinitionRecord).where(WorkflowDefinitionRecord.id == definition_id).with_for_update()
    )
    if not definition:
        raise WorkflowContractError("Workflow was not found")
    if definition.status != "ACTIVE":
        raise WorkflowContractError("Archived Workflow cannot be published")
    canvas = db.get(CanvasRecord, definition.draft_canvas_id)
    if not canvas or canvas.workflow_definition_id != definition.id:
        raise WorkflowContractError("Workflow Draft Canvas is missing")
    if canvas.revision != payload.expected_canvas_revision:
        raise WorkflowContractError(f"Canvas revision conflict: expected {payload.expected_canvas_revision}, current {canvas.revision}")
    existing = db.scalar(select(WorkflowVersionRecord).where(
        WorkflowVersionRecord.workflow_definition_id == definition.id,
        WorkflowVersionRecord.source_canvas_id == canvas.id,
        WorkflowVersionRecord.source_canvas_revision == canvas.revision,
    ))
    if existing:
        return existing, []
    compiled = compile_canvas_version(db, canvas)
    next_version = int(db.scalar(select(func.max(WorkflowVersionRecord.version_number)).where(
        WorkflowVersionRecord.workflow_definition_id == definition.id
    )) or 0) + 1
    version = WorkflowVersionRecord(
        id=new_id("workflowver"),
        workflow_definition_id=definition.id,
        version_number=next_version,
        schema_version="workflow.version.v1",
        graph_json=compiled.graph,
        input_schema_json=compiled.input_schema,
        bindings_json=compiled.bindings,
        output_schema_json=compiled.output_schema,
        content_hash=compiled.content_hash,
        source_canvas_id=canvas.id,
        source_canvas_revision=canvas.revision,
        release_notes=payload.release_notes,
        published_by=payload.published_by,
        published_at=utc_now(),
    )
    db.add(version)
    db.flush()
    for annotation in compiled.annotations:
        db.add(WorkflowAnnotationRecord(
            id=new_id("annotation"),
            workflow_definition_id=definition.id,
            workflow_version_id=version.id,
            node_id=None,
            body=annotation["body"],
            position_json=annotation["position"],
            color=annotation["color"],
            revision=1,
            created_by=payload.published_by,
            updated_by=payload.published_by,
            updated_at=utc_now(),
        ))
    definition.current_version_id = version.id
    definition.updated_at = utc_now()
    canvas.base_version_id = version.id
    audit(db, "workflow.published", definition.id, {
        "version_id": version.id,
        "version_number": version.version_number,
        "content_hash": version.content_hash,
        "warnings": compiled.warnings,
    })
    db.commit()
    db.refresh(version)
    return version, compiled.warnings


def _validate_workflow_input(db: Session, definition: dict[str, Any], value: Any) -> Any:
    input_type = str(definition.get("type") or "string")
    validation = dict(definition.get("validation") or {})
    if input_type in {"string", "prompt", "enum", "model_alias", "artifact", "character"} and not isinstance(value, str):
        raise WorkflowContractError(f"Workflow input {definition['key']} must be a string")
    if input_type == "integer" and (not isinstance(value, int) or isinstance(value, bool)):
        raise WorkflowContractError(f"Workflow input {definition['key']} must be an integer")
    if input_type == "number" and (not isinstance(value, (int, float)) or isinstance(value, bool)):
        raise WorkflowContractError(f"Workflow input {definition['key']} must be a number")
    if input_type == "boolean" and not isinstance(value, bool):
        raise WorkflowContractError(f"Workflow input {definition['key']} must be a boolean")
    options = definition.get("options") or validation.get("options")
    if options and value not in options:
        raise WorkflowContractError(f"Workflow input {definition['key']} must be one of {options}")
    if isinstance(value, str):
        if "min_length" in validation and len(value) < int(validation["min_length"]):
            raise WorkflowContractError(f"Workflow input {definition['key']} is too short")
        if "max_length" in validation and len(value) > int(validation["max_length"]):
            raise WorkflowContractError(f"Workflow input {definition['key']} is too long")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in validation and value < validation["minimum"]:
            raise WorkflowContractError(f"Workflow input {definition['key']} is below the minimum")
        if "maximum" in validation and value > validation["maximum"]:
            raise WorkflowContractError(f"Workflow input {definition['key']} exceeds the maximum")
    if input_type in {"artifact", "character"}:
        artifact = db.get(ArtifactRecord, value)
        if not artifact:
            raise WorkflowContractError(f"Workflow input Artifact was not found: {value}")
        if input_type == "character" and artifact.type != "Character":
            raise WorkflowContractError(f"Workflow input {definition['key']} requires a Character")
        allowed_types = set(validation.get("artifact_types") or [])
        if allowed_types and artifact.type not in allowed_types:
            raise WorkflowContractError(f"Workflow input {definition['key']} does not accept Artifact type {artifact.type}")
    return value


def resolve_workflow_inputs(db: Session, version: WorkflowVersionRecord, requested: dict[str, Any]) -> dict[str, Any]:
    definitions = list((version.input_schema_json or {}).get("inputs") or [])
    known = {str(item["key"]): item for item in definitions}
    unknown = sorted(set(requested) - set(known))
    if unknown:
        raise WorkflowContractError(f"unknown Workflow inputs: {', '.join(unknown)}")
    resolved: dict[str, Any] = {}
    for key, definition in known.items():
        if key in requested:
            value = requested[key]
        elif "default" in definition:
            value = definition["default"]
        elif definition.get("required") is True:
            raise WorkflowContractError(f"required Workflow input is missing: {key}")
        else:
            continue
        resolved[key] = _validate_workflow_input(db, definition, value)
    return resolved


def resolve_workflow_execution(
    db: Session,
    definition: WorkflowDefinitionRecord,
    version: WorkflowVersionRecord,
    payload: WorkflowVersionRunRequest,
) -> tuple[CanvasRunRequest, dict[str, Any], dict[str, Any]]:
    from .experiments import resolve_model

    resolved_inputs = resolve_workflow_inputs(db, version, payload.inputs)
    graph = deepcopy(version.graph_json or {})
    nodes = {str(node["id"]): node for node in graph.get("nodes", [])}
    for binding in (version.bindings_json or {}).get("bindings", []):
        target = dict(binding.get("target") or {})
        node = nodes[str(target["node_id"])]
        property_name = str(target["path"]).removeprefix("/config/")
        expression = dict(binding.get("value") or {})
        if expression.get("kind") == "input":
            value = resolved_inputs[str(expression["key"])]
        elif expression.get("kind") == "template":
            value = str(expression.get("template") or "")
            for key in expression.get("input_keys") or []:
                value = value.replace(f"{{{{{key}}}}}", str(resolved_inputs[str(key)]))
        else:
            raise WorkflowContractError("unsupported Workflow binding expression")
        node["config"][property_name] = value

    legacy_nodes: list[dict[str, Any]] = []
    model_snapshot: dict[str, Any] = {}
    for node in graph.get("nodes", []):
        type_key = str(node["type_key"])
        contract_version = int(node["contract_version"])
        node_definition = node_registry.get(type_key, contract_version)
        if not node_definition or node_definition.definition_digest != node.get("definition_digest"):
            raise WorkflowContractError(f"Node Definition digest is unavailable: {type_key}@{contract_version}")
        config = node_registry.resolve_config(node_definition, dict(node.get("config") or {}))
        runtime = dict(node.get("runtime") or {})
        model_alias = str(runtime.get("model_alias") or node_definition.execution.model_alias)
        legacy_inputs = [port_type_registry.get(port.type).legacy_type for port in node_definition.ports.inputs]
        required_inputs = [port_type_registry.get(port.type).legacy_type for port in node_definition.ports.inputs if port.required]
        multi_inputs = [port_type_registry.get(port.type).legacy_type for port in node_definition.ports.inputs if port.multiple]
        output = node_definition.ports.outputs[0] if node_definition.ports.outputs else None
        data: dict[str, Any] = {
            "key": type_key,
            "label": str((node.get("ui") or {}).get("label") or node_definition.display.label),
            "description": str((node.get("ui") or {}).get("description") or node_definition.display.description),
            "kind": "input" if node_definition.execution.kind == "source" else "review" if node_definition.execution.kind == "human_gate" else "logic",
            "inputTypes": legacy_inputs,
            "requiredInputTypes": required_inputs,
            "multiInputTypes": multi_inputs,
            "outputType": port_type_registry.get(output.type).legacy_type if output else None,
            "model": model_alias,
            "provider": runtime.get("provider") or node_definition.execution.provider,
            "contractVersion": contract_version,
            "definitionDigest": node_definition.definition_digest,
            "config": config,
            "executable": node_definition.execution.kind != "source",
        }
        if node_definition.execution.kind == "human_gate" and type_key == "timeline.compose":
            data["waitForInput"] = True
        if type_key in {"prompt.input", "generation.brief"}:
            data["configText"] = str(config.get("text") or "")
        if type_key == "asset.select":
            artifact_id = str(config.get("artifact_id") or "")
            artifact = db.get(ArtifactRecord, artifact_id) if artifact_id else None
            if not artifact:
                raise WorkflowContractError(f"input Artifact was not found: {artifact_id}")
            data["configText"] = artifact.id
            data["outputArtifactIds"] = [artifact.id]
            data["outputType"] = artifact.type if artifact.type in {"Image", "Video", "Audio"} else data["outputType"]
            data["output"] = {"kind": artifact.type.lower() if artifact.type in {"Image", "Video", "Audio"} else "json", "title": str(artifact.metadata_json.get("filename") or artifact.id)}
        if type_key == "character.select":
            character_id = str(config.get("character_id") or "")
            character = db.get(ArtifactRecord, character_id) if character_id else None
            if not character or character.type != "Character":
                raise WorkflowContractError(f"Character Artifact was not found: {character_id}")
            data["configText"] = character.id
            data["outputArtifactIds"] = [character.id]
        if node_definition.execution.kind not in {"source", "human_gate"} or type_key == "timeline.compose":
            normalized_alias, exact_model_id = resolve_model(model_alias, type_key)
            model_snapshot[str(node["id"])] = {
                "type_key": type_key,
                "contract_version": contract_version,
                "definition_digest": node_definition.definition_digest,
                "model_alias": normalized_alias,
                "exact_model_id": exact_model_id,
            }
            data["model"] = normalized_alias
        legacy_nodes.append({
            "id": str(node["id"]),
            "type": "studio",
            "position": dict((node.get("ui") or {}).get("position") or {}),
            "data": data,
        })
    legacy_edges = [
        {
            "id": str(edge["id"]),
            "source": str(edge["source"]),
            "target": str(edge["target"]),
            "sourceHandle": edge.get("source_port"),
            "targetHandle": edge.get("target_port"),
        }
        for edge in graph.get("edges", [])
    ]
    return (
        CanvasRunRequest(
            canvas_id=version.source_canvas_id,
            name=f"{definition.name} · v{version.version_number}",
            nodes=legacy_nodes,
            edges=legacy_edges,
        ),
        resolved_inputs,
        model_snapshot,
    )


def create_annotation(
    db: Session,
    definition: WorkflowDefinitionRecord,
    payload: WorkflowAnnotationCreateRequest,
    *,
    version: WorkflowVersionRecord | None = None,
) -> WorkflowAnnotationRecord:
    if version and version.workflow_definition_id != definition.id:
        raise WorkflowContractError("Workflow Version does not belong to the Workflow")
    if payload.node_id and version:
        node_ids = {str(node.get("id")) for node in (version.graph_json or {}).get("nodes", [])}
        if payload.node_id not in node_ids:
            raise WorkflowContractError("Annotation Node does not exist in the Frozen Version")
    record = WorkflowAnnotationRecord(
        id=new_id("annotation"),
        workflow_definition_id=definition.id,
        workflow_version_id=version.id if version else None,
        node_id=payload.node_id,
        body=payload.body,
        position_json=dict(payload.position),
        color=payload.color,
        revision=1,
        created_by=payload.actor_id,
        updated_by=payload.actor_id,
        updated_at=utc_now(),
    )
    db.add(record)
    audit(db, "workflow.annotation_created", record.id, {"workflow_version_id": record.workflow_version_id})
    db.commit()
    db.refresh(record)
    return record


def update_annotation(db: Session, record: WorkflowAnnotationRecord, payload: WorkflowAnnotationUpdateRequest) -> WorkflowAnnotationRecord:
    if record.deleted_at:
        raise WorkflowContractError("Workflow Annotation was deleted")
    if record.revision != payload.expected_revision:
        raise WorkflowContractError(f"Annotation revision conflict: expected {payload.expected_revision}, current {record.revision}")
    if payload.body is not None:
        record.body = payload.body
    if payload.position is not None:
        record.position_json = dict(payload.position)
    if payload.color is not None:
        record.color = payload.color
    record.revision += 1
    record.updated_by = payload.actor_id
    record.updated_at = utc_now()
    audit(db, "workflow.annotation_updated", record.id, {"revision": record.revision})
    db.commit()
    db.refresh(record)
    return record


def delete_annotation(db: Session, record: WorkflowAnnotationRecord, actor_id: str = "local-user") -> None:
    if record.deleted_at:
        return
    record.deleted_at = utc_now()
    record.revision += 1
    record.updated_by = actor_id
    record.updated_at = utc_now()
    audit(db, "workflow.annotation_deleted", record.id, {"revision": record.revision})
    db.commit()
