from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class NodeStatus(StrEnum):
    BLOCKED = "BLOCKED"
    READY = "READY"
    QUEUED = "QUEUED"
    CLAIMED = "CLAIMED"
    SUBMITTED = "SUBMITTED"
    RUNNING = "RUNNING"
    WAITING_INPUT = "WAITING_INPUT"
    RETRY_WAIT = "RETRY_WAIT"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELED = "CANCELED"
    STALE = "STALE"


class RightsBasis(StrEnum):
    OWNED = "owned"
    LICENSED = "licensed"
    CREATIVE_COMMONS = "creative_commons"
    PUBLIC_DOMAIN = "public_domain"
    ANALYSIS_ONLY = "analysis_only"
    UNKNOWN = "unknown"


class Evidence(BaseModel):
    reference_id: str
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    artifact_id: str


class EvidenceValue(BaseModel):
    value: Any
    confidence: float = Field(ge=0, le=1)
    evidence: list[Evidence] = Field(default_factory=list)
    manual_override: Any | None = None

    @property
    def resolved_value(self) -> Any:
        return self.manual_override if self.manual_override is not None else self.value


class NarrativeBeat(BaseModel):
    role: Literal["hook", "context", "escalation", "payoff"]
    start_ratio: float = Field(ge=0, le=1)
    end_ratio: float = Field(gt=0, le=1)
    pattern: str | None = None

    @model_validator(mode="after")
    def validate_range(self) -> "NarrativeBeat":
        if self.end_ratio <= self.start_ratio:
            raise ValueError("end_ratio must be greater than start_ratio")
        return self


class FormatCoreV1(BaseModel):
    schema_version: Literal["format.core.v1"] = "format.core.v1"
    duration: dict[str, int]
    narrative: dict[str, list[NarrativeBeat]]
    editing: dict[str, Any]
    captions: dict[str, Any]
    voice: dict[str, Any]
    music: dict[str, Any]
    visual: dict[str, Any]
    constraints: dict[str, Any] = Field(default_factory=dict)


class FormatProfilePayload(BaseModel):
    schema_version: Literal["format.profile.v1"] = "format.profile.v1"
    core: FormatCoreV1
    extensions: dict[str, Any] = Field(default_factory=dict)
    evidence: dict[str, EvidenceValue] = Field(default_factory=dict)


class ReferenceInspectRequest(BaseModel):
    urls: list[HttpUrl] = Field(min_length=1, max_length=100)


class ReferenceMetadata(BaseModel):
    canonical_url: str
    source_id: str
    title: str
    creator: str
    duration_ms: int
    width: int
    height: int
    has_subtitles: bool
    estimated_bytes: int
    thumbnail_url: str | None = None
    duplicate_reference_id: str | None = None


class ReferenceImportRequest(BaseModel):
    metadata: ReferenceMetadata
    rights_basis: RightsBasis = RightsBasis.ANALYSIS_ONLY
    allow_generation_input: bool = False
    allow_direct_asset_use: bool = False
    retention_policy: str = "workspace_default"
    source_attribution: str | None = None

    @model_validator(mode="after")
    def protect_analysis_only(self) -> "ReferenceImportRequest":
        if self.rights_basis in {RightsBasis.ANALYSIS_ONLY, RightsBasis.UNKNOWN}:
            self.allow_generation_input = False
            self.allow_direct_asset_use = False
        return self


class ReferenceSetRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    reference_ids: list[str] = Field(min_length=1)


class ExtractionRecipeRequest(BaseModel):
    recipe_id: str
    version: int = Field(ge=1)
    prompt_template_version_id: str
    output_schema_id: str
    core_projection: Literal["format.core.v1"] = "format.core.v1"
    analyzers: list[str]
    logical_model: str = "google.text.quality"


class FormatRunRequest(BaseModel):
    reference_set_id: str
    recipe_id: str = "shorts_format_full_v2"
    recipe_version: int = 2
    name: str = "Extracted shorts format"


class VariationRequest(BaseModel):
    count: int = Field(default=5, ge=1, le=20)
    distance: Literal["low", "medium", "high"] = "medium"
    locked_fields: list[str] = Field(default_factory=list)
    variation_axes: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    seed: int | None = None


class MergeSource(BaseModel):
    format_id: str
    weight: float = Field(default=1, ge=0)


