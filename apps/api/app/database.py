from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Iterator

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, create_engine, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

from .domain import utc_now


DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./video_canvas.db")
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Timestamped:
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ReferenceRecord(Timestamped, Base):
    __tablename__ = "reference_assets"
    canonical_url: Mapped[str] = mapped_column(Text, unique=True, index=True)
    source_id: Mapped[str] = mapped_column(String(255), index=True)
    title: Mapped[str] = mapped_column(String(512))
    creator: Mapped[str] = mapped_column(String(255))
    duration_ms: Mapped[int] = mapped_column(Integer)
    rights_basis: Mapped[str] = mapped_column(String(32))
    allow_generation_input: Mapped[bool] = mapped_column(Boolean, default=False)
    allow_direct_asset_use: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(32), default="ready")
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class ReferenceSetRecord(Timestamped, Base):
    __tablename__ = "reference_sets"
    name: Mapped[str] = mapped_column(String(160))
    reference_ids: Mapped[list[str]] = mapped_column(JSON)


class DefinitionRecord(Timestamped, Base):
    __tablename__ = "definitions"
    kind: Mapped[str] = mapped_column(String(64), index=True)
    version: Mapped[int] = mapped_column(Integer)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class FormatRecord(Timestamped, Base):
    __tablename__ = "formats"
    name: Mapped[str] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(String(32), default="profile")
    parent_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    lineage: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class GenerationBriefRecord(Timestamped, Base):
    __tablename__ = "generation_briefs"
    topic: Mapped[str] = mapped_column(String(512))
    format_id: Mapped[str] = mapped_column(ForeignKey("formats.id"))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class RunRecord(Timestamped, Base):
    __tablename__ = "runs"
    name: Mapped[str] = mapped_column(String(512))
    status: Mapped[str] = mapped_column(String(32))
    progress: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, default=0)
    actual_cost_usd: Mapped[float] = mapped_column(Float, default=0)
    budget_limit_usd: Mapped[float] = mapped_column(Float, default=0)
    execution_plan: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    node_runs: Mapped[list["NodeRunRecord"]] = relationship(back_populates="run", cascade="all, delete-orphan", order_by="NodeRunRecord.ordinal")


class NodeRunRecord(Timestamped, Base):
    __tablename__ = "node_runs"
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    node_key: Mapped[str] = mapped_column(String(128))
    ordinal: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32))
    progress: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0)
    provider_request_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider_operation_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    request_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    output_artifact_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    run: Mapped[RunRecord] = relationship(back_populates="node_runs")


class ArtifactRecord(Timestamped, Base):
    __tablename__ = "artifacts"
    type: Mapped[str] = mapped_column(String(64), index=True)
    schema_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    uri: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    producer_node_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    input_artifact_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class ArtifactEdgeRecord(Timestamped, Base):
    __tablename__ = "artifact_edges"
    __table_args__ = (
        UniqueConstraint(
            "parent_artifact_id",
            "child_artifact_id",
            "role",
            "ordinal",
            name="uq_artifact_edges_relation",
        ),
    )
    parent_artifact_id: Mapped[str] = mapped_column(
        ForeignKey("artifacts.id", ondelete="CASCADE"), index=True
    )
    child_artifact_id: Mapped[str] = mapped_column(
        ForeignKey("artifacts.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(64), default="input")
    ordinal: Mapped[int] = mapped_column(Integer, default=0)
    operation_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class ExperimentRunRecord(Timestamped, Base):
    __tablename__ = "experiment_runs"
    canvas_id: Mapped[str] = mapped_column(String(128), index=True)
    node_id: Mapped[str] = mapped_column(String(128), index=True)
    node_key: Mapped[str] = mapped_column(String(128), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    execution_mode: Mapped[str] = mapped_column(String(64), default="google-live.v1")
    prompt: Mapped[str] = mapped_column(Text)
    model_alias: Mapped[str] = mapped_column(String(128))
    exact_model_id: Mapped[str] = mapped_column(String(255))
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    input_snapshot: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    request_hash: Mapped[str] = mapped_column(String(64), index=True)
    provider_request_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    output_artifact_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    output_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0)
    cache_hit: Mapped[bool] = mapped_column(Boolean, default=False)
    cached_from_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_baseline: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class CanvasRecord(Timestamped, Base):
    __tablename__ = "canvases"
    name: Mapped[str] = mapped_column(String(255))
    graph_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    active_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    workflow_definition_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    base_version_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    draft_contract_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, index=True)


class WorkflowDefinitionRecord(Timestamped, Base):
    __tablename__ = "workflow_definitions"
    name: Mapped[str] = mapped_column(String(255), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="ACTIVE", index=True)
    draft_canvas_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    current_version_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, index=True)
    versions: Mapped[list["WorkflowVersionRecord"]] = relationship(back_populates="definition", cascade="all, delete-orphan", order_by="WorkflowVersionRecord.version_number")


