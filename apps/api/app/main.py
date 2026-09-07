from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from .api.routers import artifacts_router, canvases_router, fonts_router, formats_router, generation_router, references_router, runs_router, settings_router, skills_router, system_router, workflows_router
from .database import (
    CanvasRunRecord,
    SessionLocal,
    create_all,
)
from .domain import NodeStatus
from .canvas_runs import local_canvas_engine
from .provider_settings import (
    apply_provider_settings_to_environment,
    ensure_provider_settings,
)
from .project_skills import ensure_bundled_skills
from .storage import get_storage
from .service import backfill_artifact_edges


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    create_all()
    with SessionLocal() as settings_db:
        apply_provider_settings_to_environment(ensure_provider_settings(settings_db))
    with SessionLocal() as skill_db:
        ensure_bundled_skills(skill_db)
    get_storage().initialize()
    with SessionLocal() as lineage_db:
        if backfill_artifact_edges(lineage_db):
            lineage_db.commit()
    if not uses_temporal():
        with SessionLocal() as startup_db:
            resumable_runs = startup_db.scalars(select(CanvasRunRecord).where(CanvasRunRecord.status.in_([NodeStatus.READY, NodeStatus.RUNNING]))).unique().all()
            for run in resumable_runs:
                for node in run.node_runs:
                    if node.status == NodeStatus.RUNNING:
                        node.status = NodeStatus.READY
                run.status = NodeStatus.READY
            startup_db.commit()
            resumable_ids = [run.id for run in resumable_runs]
        for run_id in resumable_ids:
            await local_canvas_engine.start(run_id)
    yield


app = FastAPI(
    title="Frameflow Control Plane",
    version="0.1.0",
    description="Reference-isolated, artifact-first shorts workflow API",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):3\d{3}",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(artifacts_router)
app.include_router(canvases_router)
app.include_router(fonts_router)
app.include_router(formats_router)
app.include_router(generation_router)
app.include_router(references_router)
app.include_router(runs_router)
app.include_router(settings_router)
app.include_router(skills_router)
app.include_router(system_router)
app.include_router(workflows_router)


def uses_temporal() -> bool:
    return os.getenv("EXECUTION_BACKEND", "local").lower() == "temporal"
