from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.orm import Session

from .canvas_documents import (
    CANVAS_DOCUMENT_SCHEMA_VERSION,
    CANVAS_GRAPH_SCHEMA_VERSION,
    CANVAS_RUNTIME_SCHEMA_VERSION,
    canonical_canvas_graph,
)
from .database import CanvasRecord, WorkflowDefinitionRecord
from .domain import utc_now
from .nodes import node_registry
from .nodes.contracts import NodeDefinition
from .nodes.port_types import port_type_registry
from .service import audit, new_id
from .workflow_definitions import CompiledWorkflowVersion, compile_canvas_version


WORKFLOW_INPUT_TYPES = Literal[
    "string",
    "prompt",
    "integer",
    "number",
    "boolean",
    "enum",
    "artifact",
    "character",
    "model_alias",
]


class AuthoringNodeSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ref: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    type_key: str = Field(pattern=r"^[a-z][a-z0-9]*(?:\.[a-z][a-z0-9_]*)+$")
    contract_version: int | None = Field(default=None, ge=1)
    config: dict[str, Any] = Field(default_factory=dict)
    model_alias: str | None = Field(default=None, min_length=1, max_length=255)
    label: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2_000)


class AuthoringEdgeEndpoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    port: str = Field(pattern=r"^[a-z][a-z0-9_]*$")


class AuthoringEdgeSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: AuthoringEdgeEndpoint
    target: AuthoringEdgeEndpoint


class AuthoringInputSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    label: str = Field(min_length=1, max_length=160)
    type: WORKFLOW_INPUT_TYPES
    required: bool = False
    default: Any | None = None
    description: str = Field(default="", max_length=2_000)
    validation: dict[str, Any] = Field(default_factory=dict)
    options: list[Any] | None = None

    @model_validator(mode="after")
    def validate_required_default(self) -> "AuthoringInputSpec":
        if self.required and self.default is not None:
            raise ValueError("required Workflow input cannot have a default")
        return self


class AuthoringBindingSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    field: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    kind: Literal["input", "template"] = "input"
    input_key: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{0,63}$")
    template: str | None = Field(default=None, max_length=32_000)
    input_keys: list[str] = Field(default_factory=list, max_length=64)

    @model_validator(mode="after")
    def validate_expression(self) -> "AuthoringBindingSpec":
        if self.kind == "input":
            if not self.input_key or self.template is not None or self.input_keys:
                raise ValueError("input binding requires input_key only")
        elif self.template is None or not self.input_keys or self.input_key is not None:
            raise ValueError("template binding requires template and input_keys")
        return self


class AuthoringOutputSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    label: str = Field(min_length=1, max_length=160)
    node: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    port: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    primary: bool = False


class WorkflowAuthoringSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=10_000)
    tags: list[str] = Field(default_factory=list, max_length=32)
    nodes: list[AuthoringNodeSpec] = Field(min_length=1, max_length=500)
    edges: list[AuthoringEdgeSpec] = Field(default_factory=list, max_length=2_000)
    inputs: list[AuthoringInputSpec] = Field(default_factory=list, max_length=128)
    bindings: list[AuthoringBindingSpec] = Field(default_factory=list, max_length=256)
    outputs: list[AuthoringOutputSpec] = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def validate_unique_names(self) -> "WorkflowAuthoringSpec":
        refs = [node.ref for node in self.nodes]
        if len(refs) != len(set(refs)):
            raise ValueError("Workflow Node refs must be unique")
        input_keys = [item.key for item in self.inputs]
        if len(input_keys) != len(set(input_keys)):
            raise ValueError("Workflow input keys must be unique")
        output_keys = [item.key for item in self.outputs]
        if len(output_keys) != len(set(output_keys)):
            raise ValueError("Workflow output keys must be unique")
        if sum(item.primary for item in self.outputs) != 1:
            raise ValueError("Workflow must declare exactly one Primary output")
        return self


@dataclass(frozen=True)
class PreparedWorkflowDraft:
    document: dict[str, Any]
    draft_contract: dict[str, Any]
    compiled: CompiledWorkflowVersion
    resolved_nodes: list[dict[str, Any]]


def _resolve_definition(spec: AuthoringNodeSpec) -> NodeDefinition:
    if spec.contract_version is not None:
        definition = node_registry.get(spec.type_key, spec.contract_version)
    else:
        candidates = [
            item
            for item in node_registry.list(lifecycle="ACTIVE")
            if item.type_key == spec.type_key
        ]
        definition = max(candidates, key=lambda item: item.contract_version) if candidates else None
    if definition is None:
        version = f"@{spec.contract_version}" if spec.contract_version is not None else ""
        raise ValueError(f"Node Definition was not found: {spec.type_key}{version}")
    if definition.lifecycle != "ACTIVE":
        raise ValueError(
            f"new Workflow Draft cannot use {definition.lifecycle} Node: "
            f"{definition.type_key}@{definition.contract_version}"
        )
    return definition


