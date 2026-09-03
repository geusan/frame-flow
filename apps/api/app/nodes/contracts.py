from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.orm import Session

from ..domain import ExperimentRunRequest
from .port_types import port_type_registry



class NodeDisplay(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1)
    description: str = Field(min_length=1)
    category: Literal["Quick", "References", "Image", "Video", "Audio", "Utilities", "Advanced"]
    icon: str = Field(min_length=1)
    cost_label: str | None = None
    keywords: list[str] = Field(default_factory=list)


class NodePort(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    type: str
    label: str = Field(min_length=1)
    required: bool = False
    multiple: bool = False


class NodePorts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    inputs: list[NodePort] = Field(default_factory=list)
    outputs: list[NodePort] = Field(min_length=1)


class NodeBindingPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workflow_inputs: Literal["schema", "none"] = "schema"


class NodeExecution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["source", "provider", "local", "human_gate", "composite"]
    executor: str = Field(min_length=1)
    revision: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    model_alias: str = Field(min_length=1)
    model_families: list[str] = Field(default_factory=list)
    approval_schema: dict[str, Any] | None = None


class NodeEditor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["generic", "legacy", "custom"]
    ref: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")

    @model_validator(mode="after")
    def validate_ref(self) -> "NodeEditor":
        if self.kind == "custom" and not self.ref:
            raise ValueError("custom editor requires ref")
        if self.kind != "custom" and self.ref is not None:
            raise ValueError(f"{self.kind} editor cannot declare ref")
        return self


class NodeArtifactContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    primary_type: str = Field(min_length=1)
    schema_id: str = Field(min_length=1)
    input_roles: dict[str, str] = Field(default_factory=dict)
    output_role: str = Field(min_length=1)


class NodeDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["node.definition.v1"]
    type_key: str = Field(pattern=r"^[a-z][a-z0-9]*(?:\.[a-z][a-z0-9_]*)+$")
    contract_version: int = Field(ge=1)
    lifecycle: Literal["ACTIVE", "DEPRECATED", "RETIRED", "BLOCKED"]
    display: NodeDisplay
    ports: NodePorts
    config_schema: dict[str, Any]
    binding_policy: NodeBindingPolicy
    execution: NodeExecution
    editor: NodeEditor
    artifact_contract: NodeArtifactContract

    @model_validator(mode="after")
    def validate_contract(self) -> "NodeDefinition":
        unknown_ports = [port.type for port in [*self.ports.inputs, *self.ports.outputs] if port.type not in port_type_registry.ids]
        if unknown_ports:
            raise ValueError(f"unregistered port types: {', '.join(sorted(set(unknown_ports)))}")
        schema = self.config_schema
        if schema.get("type") != "object" or schema.get("additionalProperties") is not False:
            raise ValueError("config_schema must be a closed object schema")
        properties = schema.get("properties")
        if not isinstance(properties, dict):
            raise ValueError("config_schema.properties must be an object")
        workflow_types = {
            "string": {"string", "prompt", "enum", "model_alias", "artifact", "character"},
            "integer": {"integer", "number"},
            "number": {"number"},
            "boolean": {"boolean"},
        }
        for name, definition in properties.items():
            workflow = definition.get("x-workflow-input") if isinstance(definition, dict) else None
            if not workflow or not workflow.get("enabled"):
                continue
            json_type = str(definition.get("type") or "")
            workflow_type = str(workflow.get("type") or "")
            if workflow_type not in workflow_types.get(json_type, set()):
                raise ValueError(f"workflow input type {workflow_type!r} is incompatible with config field {name!r}")
        if self.execution.kind == "human_gate" and self.editor.kind == "custom" and not self.execution.approval_schema:
            raise ValueError("custom human_gate Node requires an approval_schema")
        return self

    @property
    def definition_digest(self) -> str:
        payload = self._contract_payload()
        # model_families was added as backward-compatible capability metadata.
        # Do not rewrite digests for already published fixed-model contracts.
        if not payload["execution"]["model_families"]:
            payload["execution"].pop("model_families")
        if payload["execution"].get("approval_schema") is None:
            payload["execution"].pop("approval_schema", None)
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return f"sha256:{hashlib.sha256(canonical.encode()).hexdigest()}"

    def public_payload(self) -> dict[str, Any]:
        return {**self._contract_payload(), "definition_digest": self.definition_digest}

    def _contract_payload(self) -> dict[str, Any]:
        payload = self.model_dump(mode="json")
        if payload["editor"].get("ref") is None:
            payload["editor"].pop("ref")
        if payload["execution"].get("approval_schema") is None:
            payload["execution"].pop("approval_schema", None)
        return payload


@dataclass(frozen=True)
class NodeExecutionContext:
    db: Session
    payload: ExperimentRunRequest
    definition: NodeDefinition
    request_hash: str
    experiment_id: str


@dataclass(frozen=True)
class NodeExecutionResult:
    output: dict[str, object]
    output_artifact_ids: list[str]
    provider_request_id: str
    cost_usd: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


class NodeExecutor(Protocol):
    def execute(
        self,
        context: NodeExecutionContext,
        resolved_node_config: dict[str, Any],
        typed_inputs: list[dict[str, Any]],
    ) -> NodeExecutionResult: ...