class MergeRequest(BaseModel):
    name: str
    sources: list[MergeSource] = Field(min_length=2)
    default_strategy: Literal["weighted_average", "median", "union", "priority", "llm_conflict_resolution"] = "weighted_average"
    field_strategies: dict[str, Any] = Field(default_factory=dict)


class GenerationBriefRequest(BaseModel):
    topic: str = Field(min_length=2)
    key_message: str
    audience: str
    language: str = "ko-KR"
    target_duration_ms: int = Field(default=38000, ge=10000, le=180000)
    aspect_ratio: Literal["9:16", "16:9", "1:1"] = "9:16"
    additional_prompt: str = ""
    format_id: str
    candidate_count: int = Field(default=4, ge=1, le=4)
    budget_limit_usd: float = Field(default=5, gt=0)


class GenerationRunRequest(BaseModel):
    brief_id: str
    workflow_definition_id: str = "workflow.shorts.default.v1"
    dry_run: bool = False


class SelectionRequest(BaseModel):
    artifact_id: str
    selected_by: str = "local-user"


class RegenerateRequest(BaseModel):
    prompt_patch: str | None = None
    model_alias: str | None = None
    seed: int | None = None


class SignedUrlRequest(BaseModel):
    filename: str
    content_type: str
    size_bytes: int = Field(gt=0)


class ArtifactUrlImportRequest(BaseModel):
    url: HttpUrl


class FrameCaptureRequest(BaseModel):
    timestamp_ms: int = Field(ge=0)


class ExperimentRunRequest(BaseModel):
    canvas_id: str = Field(min_length=1, max_length=128)
    node_id: str = Field(min_length=1, max_length=128)
    node_key: str = Field(min_length=1, max_length=128)
    prompt: str = Field(default="", max_length=32_000)
    model_alias: str = Field(min_length=1, max_length=128)
    parameters: dict[str, Any] = Field(default_factory=dict)
    inputs: list[dict[str, Any]] = Field(default_factory=list, max_length=32)


class CanvasRunRequest(BaseModel):
    canvas_id: str = Field(min_length=1, max_length=128)
    name: str = Field(default="Untitled canvas", min_length=1, max_length=255)
    nodes: list[dict[str, Any]] = Field(min_length=1, max_length=500)
    edges: list[dict[str, Any]] = Field(default_factory=list, max_length=2000)


class CanvasSelectionRequest(BaseModel):
    artifact_id: str = Field(min_length=1, max_length=128)


class ApiRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime


class ArtifactResponse(ApiRecord):
    type: str
    schema_id: str | None
    uri: str
    sha256: str
    producer_node_run_id: str | None
    input_artifact_ids: list[str]
    metadata: dict[str, Any]


class ExperimentRunResponse(ApiRecord):
    canvas_id: str
    node_id: str
    node_key: str
    status: NodeStatus
    execution_mode: str
    prompt: str
    model_alias: str
    exact_model_id: str
    parameters: dict[str, Any]
    inputs: list[dict[str, Any]]
    request_hash: str
    provider_request_id: str | None
    output_artifact_ids: list[str]
    output: dict[str, Any]
    duration_ms: int
    cost_usd: float
    cache_hit: bool
    cached_from_id: str | None
    is_baseline: bool
    error: str | None


class CanvasNodeRunResponse(ApiRecord):
    canvas_node_id: str
    node_key: str
    status: NodeStatus
    progress: int
    attempt_count: int
    provider_request_id: str | None
    provider_operation_id: str | None
    request_hash: str | None
    output_artifact_ids: list[str]
    output: dict[str, Any]
    duration_ms: int
    cost_usd: float
    error: str | None


class CanvasRunResponse(ApiRecord):
    canvas_id: str
    name: str
    status: NodeStatus
    progress: int
    graph: dict[str, Any]
    node_runs: list[CanvasNodeRunResponse]


class NodeRunResponse(ApiRecord):
    run_id: str
    node_key: str
    status: NodeStatus
    progress: int
    cost_usd: float
    provider_request_id: str | None
    provider_operation_id: str | None
    attempt_count: int
    output_artifact_ids: list[str]


class RunResponse(ApiRecord):
    name: str
    status: NodeStatus
    progress: int
    estimated_cost_usd: float
    actual_cost_usd: float
    budget_limit_usd: float
    execution_plan: dict[str, Any]
    node_runs: list[NodeRunResponse] = Field(default_factory=list)


class EventResponse(BaseModel):
    event: str
    run_id: str
    occurred_at: datetime = Field(default_factory=utc_now)
    data: dict[str, Any] = Field(default_factory=dict)