def _provider_for_alias(alias: str, definition: NodeDefinition) -> str:
    provider = alias.split(".", 1)[0]
    return provider if provider in {"google", "openai", "fal", "xai", "local"} else definition.execution.provider


def _resolve_model_alias(spec: AuthoringNodeSpec, definition: NodeDefinition) -> str:
    alias = spec.model_alias or definition.execution.model_alias
    families = definition.execution.model_families
    if spec.model_alias and families and not any(alias.startswith(prefix) for prefix in families):
        raise ValueError(
            f"model alias {alias!r} is incompatible with "
            f"{definition.type_key}@{definition.contract_version}"
        )
    if spec.model_alias and not families and alias != definition.execution.model_alias:
        raise ValueError(
            f"{definition.type_key}@{definition.contract_version} does not allow model selection"
        )
    return alias


def _auto_layout(node_refs: list[str], edges: list[AuthoringEdgeSpec]) -> dict[str, dict[str, int]]:
    incoming = {ref: [] for ref in node_refs}
    outgoing = {ref: [] for ref in node_refs}
    for edge in edges:
        if edge.source.node in outgoing and edge.target.node in incoming:
            outgoing[edge.source.node].append(edge.target.node)
            incoming[edge.target.node].append(edge.source.node)
    indegree = {ref: len(incoming[ref]) for ref in node_refs}
    queue = [ref for ref in node_refs if indegree[ref] == 0]
    depth = {ref: 0 for ref in node_refs}
    while queue:
        source = queue.pop(0)
        for target in outgoing[source]:
            depth[target] = max(depth[target], depth[source] + 1)
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)
    rows: dict[int, int] = {}
    positions: dict[str, dict[str, int]] = {}
    for ref in node_refs:
        column = depth[ref]
        row = rows.get(column, 0)
        rows[column] = row + 1
        positions[ref] = {"x": 40 + column * 340, "y": 80 + row * 220}
    return positions


def _input_contract_item(item: AuthoringInputSpec) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "key": item.key,
        "label": item.label,
        "type": item.type,
        "required": item.required,
        "description": item.description,
        "validation": item.validation,
    }
    if item.default is not None:
        payload["default"] = item.default
    if item.options is not None:
        payload["options"] = item.options
    return payload


def _binding_contract_item(item: AuthoringBindingSpec) -> dict[str, Any]:
    if item.kind == "input":
        value = {"kind": "input", "key": item.input_key}
    else:
        value = {
            "kind": "template",
            "template": item.template,
            "input_keys": item.input_keys,
        }
    return {
        "target": {"node_id": item.node, "path": f"/config/{item.field}"},
        "value": value,
    }