class WorkflowVersionRecord(Timestamped, Base):
    __tablename__ = "workflow_versions"
    __table_args__ = (
        UniqueConstraint("workflow_definition_id", "version_number", name="uq_workflow_version_number"),
        UniqueConstraint("workflow_definition_id", "source_canvas_id", "source_canvas_revision", name="uq_workflow_canvas_revision"),
    )
    workflow_definition_id: Mapped[str] = mapped_column(ForeignKey("workflow_definitions.id"), index=True)
    version_number: Mapped[int] = mapped_column(Integer)
    schema_version: Mapped[str] = mapped_column(String(64), default="workflow.version.v1")
    graph_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    input_schema_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    bindings_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    output_schema_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    source_canvas_id: Mapped[str] = mapped_column(String(64), index=True)
    source_canvas_revision: Mapped[int] = mapped_column(Integer)
    release_notes: Mapped[str] = mapped_column(Text, default="")
    published_by: Mapped[str] = mapped_column(String(128), default="local-user")
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    definition: Mapped[WorkflowDefinitionRecord] = relationship(back_populates="versions")


class WorkflowAnnotationRecord(Timestamped, Base):
    __tablename__ = "workflow_annotations"
    workflow_definition_id: Mapped[str] = mapped_column(ForeignKey("workflow_definitions.id"), index=True)
    workflow_version_id: Mapped[str | None] = mapped_column(ForeignKey("workflow_versions.id"), nullable=True, index=True)
    node_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    body: Mapped[str] = mapped_column(Text)
    position_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    color: Mapped[str] = mapped_column(String(32), default="yellow")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[str] = mapped_column(String(128), default="local-user")
    updated_by: Mapped[str] = mapped_column(String(128), default="local-user")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)


class CanvasRunRecord(Timestamped, Base):
    __tablename__ = "canvas_runs"
    canvas_id: Mapped[str] = mapped_column(String(128), index=True)
    name: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    graph_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    source_type: Mapped[str] = mapped_column(String(32), default="CANVAS_DRAFT", index=True)
    workflow_definition_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    workflow_version_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    input_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    model_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    compiler_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    node_runs: Mapped[list["CanvasNodeRunRecord"]] = relationship(back_populates="run", cascade="all, delete-orphan", order_by="CanvasNodeRunRecord.ordinal")


