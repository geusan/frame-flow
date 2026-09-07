from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...database import (
    ArtifactRecord,
    CanvasRecord,
    CanvasRunRecord,
    ExperimentRunRecord,
    FormatRecord,
    ProviderSettingRecord,
    ReferenceRecord,
    RunRecord,
    WorkflowDefinitionRecord,
    get_db,
)
from ...domain import NodeStatus
from ...nodes import node_registry
from ...nodes.port_types import port_type_registry
from ...provider_settings import provider_is_configured
from ...storage import get_storage
from ...video_downloaders import configured_video_downloader_name


router = APIRouter(tags=["system"])


@router.get("/health")
def health(db: Session = Depends(get_db)) -> dict[str, Any]:
    settings = {
        row.provider: row
        for row in db.scalars(select(ProviderSettingRecord)).all()
    }
    return {
        "status": "ok",
        "service": "frameflow-api",
        "storage_provider": get_storage().settings.provider,
        "generation_provider_mode": os.getenv("GENERATION_PROVIDER_MODE", "live"),
        "reference_provider_mode": os.getenv("REFERENCE_PROVIDER_MODE", "live"),
        "video_downloader_provider": configured_video_downloader_name(),
        "scene_search_provider_mode": os.getenv("SCENE_SEARCH_PROVIDER_MODE", "live"),
        "reference_analysis_mode": os.getenv("REFERENCE_ANALYSIS_MODE", "live"),
        "reference_audio_separator": os.getenv("REFERENCE_AUDIO_SEPARATOR", "demucs"),
        "format_provider_mode": os.getenv("FORMAT_PROVIDER_MODE", "live"),
        "google_configured": bool(
            settings.get("google") and provider_is_configured(settings["google"])
        ),
        "openai_configured": bool(
            settings.get("openai") and provider_is_configured(settings["openai"])
        ),
        "xai_configured": bool(
            settings.get("xai") and provider_is_configured(settings["xai"])
        ),
        "claude_configured": bool(
            settings.get("claude") and provider_is_configured(settings["claude"])
        ),
        "execution_backend": os.getenv("EXECUTION_BACKEND", "local").lower(),
    }


@router.get("/node-definitions")
def list_node_definitions() -> list[dict[str, Any]]:
    return [
        definition.public_payload()
        for definition in node_registry.list(lifecycle="ACTIVE")
    ]


@router.get("/node-port-types")
def list_node_port_types() -> dict[str, Any]:
    return port_type_registry.model_dump(mode="json")


@router.get("/workspace/summary")
def workspace_summary(db: Session = Depends(get_db)) -> dict[str, Any]:
    regular_run_count = int(
        db.scalar(select(func.count()).select_from(RunRecord)) or 0
    )
    canvas_run_count = int(
        db.scalar(select(func.count()).select_from(CanvasRunRecord)) or 0
    )
    active_statuses = [
        NodeStatus.READY,
        NodeStatus.QUEUED,
        NodeStatus.CLAIMED,
        NodeStatus.SUBMITTED,
        NodeStatus.RUNNING,
        NodeStatus.WAITING_INPUT,
        NodeStatus.RETRY_WAIT,
    ]
    active_regular = int(
        db.scalar(
            select(func.count())
            .select_from(RunRecord)
            .where(RunRecord.status.in_(active_statuses))
        )
        or 0
    )
    active_canvas = int(
        db.scalar(
            select(func.count())
            .select_from(CanvasRunRecord)
            .where(CanvasRunRecord.status.in_(active_statuses))
        )
        or 0
    )
    artifact_counts = {
        str(artifact_type): int(count)
        for artifact_type, count in db.execute(
            select(ArtifactRecord.type, func.count()).group_by(ArtifactRecord.type)
        ).all()
    }
    experiment_count = int(
        db.scalar(select(func.count()).select_from(ExperimentRunRecord)) or 0
    )
    recorded_cost = float(
        db.scalar(
            select(func.coalesce(func.sum(ExperimentRunRecord.cost_usd), 0.0))
        )
        or 0
    )
    return {
        "service": "frameflow-api",
        "environment": os.getenv("APP_ENV", "development"),
        "storage_provider": get_storage().settings.provider,
        "execution_backend": os.getenv("EXECUTION_BACKEND", "local").lower(),
        "references": int(
            db.scalar(select(func.count()).select_from(ReferenceRecord)) or 0
        ),
        "canvases": int(
            db.scalar(select(func.count()).select_from(CanvasRecord)) or 0
        ),
        "workflows": int(
            db.scalar(select(func.count()).select_from(WorkflowDefinitionRecord)) or 0
        ),
        "formats": int(
            db.scalar(select(func.count()).select_from(FormatRecord)) or 0
        ),
        "runs": regular_run_count + canvas_run_count,
        "regular_runs": regular_run_count,
        "canvas_runs": canvas_run_count,
        "active_runs": active_regular + active_canvas,
        "experiments": experiment_count,
        "recorded_cost_usd": recorded_cost,
        "images": artifact_counts.get("Image", 0),
        "characters": artifact_counts.get("Character", 0),
        "videos": artifact_counts.get("Video", 0)
        + artifact_counts.get("FinalVideo", 0),
        "audio": artifact_counts.get("Audio", 0),
        "artifacts": sum(artifact_counts.values()),
    }
