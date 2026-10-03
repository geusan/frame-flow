from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator
from jsonschema import Draft202012Validator

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
        Draft202012Validator.check_schema(schema)
        if self.execution.approval_schema:
            Draft202012Validator.check_schema(self.execution.approval_schema)
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
class NodeInputMedia:
    artifact_id: str
    artifact_type: str
    data: bytes
    content_type: str


@dataclass(frozen=True)
class NodeArtifactRef:
    id: str
    type: str


@dataclass(frozen=True)
class NodeArtifactSnapshot:
    id: str
    type: str
    schema_id: str | None = None
    sha256: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def metadata_json(self) -> dict[str, Any]:
        return self.metadata


@dataclass(frozen=True)
class NodeArtifactContent:
    record: NodeArtifactSnapshot
    data: bytes
    content_type: str

    @property
    def id(self) -> str:
        return self.record.id

    @property
    def type(self) -> str:
        return self.record.type

    @property
    def schema_id(self) -> str | None:
        return self.record.schema_id

    @property
    def sha256(self) -> str:
        return self.record.sha256

    @property
    def metadata_json(self) -> dict[str, Any]:
        return self.record.metadata


@dataclass(frozen=True)
class NodeArtifactWrite:
    artifact_type: str
    schema_id: str | None = None
    input_artifact_ids: list[str] = field(default_factory=list)
    input_artifact_roles: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    content: bytes | None = None
    content_type: str | None = None
    filename: str | None = None


class NodeArtifactStore(Protocol):
    def read(self, artifact_id: str) -> NodeArtifactContent: ...

    def read_inputs(
        self,
        typed_inputs: list[dict[str, Any]],
    ) -> list[NodeArtifactContent]: ...

    def load_input_media(
        self,
        definition: NodeDefinition,
        typed_inputs: list[dict[str, Any]],
        *,
        expand_characters: bool = True,
    ) -> tuple[list[NodeInputMedia], list[str], dict[str, str]]: ...

    def create(self, write: NodeArtifactWrite) -> NodeArtifactRef: ...

    def flush(self) -> None: ...

    def content_url(self, artifact_id: str) -> str: ...


@dataclass(frozen=True)
class NodeProviderAuth:
    auth_method: str
    configured: bool
    setup_token: str = ""


class NodeProviderSettings(Protocol):
    def get_auth(self, provider_key: str) -> NodeProviderAuth | None: ...


class NodeMediaRuntime(Protocol):
    def canonical_caption_document(self, document: dict[str, Any]) -> dict[str, Any]: ...

    def materialize_caption_fonts(
        self,
        document: dict[str, Any],
        directory: Any,
    ) -> dict[str, str]: ...

    def render_timeline(self, timeline: NodeArtifactContent) -> bytes: ...

    def build_timeline(
        self,
        artifacts: list[NodeArtifactContent],
        config: dict[str, Any],
    ) -> dict[str, Any]: ...

    def edit_videos(
        self,
        artifacts: list[NodeArtifactContent],
        config: dict[str, Any],
    ) -> bytes: ...

    def replace_audio(
        self,
        video: NodeArtifactContent,
        audio: NodeArtifactContent,
        subtitle: NodeArtifactContent | None = None,
        *,
        language: str = "und",
    ) -> bytes: ...

    def media_duration(self, artifact: NodeArtifactContent) -> float: ...

    def extract_speech_audio(self, video: NodeArtifactContent) -> tuple[bytes, int]: ...

    def synthesized_wav(self, speech: Any) -> bytes: ...

    def build_subtitles(self, script: str, duration: float) -> bytes: ...

    def segments_to_srt(self, segments: list[Any]) -> bytes: ...

    def quality_report(
        self,
        video: NodeArtifactContent,
        config: dict[str, Any],
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class NodeCharacterLoraResult:
    character: NodeArtifactSnapshot
    state: dict[str, Any]


class NodeCharacterLoraRuntime(Protocol):
    def ensure_ready(
        self,
        character_id: str,
        *,
        trigger_word: str,
        steps: int,
        learning_rate: float,
        timeout_seconds: int,
    ) -> NodeCharacterLoraResult: ...


class NodeCharacterMotionRuntime(Protocol):
    def remember_task(
        self,
        request_hash: str,
        experiment_id: str,
        stage: str,
        task_id: str,
    ) -> None: ...

    def resume_task(
        self,
        request_hash: str,
        experiment_id: str,
        allowed_stages: set[str],
    ) -> tuple[str | None, str | None]: ...


class ProviderTaskStateError(RuntimeError):
    retryable = False


class NodeProviderTasks(Protocol):
    def claim(self, provider: str, stage: str, *, resumable: bool) -> str | None: ...
    def remember(self, provider: str, stage: str, task_id: str) -> None: ...


@dataclass(frozen=True)
class NodeExecutionContext:
    definition: NodeDefinition
    prompt: str
    model_alias: str
    request_hash: str
    experiment_id: str
    progress_callback: Callable[[int, str], None] | None = None
    artifact_store: NodeArtifactStore | None = None
    provider_settings: NodeProviderSettings | None = None
    media_runtime: NodeMediaRuntime | None = None
    character_lora_runtime: NodeCharacterLoraRuntime | None = None
    character_motion_runtime: NodeCharacterMotionRuntime | None = None
    provider_tasks: NodeProviderTasks | None = None

    def report_progress(self, progress: int, message: str) -> None:
        if self.progress_callback:
            self.progress_callback(max(0, min(99, int(progress))), str(message)[:1000])

    def require_artifact_store(self) -> NodeArtifactStore:
        if self.artifact_store is None:
            raise RuntimeError("Node Executor requires an ArtifactStore")
        return self.artifact_store

    def require_provider_settings(self) -> NodeProviderSettings:
        if self.provider_settings is None:
            raise RuntimeError("Node Executor requires ProviderSettings")
        return self.provider_settings

    def require_media_runtime(self) -> NodeMediaRuntime:
        if self.media_runtime is None:
            raise RuntimeError("Node Executor requires MediaRuntime")
        return self.media_runtime

    def require_character_lora_runtime(self) -> NodeCharacterLoraRuntime:
        if self.character_lora_runtime is None:
            raise RuntimeError("Node Executor requires CharacterLoraRuntime")
        return self.character_lora_runtime

    def require_character_motion_runtime(self) -> NodeCharacterMotionRuntime:
        if self.character_motion_runtime is None:
            raise RuntimeError("Node Executor requires CharacterMotionRuntime")
        return self.character_motion_runtime

    def require_provider_tasks(self) -> NodeProviderTasks:
        if self.provider_tasks is None:
            raise RuntimeError("Node Executor requires ProviderTasks")
        return self.provider_tasks

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