class CanvasNodeRunRecord(Timestamped, Base):
    __tablename__ = "canvas_node_runs"
    run_id: Mapped[str] = mapped_column(ForeignKey("canvas_runs.id"), index=True)
    canvas_node_id: Mapped[str] = mapped_column(String(128), index=True)
    node_key: Mapped[str] = mapped_column(String(128), index=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    provider_request_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider_operation_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    request_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    output_artifact_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    output_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    run: Mapped[CanvasRunRecord] = relationship(back_populates="node_runs")


class ProviderSettingRecord(Timestamped, Base):
    __tablename__ = "provider_settings"
    provider: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    configuration: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    secrets: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    source: Mapped[str] = mapped_column(String(32), default="default")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class FontRecord(Timestamped, Base):
    __tablename__ = "fonts"
    __table_args__ = (UniqueConstraint("artifact_id", "profile_version", name="uq_font_artifact_profile_version"),)
    artifact_id: Mapped[str] = mapped_column(ForeignKey("artifacts.id", ondelete="RESTRICT"), index=True)
    profile_version: Mapped[int] = mapped_column(Integer, default=1)
    supersedes_id: Mapped[str | None] = mapped_column(ForeignKey("fonts.id", ondelete="RESTRICT"), nullable=True, index=True)
    display_name: Mapped[str] = mapped_column(String(160), index=True)
    family_name: Mapped[str] = mapped_column(String(160), index=True)
    subfamily_name: Mapped[str] = mapped_column(String(96), default="Regular")
    postscript_name: Mapped[str] = mapped_column(String(160))
    weight: Mapped[int] = mapped_column(Integer, default=400)
    style: Mapped[str] = mapped_column(String(32), default="normal")
    size_adjust: Mapped[float] = mapped_column(Float, default=1.0)
    baseline_shift: Mapped[float] = mapped_column(Float, default=0.0)
    lifecycle: Mapped[str] = mapped_column(String(32), default="ACTIVE", index=True)
    license_name: Mapped[str] = mapped_column(String(160), default="User provided")
    metrics_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, index=True)


class SkillDefinitionRecord(Timestamped, Base):
    __tablename__ = "skill_definitions"
    skill_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text)
    lifecycle: Mapped[str] = mapped_column(String(32), default="ACTIVE", index=True)
    current_version_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    source: Mapped[str] = mapped_column(String(32), default="database")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, index=True)
    versions: Mapped[list["SkillVersionRecord"]] = relationship(
        back_populates="definition",
        cascade="all, delete-orphan",
        order_by="SkillVersionRecord.version_number",
    )


class SkillVersionRecord(Timestamped, Base):
    __tablename__ = "skill_versions"
    __table_args__ = (
        UniqueConstraint("skill_definition_id", "version_number", name="uq_skill_version_number"),
        UniqueConstraint("skill_definition_id", "content_digest", name="uq_skill_version_digest"),
    )
    skill_definition_id: Mapped[str] = mapped_column(ForeignKey("skill_definitions.id", ondelete="CASCADE"), index=True)
    version_number: Mapped[int] = mapped_column(Integer)
    schema_version: Mapped[str] = mapped_column(String(64), default="project.skill.v1")
    content_digest: Mapped[str] = mapped_column(String(64), index=True)
    manifest_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    instruction_body: Mapped[str] = mapped_column(Text)
    source_archive_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(128), default="local-user")
    definition: Mapped[SkillDefinitionRecord] = relationship(back_populates="versions")


class SkillInstallationRecord(Timestamped, Base):
    __tablename__ = "skill_installations"
    skill_definition_id: Mapped[str] = mapped_column(
        ForeignKey("skill_definitions.id", ondelete="CASCADE"), unique=True, index=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    permission_policy_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=lambda: {"mode": "prompt_only", "tools": []}
    )
    default_config_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class AuditEventRecord(Timestamped, Base):
    __tablename__ = "audit_events"
    action: Mapped[str] = mapped_column(String(128), index=True)
    actor_id: Mapped[str] = mapped_column(String(128), default="local-user")
    subject_id: Mapped[str] = mapped_column(String(128), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


def create_all() -> None:
    with engine.begin() as connection:
        if connection.dialect.name == "postgresql":
            # API and Temporal worker start together in Compose. Serialize schema
            # inspection/DDL so both processes cannot create the same table.
            connection.execute(text("SELECT pg_advisory_xact_lock(:lock_id)"), {"lock_id": 2026082701})
        Base.metadata.create_all(bind=connection)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