def prepare_workflow_draft(db: Session, spec: WorkflowAuthoringSpec) -> PreparedWorkflowDraft:
    refs = {node.ref for node in spec.nodes}
    for edge in spec.edges:
        if edge.source.node not in refs or edge.target.node not in refs:
            raise ValueError("Workflow edge references an unknown Node ref")
    for binding in spec.bindings:
        if binding.node not in refs:
            raise ValueError(f"Workflow binding references an unknown Node ref: {binding.node}")
    for output in spec.outputs:
        if output.node not in refs:
            raise ValueError(f"Workflow output references an unknown Node ref: {output.node}")

    positions = _auto_layout([node.ref for node in spec.nodes], spec.edges)
    definitions: dict[str, NodeDefinition] = {}
    canonical_nodes: list[dict[str, Any]] = []
    resolved_nodes: list[dict[str, Any]] = []
    for order, node in enumerate(spec.nodes):
        definition = _resolve_definition(node)
        config = node_registry.resolve_config(definition, node.config)
        model_alias = _resolve_model_alias(node, definition)
        definitions[node.ref] = definition
        canonical_nodes.append({
            "id": node.ref,
            "type_key": definition.type_key,
            "contract_version": definition.contract_version,
            "definition_digest": definition.definition_digest,
            "config": config,
            "execution": {
                "model_alias": model_alias,
                "provider": _provider_for_alias(model_alias, definition),
            },
            "ui": {
                "order": order,
                "position": positions[node.ref],
                "label": node.label or definition.display.label,
                "description": node.description if node.description is not None else definition.display.description,
                "react_flow": {},
            },
            "editor": {"legacy_data": {}},
        })
        resolved_nodes.append({
            "ref": node.ref,
            "type_key": definition.type_key,
            "contract_version": definition.contract_version,
            "definition_digest": definition.definition_digest,
            "config": config,
            "model_alias": model_alias,
        })

    canonical_edges: list[dict[str, Any]] = []
    for index, edge in enumerate(spec.edges):
        source_definition = definitions[edge.source.node]
        target_definition = definitions[edge.target.node]
        if not any(port.key == edge.source.port for port in source_definition.ports.outputs):
            raise ValueError(
                f"unknown output port: {edge.source.node}.{edge.source.port}"
            )
        if not any(port.key == edge.target.port for port in target_definition.ports.inputs):
            raise ValueError(
                f"unknown input port: {edge.target.node}.{edge.target.port}"
            )
        canonical_edges.append({
            "id": f"edge-{index + 1}-{edge.source.node}-{edge.target.node}",
            "source": edge.source.node,
            "target": edge.target.node,
            "source_port": edge.source.port,
            "target_port": edge.target.port,
            "ui": {"input_order": index},
        })

    output_contract: list[dict[str, Any]] = []
    for output in spec.outputs:
        definition = definitions[output.node]
        port = next((item for item in definition.ports.outputs if item.key == output.port), None)
        if port is None:
            raise ValueError(f"unknown Workflow output port: {output.node}.{output.port}")
        output_contract.append({
            "key": output.key,
            "label": output.label,
            "node_id": output.node,
            "port_key": port.key,
            "port_type": port.type,
            "primary": output.primary,
        })

    document = {
        "schema_version": CANVAS_DOCUMENT_SCHEMA_VERSION,
        "graph": {
            "schema_version": CANVAS_GRAPH_SCHEMA_VERSION,
            "nodes": canonical_nodes,
            "elements": [],
            "edges": canonical_edges,
        },
        "runtime": {
            "schema_version": CANVAS_RUNTIME_SCHEMA_VERSION,
            "nodes": {},
        },
    }
    draft_contract = {
        "schema_version": "workflow.contract.draft.v1",
        "inputs": [_input_contract_item(item) for item in spec.inputs],
        "bindings": [_binding_contract_item(item) for item in spec.bindings],
        "outputs": output_contract,
    }
    transient_canvas = CanvasRecord(
        id="mcp-plan",
        name=spec.name,
        graph_json=document,
        revision=1,
        draft_contract_json=draft_contract,
        updated_at=utc_now(),
    )
    compiled = compile_canvas_version(db, transient_canvas)
    return PreparedWorkflowDraft(
        document=document,
        draft_contract=draft_contract,
        compiled=compiled,
        resolved_nodes=resolved_nodes,
    )


def create_workflow_draft(
    db: Session,
    spec: WorkflowAuthoringSpec,
    *,
    actor_id: str = "local-mcp",
) -> tuple[WorkflowDefinitionRecord, CanvasRecord, PreparedWorkflowDraft]:
    prepared = prepare_workflow_draft(db, spec)
    canvas = CanvasRecord(
        id=new_id("canvas"),
        name=spec.name,
        graph_json=prepared.document,
        active_run_id=None,
        revision=1,
        draft_contract_json=prepared.draft_contract,
        updated_at=utc_now(),
    )
    definition = WorkflowDefinitionRecord(
        id=new_id("workflow"),
        name=spec.name,
        description=spec.description,
        status="ACTIVE",
        draft_canvas_id=canvas.id,
        current_version_id=None,
        tags=list(dict.fromkeys(spec.tags)),
        updated_at=utc_now(),
    )
    canvas.workflow_definition_id = definition.id
    db.add_all([canvas, definition])
    audit(db, "workflow.created_by_mcp", definition.id, {
        "actor_id": actor_id,
        "draft_canvas_id": canvas.id,
        "content_hash": prepared.compiled.content_hash,
        "node_contracts": [
            f"{item['type_key']}@{item['contract_version']}"
            for item in prepared.resolved_nodes
        ],
    })
    db.commit()
    db.refresh(definition)
    db.refresh(canvas)
    return definition, canvas, prepared


