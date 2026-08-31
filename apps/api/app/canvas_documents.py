from __future__ import annotations

from copy import deepcopy
from typing import Any

from .nodes import node_registry
from .nodes.inventory import canvas_only_keys
from .nodes.port_types import port_type_registry


CANVAS_DOCUMENT_SCHEMA_VERSION = "canvas.document.v1"
CANVAS_GRAPH_SCHEMA_VERSION = "canvas.graph.v1"
CANVAS_RUNTIME_SCHEMA_VERSION = "canvas.runtime.v1"

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

RUNTIME_DATA_FIELDS = frozenset({
    "status",
    "preview",
    "attemptCount",
    "lastRunAt",
    "logs",
    "output",
    "outputEdited",
    "lastExperimentId",
    "outputArtifactIds",
    "lastRequestHash",
    "executionMode",
    "lastCostUsd",
    "runProgress",
    "promptEdited",
})

CONTRACT_DERIVED_DATA_FIELDS = frozenset({
    "key",
    "label",
    "description",
    "icon",
    "kind",
    "inputTypes",
    "inputsRequired",
    "requiredInputTypes",
    "multiInputTypes",
    "outputType",
    "cost",
    "contractVersion",
    "definitionDigest",
    "config",
    "parameters",
    "model",
    "provider",
    "executable",
})

EPHEMERAL_REACT_FLOW_FIELDS = frozenset({
    "selected",
    "dragging",
    "measured",
    "width",
    "height",
    "positionAbsolute",
})


def is_canonical_canvas_document(document: dict[str, Any] | None) -> bool:
    return bool(document and document.get("schema_version") == CANVAS_DOCUMENT_SCHEMA_VERSION)


def legacy_node_config(data: dict[str, Any], type_key: str) -> dict[str, Any]:
    config = dict(data.get("config") or data.get("parameters") or {})
    definition = node_registry.get(type_key, int(data.get("contractVersion") or 1))
    prefer_legacy_fields = bool(definition and definition.editor.kind == "legacy")
    for source, target in LEGACY_CONFIG_FIELDS.items():
        if data.get(source) is not None and (prefer_legacy_fields or target not in config):
            config[target] = data[source]
    if type_key in {"prompt.input", "generation.brief"}:
        if prefer_legacy_fields or "text" not in config:
            config["text"] = str(data.get("configText") or "")
    if type_key == "asset.select":
        artifact_ids = list(data.get("outputArtifactIds") or [])
        if prefer_legacy_fields or "artifact_id" not in config:
            config["artifact_id"] = str(data.get("configText") or (artifact_ids[0] if artifact_ids else ""))
        if prefer_legacy_fields or "artifact_type" not in config:
            config["artifact_type"] = str(data.get("outputType") or "ReferenceAsset")
    if type_key == "character.select":
        artifact_ids = list(data.get("outputArtifactIds") or [])
        if prefer_legacy_fields or "character_id" not in config:
            config["character_id"] = str(data.get("configText") or (artifact_ids[0] if artifact_ids else ""))
    if type_key == "format.profile":
        if prefer_legacy_fields or "format_id" not in config:
            config["format_id"] = str(data.get("configText") or "")
    return config


def logical_model_alias(data: dict[str, Any], default_alias: str, provider: str) -> str:
    value = str(data.get("model") or default_alias)
    if value.startswith(("google.", "openai.", "fal.", "local.", "reference-analysis.")):
        return value
    selected_provider = str(data.get("provider") or provider or "google")
    return f"{selected_provider}.{value}" if selected_provider in {"google", "openai", "fal"} else value


def _legacy_data_extensions(data: dict[str, Any], type_key: str) -> dict[str, Any]:
    excluded = set(CONTRACT_DERIVED_DATA_FIELDS) | set(RUNTIME_DATA_FIELDS) | set(LEGACY_CONFIG_FIELDS)
    if type_key in {"prompt.input", "generation.brief", "asset.select", "character.select", "format.profile"}:
        excluded.add("configText")
    return {key: deepcopy(value) for key, value in data.items() if key not in excluded}


def _react_flow_extensions(raw_node: dict[str, Any]) -> dict[str, Any]:
    return {
        key: deepcopy(value)
        for key, value in raw_node.items()
        if key not in {"id", "data", "position"} and key not in EPHEMERAL_REACT_FLOW_FIELDS
    }


