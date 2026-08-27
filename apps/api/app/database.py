from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Iterator

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, create_engine
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


class ExperimentRunRecord(Timestamped, Base):
    __tablename__ = "experiment_runs"
    canvas_id: Mapped[str] = mapped_column(String(128), index=True)
    node_id: Mapped[str] = mapped_column(String(128), index=True)
    node_key: Mapped[str] = mapped_column(String(128), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    execution_mode: Mapped[str] = mapped_column(String(32), default="deterministic")
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


class AuditEventRecord(Timestamped, Base):
    __tablename__ = "audit_events"
    action: Mapped[str] = mapped_column(String(128), index=True)
    actor_id: Mapped[str] = mapped_column(String(128), default="local-user")
    subject_id: Mapped[str] = mapped_column(String(128), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


def create_all() -> None:
    Base.metadata.create_all(bind=engine)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