def update_workflow_draft(
    db: Session,
    *,
    workflow_id: str,
    expected_revision: int,
    spec: WorkflowAuthoringSpec,
    actor_id: str = "local-mcp",
) -> tuple[WorkflowDefinitionRecord, CanvasRecord, PreparedWorkflowDraft, bool]:
    definition = db.get(WorkflowDefinitionRecord, workflow_id)
    if definition is None:
        raise ValueError("Workflow was not found")
    if definition.status != "ACTIVE":
        raise ValueError("Archived Workflow Draft cannot be updated")
    canvas = db.get(CanvasRecord, definition.draft_canvas_id)
    if canvas is None or canvas.workflow_definition_id != workflow_id:
        raise ValueError("Workflow Draft Canvas is missing")
    if canvas.revision != expected_revision:
        raise ValueError(
            f"Canvas revision conflict: expected {expected_revision}, current {canvas.revision}"
        )
    prepared = prepare_workflow_draft(db, spec)
    next_tags = list(dict.fromkeys(spec.tags))
    changed = (
        canvas.name != spec.name
        or canvas.graph_json != prepared.document
        or canvas.draft_contract_json != prepared.draft_contract
        or definition.name != spec.name
        or definition.description != spec.description
        or definition.tags != next_tags
    )
    if changed:
        canvas.name = spec.name
        canvas.graph_json = prepared.document
        canvas.draft_contract_json = prepared.draft_contract
        canvas.revision += 1
        canvas.updated_at = utc_now()
        definition.name = spec.name
        definition.description = spec.description
        definition.tags = next_tags
        definition.updated_at = utc_now()
        audit(db, "workflow.draft_updated_by_mcp", definition.id, {
            "actor_id": actor_id,
            "draft_canvas_id": canvas.id,
            "revision": canvas.revision,
            "content_hash": prepared.compiled.content_hash,
        })
        db.commit()
        db.refresh(definition)
        db.refresh(canvas)
    return definition, canvas, prepared, changed


def workflow_draft_payload(
    definition: WorkflowDefinitionRecord,
    canvas: CanvasRecord,
) -> dict[str, Any]:
    graph = canonical_canvas_graph(canvas.graph_json)
    contract = dict(canvas.draft_contract_json or {})
    nodes = []
    definitions: dict[str, NodeDefinition | None] = {}
    for node in graph.get("nodes") or []:
        node_id = str(node.get("id") or "")
        node_definition = node_registry.get(
            str(node.get("type_key") or ""),
            int(node.get("contract_version") or 1),
        )
        definitions[node_id] = node_definition
        nodes.append({
            "ref": node_id,
            "type_key": node.get("type_key"),
            "contract_version": node.get("contract_version"),
            "config": node.get("config") or {},
            "model_alias": (node.get("execution") or {}).get("model_alias"),
            "label": (node.get("ui") or {}).get("label"),
            "description": (node.get("ui") or {}).get("description"),
        })
    edges = [
        {
            "source": {
                "node": edge.get("source"),
                "port": edge.get("source_port"),
            },
            "target": {
                "node": edge.get("target"),
                "port": edge.get("target_port"),
            },
        }
        for edge in graph.get("edges") or []
    ]
    bindings = []
    for binding in contract.get("bindings") or []:
        target = dict(binding.get("target") or {})
        value = dict(binding.get("value") or {})
        bindings.append({
            "node": target.get("node_id"),
            "field": str(target.get("path") or "").removeprefix("/config/"),
            "kind": value.get("kind"),
            **({"input_key": value.get("key")} if value.get("kind") == "input" else {}),
            **({
                "template": value.get("template"),
                "input_keys": value.get("input_keys") or [],
            } if value.get("kind") == "template" else {}),
        })
    outputs = []
    for output in contract.get("outputs") or []:
        node_id = str(output.get("node_id") or "")
        port_key = output.get("port_key")
        if not port_key and definitions.get(node_id):
            matching = [
                port.key
                for port in definitions[node_id].ports.outputs
                if output.get("port_type") in {
                    port.type,
                    (
                        port_type_registry.get(port.type).legacy_type
                        if port_type_registry.get(port.type)
                        else None
                    ),
                }
            ]
            if len(matching) == 1:
                port_key = matching[0]
        outputs.append({
            "key": output.get("key"),
            "label": output.get("label"),
            "node": node_id,
            "port": port_key,
            "primary": output.get("primary") is True,
        })
    return {
        "workflow_id": definition.id,
        "draft_canvas_id": canvas.id,
        "revision": canvas.revision,
        "base_version_id": canvas.base_version_id,
        "resolved_contracts": [
            {
                "ref": str(node.get("id") or ""),
                "type_key": node.get("type_key"),
                "contract_version": node.get("contract_version"),
                "definition_digest": node.get("definition_digest"),
            }
            for node in graph.get("nodes") or []
        ],
        "spec": {
            "name": definition.name,
            "description": definition.description,
            "tags": definition.tags or [],
            "nodes": nodes,
            "edges": edges,
            "inputs": contract.get("inputs") or [],
            "bindings": bindings,
            "outputs": outputs,
        },
    }