def canonicalize_canvas_document(
    raw_nodes: list[dict[str, Any]],
    raw_edges: list[dict[str, Any]],
) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = []
    elements: list[dict[str, Any]] = []
    runtime_nodes: dict[str, dict[str, Any]] = {}

    for order, raw_node in enumerate(raw_nodes):
        node_id = str(raw_node.get("id") or "")
        data = dict(raw_node.get("data") or {})
        type_key = str(data.get("key") or "")
        runtime = {key: deepcopy(data[key]) for key in RUNTIME_DATA_FIELDS if key in data}
        if runtime:
            runtime_nodes[node_id] = runtime
        ui = {
            "order": order,
            "position": deepcopy(raw_node.get("position") or {}),
            "label": str(data.get("label") or type_key or "Unknown node"),
            "description": str(data.get("description") or ""),
            "react_flow": _react_flow_extensions(raw_node),
        }

        if type_key in canvas_only_keys():
            elements.append({
                "id": node_id,
                "element_type": type_key,
                "ui": ui,
                "editor": {
                    "data": {
                        key: deepcopy(value)
                        for key, value in data.items()
                        if key not in RUNTIME_DATA_FIELDS and key not in {"key", "label", "description"}
                    }
                },
            })
            continue

        contract_version = int(data.get("contractVersion") or 1)
        definition = node_registry.get(type_key, contract_version)
        raw_config = legacy_node_config(data, type_key)
        config = node_registry.resolve_config(definition, raw_config) if definition else raw_config
        model_alias = logical_model_alias(
            data,
            definition.execution.model_alias if definition else str(data.get("model") or ""),
            definition.execution.provider if definition else str(data.get("provider") or ""),
        )
        selected_provider = str(data.get("provider") or "")
        if not selected_provider and model_alias.startswith(("google.", "openai.", "fal.")):
            selected_provider = model_alias.split(".", 1)[0]
        if not selected_provider and definition:
            selected_provider = definition.execution.provider
        nodes.append({
            "id": node_id,
            "type_key": type_key,
            "contract_version": contract_version,
            "definition_digest": definition.definition_digest if definition else data.get("definitionDigest"),
            "config": config,
            "execution": {
                "model_alias": model_alias,
                "provider": selected_provider,
            },
            "ui": ui,
            "editor": {"legacy_data": _legacy_data_extensions(data, type_key)},
            **({"unknown": True} if definition is None else {}),
        })

    edges = []
    for raw_edge in raw_edges:
        edges.append({
            "id": str(raw_edge.get("id") or f"{raw_edge.get('source')}->{raw_edge.get('target')}"),
            "source": str(raw_edge.get("source") or ""),
            "target": str(raw_edge.get("target") or ""),
            "source_port": raw_edge.get("sourceHandle"),
            "target_port": raw_edge.get("targetHandle"),
            "ui": {
                key: deepcopy(value)
                for key, value in raw_edge.items()
                if key not in {"id", "source", "target", "sourceHandle", "targetHandle", "selected"}
            },
        })

    return {
        "schema_version": CANVAS_DOCUMENT_SCHEMA_VERSION,
        "graph": {
            "schema_version": CANVAS_GRAPH_SCHEMA_VERSION,
            "nodes": nodes,
            "elements": elements,
            "edges": edges,
        },
        "runtime": {
            "schema_version": CANVAS_RUNTIME_SCHEMA_VERSION,
            "nodes": runtime_nodes,
        },
    }


def _legacy_contract_data(node: dict[str, Any]) -> dict[str, Any]:
    type_key = str(node.get("type_key") or "")
    contract_version = int(node.get("contract_version") or 1)
    definition = node_registry.get(type_key, contract_version)
    config = deepcopy(node.get("config") or {})
    data = deepcopy((node.get("editor") or {}).get("legacy_data") or {})
    data.update({
        "key": type_key,
        "label": str((node.get("ui") or {}).get("label") or (definition.display.label if definition else type_key)),
        "description": str((node.get("ui") or {}).get("description") or (definition.display.description if definition else "")),
        "contractVersion": contract_version,
        "definitionDigest": node.get("definition_digest"),
        "config": config,
    })
    if definition:
        inputs = [port_type_registry.get(port.type).legacy_type for port in definition.ports.inputs]
        required = [port_type_registry.get(port.type).legacy_type for port in definition.ports.inputs if port.required]
        multiple = [port_type_registry.get(port.type).legacy_type for port in definition.ports.inputs if port.multiple]
        output = definition.ports.outputs[0] if definition.ports.outputs else None
        output_type = port_type_registry.get(output.type).legacy_type if output else None
        data.update({
            "icon": definition.display.icon,
            "kind": "input" if definition.execution.kind == "source" else "generate" if definition.execution.kind == "provider" else "logic",
            "inputTypes": inputs,
            "requiredInputTypes": required,
            "multiInputTypes": multiple,
            "outputType": output_type,
            "cost": definition.display.cost_label,
            "executable": definition.execution.kind != "source",
        })
    execution = dict(node.get("execution") or {})
    data.setdefault("model", execution.get("model_alias"))
    data.setdefault("provider", execution.get("provider"))
    for legacy_key, config_key in LEGACY_CONFIG_FIELDS.items():
        if config_key in config:
            data[legacy_key] = deepcopy(config[config_key])
    if type_key in {"prompt.input", "generation.brief"}:
        data["configText"] = str(config.get("text") or "")
    elif type_key == "asset.select":
        data["configText"] = str(config.get("artifact_id") or "")
        data["outputType"] = str(config.get("artifact_type") or data.get("outputType") or "ReferenceAsset")
    elif type_key == "character.select":
        data["configText"] = str(config.get("character_id") or "")
    elif type_key == "format.profile":
        data["configText"] = str(config.get("format_id") or "")
    return {key: value for key, value in data.items() if value is not None}


def legacy_canvas_graph(document: dict[str, Any] | None) -> dict[str, list[dict[str, Any]]]:
    source = document or {}
    if not is_canonical_canvas_document(source):
        return {
            "nodes": deepcopy(source.get("nodes") or []),
            "edges": deepcopy(source.get("edges") or []),
        }

    graph = dict(source.get("graph") or {})
    runtime_nodes = dict((source.get("runtime") or {}).get("nodes") or {})
    legacy_nodes: list[tuple[int, dict[str, Any]]] = []
    for node in graph.get("nodes") or []:
        ui = dict(node.get("ui") or {})
        legacy_data = _legacy_contract_data(node)
        legacy_data.update(deepcopy(runtime_nodes.get(str(node.get("id") or "")) or {}))
        legacy_nodes.append((int(ui.get("order") or 0), {
            **deepcopy(ui.get("react_flow") or {}),
            "id": str(node.get("id") or ""),
            "position": deepcopy(ui.get("position") or {}),
            "data": legacy_data,
        }))
    for element in graph.get("elements") or []:
        ui = dict(element.get("ui") or {})
        element_id = str(element.get("id") or "")
        data = deepcopy((element.get("editor") or {}).get("data") or {})
        data.update({
            "key": str(element.get("element_type") or ""),
            "label": str(ui.get("label") or "Canvas element"),
            "description": str(ui.get("description") or ""),
        })
        data.update(deepcopy(runtime_nodes.get(element_id) or {}))
        legacy_nodes.append((int(ui.get("order") or 0), {
            **deepcopy(ui.get("react_flow") or {}),
            "id": element_id,
            "position": deepcopy(ui.get("position") or {}),
            "data": data,
        }))
    legacy_nodes.sort(key=lambda item: item[0])

    edges = []
    for edge in graph.get("edges") or []:
        edges.append({
            **deepcopy(edge.get("ui") or {}),
            "id": str(edge.get("id") or ""),
            "source": str(edge.get("source") or ""),
            "target": str(edge.get("target") or ""),
            **({"sourceHandle": edge.get("source_port")} if edge.get("source_port") is not None else {}),
            **({"targetHandle": edge.get("target_port")} if edge.get("target_port") is not None else {}),
        })
    return {"nodes": [item[1] for item in legacy_nodes], "edges": edges}


def canonical_canvas_graph(document: dict[str, Any] | None) -> dict[str, Any]:
    source = document or {}
    if is_canonical_canvas_document(source):
        return deepcopy(source.get("graph") or {})
    legacy = legacy_canvas_graph(source)
    return deepcopy(canonicalize_canvas_document(legacy["nodes"], legacy["edges"])["graph"])
