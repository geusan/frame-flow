from __future__ import annotations

import asyncio
import base64
import json
import mimetypes
import os
import re
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Literal

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, Response, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from temporalio.client import Client

from .compiler import CompileError, DEFAULT_NODES, compile_generation_plan
from .database import (
    ArtifactRecord,
    CanvasRecord,
    CanvasRunRecord,
    DefinitionRecord,
    ExperimentRunRecord,
    FormatRecord,
    GenerationBriefRecord,
    NodeRunRecord,
    ProviderSettingRecord,
    ReferenceRecord,
    ReferenceSetRecord,
    RunRecord,
    SessionLocal,
    WorkflowAnnotationRecord,
    WorkflowDefinitionRecord,
    WorkflowVersionRecord,
    create_all,
    get_db,
)
from .domain import (
    ArtifactResponse,
    ArtifactUrlImportRequest,
    CanvasDocumentRequest,
    CanvasNodeApprovalRequest,
    CanvasRunRequest,
    CanvasRunResponse,
    CanvasSelectionRequest,
    CharacterLoraTrainRequest,
    ProviderSettingsUpdateRequest,
    ExperimentRunRequest,
    ExperimentRunResponse,
    ExtractionRecipeRequest,
    FrameCaptureRequest,
    FormatRunRequest,
    GenerationBriefRequest,
    GenerationRunRequest,
    ImageEditDocument,
    MergeRequest,
    NodeStatus,
    ReferenceImportRequest,
    ReferenceInspectRequest,
    ReferenceMetadata,
    ReferenceSetRequest,
    RegenerateRequest,
    RunResponse,
    SelectionRequest,
    SignedUrlRequest,
    SceneSearchRequest,
    VariationRequest,
    WorkflowAnnotationCreateRequest,
    WorkflowAnnotationUpdateRequest,
    WorkflowCreateRequest,
    WorkflowPublishRequest,
    WorkflowUpdateRequest,
    WorkflowVersionRunRequest,
    utc_now,
)
from .canvas_runs import canvas_dependencies, canvas_run_response, create_canvas_run, local_canvas_engine, record_canvas_approval, record_canvas_selection
from .canvas_documents import canonical_canvas_graph, canonicalize_canvas_document, legacy_canvas_graph
from .artifact_lineage import artifact_lineage_graph
from .character_lora import character_lora_state, refresh_character_lora_training, start_character_lora_training as submit_character_lora_training
from .canvas_temporal import CanvasRunWorkflow, CanvasWorkflowInput
from .format_extraction import FormatSource, get_format_extractor
from .media_capture import MediaCaptureError, capture_video_frame
from .media_compat import BrowserVideoError
from .nodes import node_registry
from .providers import FAL_MODEL_REGISTRY, MODEL_REGISTRY, OPENAI_MODEL_REGISTRY, model_id_for_alias
from .providers_fal import get_fal_generation_services
from .r2_training_storage import get_r2_training_dataset_store
from .provider_settings import (
    PROVIDER_DEFINITIONS,
    apply_provider_settings_to_environment,
    ensure_provider_settings,
    get_provider_record,
    provider_is_configured,
    provider_settings_payload,
    update_provider_settings,
)
from .project_skills import list_project_skills
from .reference_ingest import ReferenceIngestError, get_reference_provider, render_proxy
from .scene_search import SceneSearchError, search_video_scenes
from .experiments import experiment_response, run_experiment
from .temporal_runtime import TASK_QUEUE
from .temporal_workflow import GenerationRunWorkflow, GenerationWorkflowInput
from .storage import StorageError, artifact_content_url, extension_for, get_storage, safe_upload_key, storage_location
from .video_downloaders import configured_video_downloader_name, get_video_downloader
from .video_playback import ensure_video_playback_artifact
from .service import (
    artifact_response,
    audit,
    backfill_artifact_edges,
    broker,
    canonicalize_url,
    create_artifact,
    local_engine,
    new_id,
    node_response,
    run_response,
)
from .workflow_definitions import (
    DEFAULT_DRAFT_CONTRACT,
    WORKFLOW_COMPILER_VERSION,
    WorkflowContractError,
    create_annotation,
    create_workflow_definition,
    delete_annotation,
    publish_workflow_version,
    resolve_workflow_execution,
    update_annotation,
    update_workflow_definition,
    workflow_annotation_payload,
    workflow_definition_payload,
    workflow_version_payload,
)


CANVAS_ARTIFACT_MAX_BYTES = 250 * 1024 * 1024


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    create_all()
    with SessionLocal() as settings_db:
        apply_provider_settings_to_environment(ensure_provider_settings(settings_db))
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


def uses_temporal() -> bool:
    return os.getenv("EXECUTION_BACKEND", "local").lower() == "temporal"


async def temporal_client() -> Client:
    return await Client.connect(
        os.getenv("TEMPORAL_ADDRESS", "localhost:7233"),
        namespace=os.getenv("TEMPORAL_NAMESPACE", "default"),
    )


@app.get("/health")
def health(db: Session = Depends(get_db)) -> dict[str, Any]:
    settings = {row.provider: row for row in db.scalars(select(ProviderSettingRecord)).all()}
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
        "google_configured": bool(settings.get("google") and provider_is_configured(settings["google"])),
        "openai_configured": bool(settings.get("openai") and provider_is_configured(settings["openai"])),
        "execution_backend": os.getenv("EXECUTION_BACKEND", "local").lower(),
    }


@app.get("/node-definitions")
def list_node_definitions() -> list[dict[str, Any]]:
    return [definition.public_payload() for definition in node_registry.list(lifecycle="ACTIVE")]


@app.get("/skills")
def project_skills() -> list[dict[str, str]]:
    return [skill.public_payload() for skill in list_project_skills()]


@app.get("/workspace/summary")
def workspace_summary(db: Session = Depends(get_db)) -> dict[str, Any]:
    regular_run_count = int(db.scalar(select(func.count()).select_from(RunRecord)) or 0)
    canvas_run_count = int(db.scalar(select(func.count()).select_from(CanvasRunRecord)) or 0)
    active_statuses = [NodeStatus.READY, NodeStatus.QUEUED, NodeStatus.CLAIMED, NodeStatus.SUBMITTED, NodeStatus.RUNNING, NodeStatus.WAITING_INPUT, NodeStatus.RETRY_WAIT]
    active_regular = int(db.scalar(select(func.count()).select_from(RunRecord).where(RunRecord.status.in_(active_statuses))) or 0)
    active_canvas = int(db.scalar(select(func.count()).select_from(CanvasRunRecord).where(CanvasRunRecord.status.in_(active_statuses))) or 0)
    artifact_counts = {
        str(artifact_type): int(count)
        for artifact_type, count in db.execute(
            select(ArtifactRecord.type, func.count()).group_by(ArtifactRecord.type)
        ).all()
    }
    experiment_count = int(db.scalar(select(func.count()).select_from(ExperimentRunRecord)) or 0)
    recorded_cost = float(db.scalar(select(func.coalesce(func.sum(ExperimentRunRecord.cost_usd), 0.0))) or 0)
    return {
        "service": "frameflow-api",
        "environment": os.getenv("APP_ENV", "development"),
        "storage_provider": get_storage().settings.provider,
        "execution_backend": os.getenv("EXECUTION_BACKEND", "local").lower(),
        "references": int(db.scalar(select(func.count()).select_from(ReferenceRecord)) or 0),
        "canvases": int(db.scalar(select(func.count()).select_from(CanvasRecord)) or 0),
        "workflows": int(db.scalar(select(func.count()).select_from(WorkflowDefinitionRecord)) or 0),
        "formats": int(db.scalar(select(func.count()).select_from(FormatRecord)) or 0),
        "runs": regular_run_count + canvas_run_count,
        "regular_runs": regular_run_count,
        "canvas_runs": canvas_run_count,
        "active_runs": active_regular + active_canvas,
        "experiments": experiment_count,
        "recorded_cost_usd": recorded_cost,
        "images": artifact_counts.get("Image", 0),
        "characters": artifact_counts.get("Character", 0),
        "videos": artifact_counts.get("Video", 0) + artifact_counts.get("FinalVideo", 0),
        "audio": artifact_counts.get("Audio", 0),
        "artifacts": sum(artifact_counts.values()),
    }


def canvas_document_payload(record: CanvasRecord, last_run: CanvasRunRecord | None = None) -> dict[str, Any]:
    graph = legacy_canvas_graph(record.graph_json)
    return {
        "id": record.id,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "name": record.name,
        "nodes": graph.get("nodes") or [],
        "edges": graph.get("edges") or [],
        "node_count": len(graph.get("nodes") or []),
        "edge_count": len(graph.get("edges") or []),
        "active_run_id": record.active_run_id,
        "workflow_definition_id": record.workflow_definition_id,
        "base_version_id": record.base_version_id,
        "revision": record.revision,
        "draft_contract": record.draft_contract_json or DEFAULT_DRAFT_CONTRACT,
        "storage_schema_version": (
            str((record.graph_json or {}).get("schema_version"))
            if (record.graph_json or {}).get("schema_version")
            else "canvas.legacy.v1"
        ),
        "last_run": ({
            "id": last_run.id,
            "status": last_run.status,
            "progress": last_run.progress,
            "created_at": last_run.created_at,
        } if last_run else None),
    }


@app.get("/canvases")
def list_canvases(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    records = db.scalars(select(CanvasRecord).order_by(CanvasRecord.updated_at.desc())).all()
    run_rows = db.scalars(select(CanvasRunRecord).order_by(CanvasRunRecord.created_at.desc())).all()
    last_run_by_canvas: dict[str, CanvasRunRecord] = {}
    for run in run_rows:
        last_run_by_canvas.setdefault(run.canvas_id, run)
    return [canvas_document_payload(record, last_run_by_canvas.get(record.id)) for record in records]


@app.post("/canvases", status_code=status.HTTP_201_CREATED)
def create_canvas_document(payload: CanvasDocumentRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    record = CanvasRecord(
        id=new_id("canvas"),
        name=payload.name,
        graph_json=canonicalize_canvas_document(payload.nodes, payload.edges),
        active_run_id=payload.active_run_id,
        revision=1,
        draft_contract_json=payload.draft_contract or DEFAULT_DRAFT_CONTRACT,
        updated_at=utc_now(),
    )
    db.add(record)
    audit(db, "canvas.created", record.id, {"name": record.name})
    db.commit()
    db.refresh(record)
    return canvas_document_payload(record)


@app.get("/canvases/{canvas_id}")
def get_canvas_document(canvas_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    record = db.get(CanvasRecord, canvas_id)
    if not record:
        raise HTTPException(404, "canvas not found")
    last_run = db.scalar(
        select(CanvasRunRecord).where(CanvasRunRecord.canvas_id == canvas_id).order_by(CanvasRunRecord.created_at.desc())
    )
    return canvas_document_payload(record, last_run)


@app.put("/canvases/{canvas_id}")
def save_canvas_document(canvas_id: str, payload: CanvasDocumentRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    record = db.get(CanvasRecord, canvas_id)
    created = record is None
    if not record:
        record = CanvasRecord(
            id=canvas_id,
            created_at=utc_now(),
            updated_at=utc_now(),
            name=payload.name,
            graph_json=canonicalize_canvas_document([], []),
            revision=1,
            draft_contract_json=payload.draft_contract or DEFAULT_DRAFT_CONTRACT,
        )
        db.add(record)
    elif payload.expected_revision is not None and record.revision != payload.expected_revision:
        raise HTTPException(409, f"Canvas revision conflict: expected {payload.expected_revision}, current {record.revision}")
    next_graph = canonicalize_canvas_document(payload.nodes, payload.edges)
    next_contract = payload.draft_contract if payload.draft_contract is not None else (record.draft_contract_json or DEFAULT_DRAFT_CONTRACT)
    definition_changed = (
        record.name != payload.name
        or canonical_canvas_graph(record.graph_json) != canonical_canvas_graph(next_graph)
        or record.draft_contract_json != next_contract
    )
    record.name = payload.name
    record.graph_json = next_graph
    record.draft_contract_json = next_contract
    record.active_run_id = payload.active_run_id
    if not created and definition_changed:
        record.revision += 1
    record.updated_at = utc_now()
    audit(db, "canvas.imported" if created else "canvas.saved", record.id, {
        "node_count": len(payload.nodes),
        "edge_count": len(payload.edges),
    })
    db.commit()
    db.refresh(record)
    return canvas_document_payload(record)


@app.delete("/canvases/{canvas_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_canvas_document(canvas_id: str, db: Session = Depends(get_db)) -> Response:
    record = db.get(CanvasRecord, canvas_id)
    if not record:
        raise HTTPException(404, "canvas not found")
    if record.workflow_definition_id:
        raise HTTPException(409, "Workflow Draft Canvas cannot be deleted directly; archive the Workflow instead")
    db.delete(record)
    audit(db, "canvas.deleted", canvas_id)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _workflow_or_404(db: Session, workflow_id: str) -> WorkflowDefinitionRecord:
    record = db.get(WorkflowDefinitionRecord, workflow_id)
    if not record:
        raise HTTPException(404, "Workflow not found")
    return record


def _workflow_version_or_404(db: Session, workflow_id: str, version_number: int) -> WorkflowVersionRecord:
    record = db.scalar(select(WorkflowVersionRecord).where(
        WorkflowVersionRecord.workflow_definition_id == workflow_id,
        WorkflowVersionRecord.version_number == version_number,
    ))
    if not record:
        raise HTTPException(404, "Workflow Version not found")
    return record


def _workflow_contract_http_error(exc: WorkflowContractError) -> HTTPException:
    message = str(exc)
    status_code = 409 if "conflict" in message.lower() or "already belongs" in message.lower() else 422
    return HTTPException(status_code, message)


@app.post("/workflows", status_code=status.HTTP_201_CREATED)
def create_workflow(payload: WorkflowCreateRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        record = create_workflow_definition(db, payload)
    except WorkflowContractError as exc:
        raise _workflow_contract_http_error(exc) from exc
    return workflow_definition_payload(record, db)


@app.get("/workflows")
def list_workflows(status_filter: str | None = Query(default=None, alias="status"), db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    query = select(WorkflowDefinitionRecord)
    if status_filter:
        query = query.where(WorkflowDefinitionRecord.status == status_filter.upper())
    records = db.scalars(query.order_by(WorkflowDefinitionRecord.updated_at.desc())).all()
    return [workflow_definition_payload(record, db) for record in records]


@app.get("/workflows/{workflow_id}")
def get_workflow(workflow_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    return workflow_definition_payload(_workflow_or_404(db, workflow_id), db)


@app.patch("/workflows/{workflow_id}")
def update_workflow(workflow_id: str, payload: WorkflowUpdateRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    record = update_workflow_definition(db, _workflow_or_404(db, workflow_id), payload)
    return workflow_definition_payload(record, db)


@app.post("/workflows/{workflow_id}/publish", status_code=status.HTTP_201_CREATED)
def publish_workflow(workflow_id: str, payload: WorkflowPublishRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        version, warnings = publish_workflow_version(db, workflow_id, payload)
    except WorkflowContractError as exc:
        raise _workflow_contract_http_error(exc) from exc
    return {**workflow_version_payload(version), "warnings": warnings}


@app.post("/workflows/{workflow_id}/runs", response_model=CanvasRunResponse, status_code=status.HTTP_201_CREATED)
async def start_workflow_version_run(workflow_id: str, payload: WorkflowVersionRunRequest, db: Session = Depends(get_db)) -> CanvasRunResponse:
    definition = _workflow_or_404(db, workflow_id)
    if definition.status != "ACTIVE":
        raise HTTPException(422, "Archived Workflow cannot be run")
    if payload.version is not None:
        version = _workflow_version_or_404(db, workflow_id, payload.version)
    elif definition.current_version_id:
        version = db.get(WorkflowVersionRecord, definition.current_version_id)
    else:
        version = None
    if not version:
        raise HTTPException(422, "Workflow has no published Version")
    try:
        run_payload, resolved_inputs, model_snapshot = resolve_workflow_execution(db, definition, version, payload)
        run = create_canvas_run(db, run_payload)
    except (WorkflowContractError, ValueError, RuntimeError) as exc:
        raise HTTPException(422, str(exc)) from exc
    run.source_type = "WORKFLOW_VERSION"
    run.workflow_definition_id = definition.id
    run.workflow_version_id = version.id
    run.input_snapshot = resolved_inputs
    run.model_snapshot = model_snapshot
    run.compiler_version = WORKFLOW_COMPILER_VERSION
    audit(db, "workflow.run_created", run.id, {
        "workflow_definition_id": definition.id,
        "workflow_version_id": version.id,
        "version_number": version.version_number,
    })
    db.commit()
    db.refresh(run)
    await _schedule_canvas_run(run, run_payload.nodes)
    return canvas_run_response(run)


@app.get("/workflows/{workflow_id}/versions")
def list_workflow_versions(workflow_id: str, db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    _workflow_or_404(db, workflow_id)
    records = db.scalars(select(WorkflowVersionRecord).where(
        WorkflowVersionRecord.workflow_definition_id == workflow_id
    ).order_by(WorkflowVersionRecord.version_number.desc())).all()
    return [workflow_version_payload(record) for record in records]


@app.get("/workflows/{workflow_id}/versions/{version_number}")
def get_workflow_version(workflow_id: str, version_number: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    return workflow_version_payload(_workflow_version_or_404(db, workflow_id, version_number))


def _list_annotations(db: Session, workflow_id: str, version_id: str | None) -> list[dict[str, Any]]:
    query = select(WorkflowAnnotationRecord).where(
        WorkflowAnnotationRecord.workflow_definition_id == workflow_id,
        WorkflowAnnotationRecord.deleted_at.is_(None),
    )
    query = query.where(
        WorkflowAnnotationRecord.workflow_version_id == version_id
        if version_id is not None
        else WorkflowAnnotationRecord.workflow_version_id.is_(None)
    )
    records = db.scalars(query.order_by(WorkflowAnnotationRecord.created_at)).all()
    return [workflow_annotation_payload(record) for record in records]


@app.get("/workflows/{workflow_id}/annotations")
def list_workflow_annotations(workflow_id: str, db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    _workflow_or_404(db, workflow_id)
    return _list_annotations(db, workflow_id, None)


@app.post("/workflows/{workflow_id}/annotations", status_code=status.HTTP_201_CREATED)
def create_workflow_annotation(workflow_id: str, payload: WorkflowAnnotationCreateRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    record = create_annotation(db, _workflow_or_404(db, workflow_id), payload)
    return workflow_annotation_payload(record)


@app.get("/workflows/{workflow_id}/versions/{version_number}/annotations")
def list_workflow_version_annotations(workflow_id: str, version_number: int, db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    version = _workflow_version_or_404(db, workflow_id, version_number)
    return _list_annotations(db, workflow_id, version.id)


@app.post("/workflows/{workflow_id}/versions/{version_number}/annotations", status_code=status.HTTP_201_CREATED)
def create_workflow_version_annotation(workflow_id: str, version_number: int, payload: WorkflowAnnotationCreateRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    definition = _workflow_or_404(db, workflow_id)
    version = _workflow_version_or_404(db, workflow_id, version_number)
    try:
        record = create_annotation(db, definition, payload, version=version)
    except WorkflowContractError as exc:
        raise _workflow_contract_http_error(exc) from exc
    return workflow_annotation_payload(record)


@app.patch("/workflow-annotations/{annotation_id}")
def patch_workflow_annotation(annotation_id: str, payload: WorkflowAnnotationUpdateRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    record = db.get(WorkflowAnnotationRecord, annotation_id)
    if not record or record.deleted_at:
        raise HTTPException(404, "Workflow Annotation not found")
    try:
        record = update_annotation(db, record, payload)
    except WorkflowContractError as exc:
        raise _workflow_contract_http_error(exc) from exc
    return workflow_annotation_payload(record)


@app.delete("/workflow-annotations/{annotation_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_workflow_annotation(annotation_id: str, actor_id: str = Query(default="local-user", max_length=128), db: Session = Depends(get_db)) -> Response:
    record = db.get(WorkflowAnnotationRecord, annotation_id)
    if not record or record.deleted_at:
        raise HTTPException(404, "Workflow Annotation not found")
    delete_annotation(db, record, actor_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post("/workflows/{workflow_id}/archive")
def archive_workflow(workflow_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    record = _workflow_or_404(db, workflow_id)
    record.status = "ARCHIVED"
    record.updated_at = utc_now()
    audit(db, "workflow.archived", record.id)
    db.commit()
    db.refresh(record)
    return workflow_definition_payload(record, db)


@app.post("/workflows/{workflow_id}/activate")
def activate_workflow(workflow_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    record = _workflow_or_404(db, workflow_id)
    record.status = "ACTIVE"
    record.updated_at = utc_now()
    audit(db, "workflow.activated", record.id)
    db.commit()
    db.refresh(record)
    return workflow_definition_payload(record, db)


@app.get("/workflow-runs")
def list_workflow_runs(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    regular_runs = db.scalars(select(RunRecord).order_by(RunRecord.created_at.desc())).unique().all()
    for run in regular_runs:
        rows.append({
            "id": run.id,
            "created_at": run.created_at,
            "run_type": "generation",
            "name": run.name,
            "status": run.status,
            "progress": run.progress,
            "cost_usd": run.actual_cost_usd,
            "estimated_cost_usd": run.estimated_cost_usd,
            "nodes_done": sum(node.status == NodeStatus.SUCCEEDED for node in run.node_runs),
            "nodes_total": len(run.node_runs),
            "attempt_count": sum(node.attempt_count for node in run.node_runs),
            "duration_ms": None,
        })
    canvas_runs = db.scalars(select(CanvasRunRecord).order_by(CanvasRunRecord.created_at.desc())).unique().all()
    for run in canvas_runs:
        rows.append({
            "id": run.id,
            "created_at": run.created_at,
            "run_type": "workflow" if run.source_type == "WORKFLOW_VERSION" else "canvas",
            "name": run.name,
            "status": run.status,
            "progress": run.progress,
            "cost_usd": sum(node.cost_usd for node in run.node_runs),
            "estimated_cost_usd": None,
            "nodes_done": sum(node.status == NodeStatus.SUCCEEDED for node in run.node_runs),
            "nodes_total": len(run.node_runs),
            "attempt_count": sum(node.attempt_count for node in run.node_runs),
            "duration_ms": sum(node.duration_ms for node in run.node_runs) or None,
            "workflow_definition_id": run.workflow_definition_id,
            "workflow_version_id": run.workflow_version_id,
        })
    return sorted(rows, key=lambda row: row["created_at"], reverse=True)


@app.post("/experiments", response_model=ExperimentRunResponse, status_code=201)
def create_experiment(payload: ExperimentRunRequest, db: Session = Depends(get_db)) -> ExperimentRunResponse:
    try:
        record = run_experiment(db, payload)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(422, str(exc)) from exc
    return experiment_response(record)


async def _schedule_canvas_run(run: CanvasRunRecord, nodes: list[dict[str, Any]]) -> None:
    if uses_temporal():
        dependencies = canvas_dependencies(run)
        node_keys = {str(node.get("id")): str((node.get("data") or {}).get("key") or "unknown") for node in nodes}
        completed = [node.canvas_node_id for node in run.node_runs if node.status == NodeStatus.SUCCEEDED]
        approval_node_ids = [
            str(node.get("id"))
            for node in nodes
            if (node.get("data") or {}).get("waitForInput") is True
        ]
        client = await temporal_client()
        await client.start_workflow(
            CanvasRunWorkflow.run,
            CanvasWorkflowInput(run.id, list(node_keys), node_keys, dependencies, completed, approval_node_ids),
            id=f"frameflow/canvas/{run.id}",
            task_queue=TASK_QUEUE,
        )
    else:
        await local_canvas_engine.start(run.id)


@app.post("/canvas-runs", response_model=CanvasRunResponse, status_code=201)
async def start_canvas_run(payload: CanvasRunRequest, db: Session = Depends(get_db)) -> CanvasRunResponse:
    try:
        run = create_canvas_run(db, payload)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(422, str(exc)) from exc
    canvas = db.get(CanvasRecord, payload.canvas_id)
    if canvas:
        canvas.active_run_id = run.id
        canvas.updated_at = utc_now()
        db.commit()
    await _schedule_canvas_run(run, payload.nodes)
    return canvas_run_response(run)


@app.get("/canvas-runs/{run_id}", response_model=CanvasRunResponse)
def get_canvas_run(run_id: str, db: Session = Depends(get_db)) -> CanvasRunResponse:
    run = db.get(CanvasRunRecord, run_id)
    if not run:
        raise HTTPException(404, "Canvas run not found")
    return canvas_run_response(run)


@app.get("/canvas-runs/{run_id}/events")
async def canvas_run_events(run_id: str, request: Request) -> StreamingResponse:
    async def stream() -> AsyncIterator[str]:
        previous = ""
        while not await request.is_disconnected():
            with SessionLocal() as event_db:
                run = event_db.get(CanvasRunRecord, run_id)
                if not run:
                    yield f"event: canvas.run.error\ndata: {json.dumps({'error': 'Canvas run not found'})}\n\n"
                    return
                payload = canvas_run_response(run)
                serialized = payload.model_dump_json()
                terminal = run.status in {NodeStatus.SUCCEEDED, NodeStatus.FAILED, NodeStatus.CANCELED}
            if serialized != previous:
                previous = serialized
                yield f"event: canvas.run.updated\ndata: {serialized}\n\n"
            else:
                yield ": keepalive\n\n"
            if terminal:
                return
            await asyncio.sleep(0.4)
    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/canvas-runs/{run_id}/cancel", response_model=CanvasRunResponse)
async def cancel_canvas_run(run_id: str, db: Session = Depends(get_db)) -> CanvasRunResponse:
    run = db.get(CanvasRunRecord, run_id)
    if not run:
        raise HTTPException(404, "Canvas run not found")
    run.status = NodeStatus.CANCELED
    run.canceled_at = utc_now()
    for node in run.node_runs:
        if node.status not in {NodeStatus.SUCCEEDED, NodeStatus.FAILED}:
            node.status = NodeStatus.CANCELED
    db.commit()
    if uses_temporal():
        client = await temporal_client()
        await client.get_workflow_handle(f"frameflow/canvas/{run.id}").cancel()
    return canvas_run_response(run)


@app.post("/canvas-runs/{run_id}/nodes/{canvas_node_id}/select", response_model=CanvasRunResponse)
async def select_canvas_candidate(run_id: str, canvas_node_id: str, payload: CanvasSelectionRequest, db: Session = Depends(get_db)) -> CanvasRunResponse:
    run = db.get(CanvasRunRecord, run_id)
    if not run:
        raise HTTPException(404, "Canvas run not found")
    if uses_temporal():
        client = await temporal_client()
        handle = client.get_workflow_handle_for(CanvasRunWorkflow.run, f"frameflow/canvas/{run.id}")
        await handle.signal(CanvasRunWorkflow.candidate_selected, canvas_node_id, payload.artifact_id)
    else:
        try:
            record_canvas_selection(run_id, canvas_node_id, payload.artifact_id)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        await local_canvas_engine.start(run_id)
    db.expire_all()
    return canvas_run_response(db.get(CanvasRunRecord, run_id))


@app.post("/canvas-runs/{run_id}/nodes/{canvas_node_id}/approve", response_model=CanvasRunResponse)
async def approve_canvas_node(run_id: str, canvas_node_id: str, payload: CanvasNodeApprovalRequest, db: Session = Depends(get_db)) -> CanvasRunResponse:
    run = db.get(CanvasRunRecord, run_id)
    if not run:
        raise HTTPException(404, "Canvas run not found")
    if uses_temporal():
        client = await temporal_client()
        handle = client.get_workflow_handle_for(CanvasRunWorkflow.run, f"frameflow/canvas/{run.id}")
        await handle.signal(CanvasRunWorkflow.node_approved, canvas_node_id, payload.parameters)
    else:
        try:
            record_canvas_approval(run_id, canvas_node_id, payload.parameters)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        await local_canvas_engine.start(run_id)
    db.expire_all()
    return canvas_run_response(db.get(CanvasRunRecord, run_id))


@app.get("/experiments", response_model=list[ExperimentRunResponse])
def list_experiments(
    canvas_id: str = Query(min_length=1, max_length=128),
    node_id: str | None = Query(default=None, min_length=1, max_length=128),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> list[ExperimentRunResponse]:
    query = select(ExperimentRunRecord).where(ExperimentRunRecord.canvas_id == canvas_id)
    if node_id:
        query = query.where(ExperimentRunRecord.node_id == node_id)
    rows = db.scalars(query.order_by(ExperimentRunRecord.created_at.desc()).limit(limit)).all()
    return [experiment_response(row) for row in rows]


@app.post("/experiments/{experiment_id}/baseline", response_model=ExperimentRunResponse)
def set_experiment_baseline(experiment_id: str, db: Session = Depends(get_db)) -> ExperimentRunResponse:
    record = db.get(ExperimentRunRecord, experiment_id)
    if not record:
        raise HTTPException(404, "experiment not found")
    if record.status != NodeStatus.SUCCEEDED:
        raise HTTPException(409, "only successful experiments can be a baseline")
    siblings = db.scalars(select(ExperimentRunRecord).where(
        ExperimentRunRecord.canvas_id == record.canvas_id,
        ExperimentRunRecord.node_id == record.node_id,
        ExperimentRunRecord.is_baseline.is_(True),
    )).all()
    for sibling in siblings:
        sibling.is_baseline = False
    record.is_baseline = True
    audit(db, "experiment.baseline_set", record.id)
    db.commit()
    db.refresh(record)
    return experiment_response(record)


@app.post("/references/inspect", response_model=list[ReferenceMetadata])
def inspect_references(payload: ReferenceInspectRequest, db: Session = Depends(get_db)) -> list[ReferenceMetadata]:
    results: list[ReferenceMetadata] = []
    provider = get_reference_provider()
    for raw_url in payload.urls:
        try:
            inspected = provider.inspect(str(raw_url))
            canonical = canonicalize_url(inspected.canonical_url)
        except (ValueError, ReferenceIngestError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        existing = db.scalar(select(ReferenceRecord).where(ReferenceRecord.canonical_url == canonical))
        results.append(
            ReferenceMetadata(
                canonical_url=canonical,
                source_id=inspected.source_id,
                title=inspected.title,
                creator=inspected.creator,
                duration_ms=inspected.duration_ms,
                width=inspected.width,
                height=inspected.height,
                has_subtitles=inspected.has_subtitles,
                estimated_bytes=inspected.estimated_bytes,
                thumbnail_url=inspected.thumbnail_url,
                duplicate_reference_id=existing.id if existing else None,
            )
        )
    return results


@app.post("/references/import", status_code=status.HTTP_201_CREATED)
def import_reference(payload: ReferenceImportRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        canonical = canonicalize_url(payload.metadata.canonical_url)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(422, str(exc)) from exc
    existing = db.scalar(select(ReferenceRecord).where(ReferenceRecord.canonical_url == canonical))
    if existing:
        return {"reference_id": existing.id, "deduplicated": True, "artifact_ids": []}
    provider = get_reference_provider()
    try:
        inspected = provider.inspect(canonical)
        downloaded = provider.download(canonical, max_duration_seconds=600)
        proxy = render_proxy(downloaded.video)
    except ReferenceIngestError as exc:
        raise HTTPException(422, str(exc)) from exc
    reference = ReferenceRecord(
        id=new_id("ref"),
        canonical_url=canonical,
        source_id=inspected.source_id,
        title=inspected.title,
        creator=inspected.creator,
        duration_ms=inspected.duration_ms,
        rights_basis=payload.rights_basis,
        allow_generation_input=payload.allow_generation_input,
        allow_direct_asset_use=payload.allow_direct_asset_use,
        status="ready",
        metadata_json={**payload.metadata.model_dump(mode="json"), "inspected": inspected.__dict__},
    )
    db.add(reference)
    artifacts = [
        create_artifact(
            db, "ReferenceOriginal", metadata={"access_scope": "reference-analyzer-only", "reference_id": reference.id},
            content=downloaded.video, content_type=downloaded.video_content_type, filename="original.mp4",
        ),
        create_artifact(
            db, "ProxyVideo", metadata={"width": 540, "height": 960, "reference_id": reference.id},
            content=proxy, content_type="video/mp4", filename="proxy.mp4",
        ),
        create_artifact(
            db, "Thumbnail", metadata={"reference_id": reference.id}, content=downloaded.thumbnail,
            content_type=downloaded.thumbnail_content_type, filename=f"thumbnail.{downloaded.thumbnail_content_type.split('/')[-1]}",
        ),
    ]
    if downloaded.subtitle:
        artifacts.append(create_artifact(
            db, "Subtitle", schema_id="subtitle.source.v1", metadata={"reference_id": reference.id},
            content=downloaded.subtitle, content_type=downloaded.subtitle_content_type or "application/x-subrip", filename="subtitle.srt",
        ))
    audit(db, "reference.imported", reference.id, {"rights_basis": payload.rights_basis})
    db.commit()
    return {"reference_id": reference.id, "deduplicated": False, "artifact_ids": [artifact.id for artifact in artifacts]}


@app.get("/references")
def list_references(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    rows = db.scalars(select(ReferenceRecord).order_by(ReferenceRecord.created_at.desc())).all()
    thumbnails = db.scalars(select(ArtifactRecord).where(ArtifactRecord.type == "Thumbnail")).all()
    thumbnail_by_reference = {
        str(artifact.metadata_json.get("reference_id")): artifact.id
        for artifact in thumbnails
        if artifact.metadata_json.get("reference_id")
    }
    return [{
        "id": row.id,
        "created_at": row.created_at,
        "title": row.title,
        "creator": row.creator,
        "duration_ms": row.duration_ms,
        "rights_basis": row.rights_basis,
        "allow_generation_input": row.allow_generation_input,
        "status": row.status,
        "metadata": row.metadata_json,
        "thumbnail_url": artifact_content_url(thumbnail_by_reference[row.id]) if row.id in thumbnail_by_reference else None,
    } for row in rows]


@app.post("/reference-sets", status_code=201)
def create_reference_set(payload: ReferenceSetRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    known = set(db.scalars(select(ReferenceRecord.id).where(ReferenceRecord.id.in_(payload.reference_ids))).all())
    missing = set(payload.reference_ids) - known
    if missing:
        raise HTTPException(404, f"unknown references: {sorted(missing)}")
    record = ReferenceSetRecord(id=new_id("refset"), name=payload.name, reference_ids=payload.reference_ids)
    db.add(record)
    db.commit()
    return {"id": record.id, "name": record.name, "reference_ids": record.reference_ids}


@app.post("/extraction-recipes", status_code=201)
def create_extraction_recipe(payload: ExtractionRecipeRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    record = DefinitionRecord(id=new_id("recipe"), kind="extraction_recipe", version=payload.version, payload=payload.model_dump(mode="json"))
    db.add(record)
    db.commit()
    return {"id": record.id, **record.payload}


@app.post("/format-runs", status_code=201)
def create_format_run(payload: FormatRunRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    reference_set = db.get(ReferenceSetRecord, payload.reference_set_id)
    if not reference_set:
        raise HTTPException(404, "reference set not found")
    references = [db.get(ReferenceRecord, reference_id) for reference_id in reference_set.reference_ids]
    if any(reference is None for reference in references):
        raise HTTPException(404, "reference set contains a missing reference")
    proxy_artifacts = db.scalars(select(ArtifactRecord).where(ArtifactRecord.type == "ProxyVideo")).all()
    proxy_by_reference = {
        str(artifact.metadata_json.get("reference_id")): artifact
        for artifact in proxy_artifacts
        if artifact.metadata_json.get("reference_id")
    }
    storage = get_storage()
    sources: list[FormatSource] = []
    for reference in references:
        assert reference is not None
        proxy = proxy_by_reference.get(reference.id)
        if not proxy:
            raise HTTPException(409, f"reference has no ProxyVideo artifact: {reference.id}")
        bucket, key = storage_location(proxy.uri, proxy.metadata_json)
        sources.append(FormatSource(
            reference.id, reference.title, reference.creator, reference.duration_ms,
            storage.get_bytes(bucket=bucket, key=key),
            str((proxy.metadata_json.get("storage") or {}).get("content_type") or "video/mp4"),
        ))
    try:
        extracted = get_format_extractor().extract(sources)
    except Exception as exc:
        raise HTTPException(422, str(exc)) from exc
    profile = extracted.profile
    record = FormatRecord(
        id=new_id("fmt"), name=payload.name, kind="profile", parent_ids=reference_set.reference_ids,
        payload=profile.model_dump(mode="json"),
        lineage={
            "recipe_id": payload.recipe_id,
            "recipe_version": payload.recipe_version,
            "provider_request_id": extracted.provider_request_id,
            "exact_model_id": extracted.exact_model_id,
        },
    )
    db.add(record)
    content = json.dumps(record.payload, ensure_ascii=False, sort_keys=True, indent=2).encode()
    artifact = create_artifact(
        db, "FormatProfile", schema_id="format.profile.v1", content=content,
        content_type="application/json", filename="format-profile.json",
        input_artifact_ids=[proxy_by_reference[reference_id].id for reference_id in reference_set.reference_ids],
        metadata={"format_id": record.id, "provider_request_id": extracted.provider_request_id},
    )
    db.commit()
    return {"id": record.id, "name": record.name, "kind": record.kind, "payload": record.payload, "lineage": record.lineage, "artifact_id": artifact.id}


@app.get("/formats/{format_id}")
def get_format(format_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    record = db.get(FormatRecord, format_id)
    if not record:
        raise HTTPException(404, "format not found")
    return {"id": record.id, "name": record.name, "kind": record.kind, "parent_ids": record.parent_ids, "payload": record.payload, "lineage": record.lineage}


@app.get("/formats")
def list_formats(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    rows = db.scalars(select(FormatRecord).order_by(FormatRecord.created_at.desc())).all()
    return [{
        "id": row.id,
        "created_at": row.created_at,
        "name": row.name,
        "kind": row.kind,
        "parent_ids": row.parent_ids,
        "payload": row.payload,
        "lineage": row.lineage,
    } for row in rows]


@app.post("/formats/{format_id}/variants", status_code=201)
def create_variants(format_id: str, payload: VariationRequest, db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    parent = db.get(FormatRecord, format_id)
    if not parent:
        raise HTTPException(404, "format not found")
    results = []
    for index in range(payload.count):
        variant_payload = json.loads(json.dumps(parent.payload))
        previous = variant_payload["core"]["visual"]["motion_intensity"]
        new_value = round(min(1, previous + (index + 1) * 0.04), 2)
        variant_payload["core"]["visual"]["motion_intensity"] = new_value
        record = FormatRecord(id=new_id("fmtvar"), name=f"{parent.name} · Variant {index + 1}", kind="variant", parent_ids=[parent.id], payload=variant_payload, lineage={"variation_recipe": payload.model_dump(mode="json"), "diff": [{"field": "core.visual.motion_intensity", "previous": previous, "value": new_value, "reason": "diversity axis"}]})
        db.add(record)
        results.append({"id": record.id, "name": record.name, "diff": record.lineage["diff"]})
    db.commit()
    return results


@app.post("/formats/merge", status_code=201)
def merge_formats(payload: MergeRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    rows = [db.get(FormatRecord, source.format_id) for source in payload.sources]
    if any(row is None for row in rows):
        raise HTTPException(404, "one or more formats were not found")
    formats = [row for row in rows if row is not None]
    merged = json.loads(json.dumps(formats[0].payload))
    total_weight = sum(source.weight for source in payload.sources) or 1
    fields = ["median_shot_duration_ms", "cuts_per_10_seconds"]
    lineage: dict[str, Any] = {}
    for field in fields:
        value = sum(float(row.payload["core"]["editing"][field]) * source.weight for row, source in zip(formats, payload.sources, strict=True)) / total_weight
        merged["core"]["editing"][field] = round(value, 2)
        lineage[f"core.editing.{field}"] = {"value": round(value, 2), "sources": [source.model_dump() for source in payload.sources], "strategy": payload.default_strategy}
    record = FormatRecord(id=new_id("fmtmerge"), name=payload.name, kind="composition", parent_ids=[source.format_id for source in payload.sources], payload=merged, lineage=lineage)
    db.add(record)
    db.commit()
    return {"id": record.id, "name": record.name, "kind": record.kind, "payload": record.payload, "lineage": record.lineage}


@app.post("/generation-briefs", status_code=201)
def create_generation_brief(payload: GenerationBriefRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    if not db.get(FormatRecord, payload.format_id):
        raise HTTPException(404, "format not found")
    record = GenerationBriefRecord(id=new_id("brief"), topic=payload.topic, format_id=payload.format_id, payload=payload.model_dump(mode="json"))
    db.add(record)
    db.commit()
    return {"id": record.id, **record.payload}


@app.post("/generation-runs", response_model=RunResponse, status_code=201)
async def create_generation_run(payload: GenerationRunRequest, db: Session = Depends(get_db)) -> RunResponse:
    brief = db.get(GenerationBriefRecord, payload.brief_id)
    if not brief:
        raise HTTPException(404, "generation brief not found")
    try:
        plan = compile_generation_plan(brief.payload, payload.workflow_definition_id)
    except CompileError as exc:
        raise HTTPException(422, str(exc)) from exc
    execution_plan = {**plan.payload, "brief_id": brief.id, "format_id": brief.format_id}
    run = RunRecord(id=new_id("run"), name=brief.topic, status=NodeStatus.READY, progress=0, estimated_cost_usd=plan.estimated_cost_usd, actual_cost_usd=0, budget_limit_usd=brief.payload["budget_limit_usd"], execution_plan=execution_plan)
    db.add(run)
    for ordinal, (node_key, _pool, _cost) in enumerate(DEFAULT_NODES):
        db.add(NodeRunRecord(id=new_id("node"), run_id=run.id, node_key=node_key, ordinal=ordinal, status=NodeStatus.READY if ordinal == 0 else NodeStatus.BLOCKED, progress=0, cost_usd=0, attempt_count=0, output_artifact_ids=[]))
    audit(db, "run.created", run.id, {"brief_id": brief.id, "dry_run": payload.dry_run})
    db.commit()
    db.refresh(run)
    if not payload.dry_run:
        if uses_temporal():
            client = await temporal_client()
            await client.start_workflow(
                GenerationRunWorkflow.run,
                GenerationWorkflowInput(run_id=run.id, node_keys=[node[0] for node in DEFAULT_NODES]),
                id=f"frameflow/{run.id}",
                task_queue=TASK_QUEUE,
            )
        else:
            await local_engine.start(run.id)
    return run_response(run)


@app.get("/runs/{run_id}", response_model=RunResponse)
def get_run(run_id: str, db: Session = Depends(get_db)) -> RunResponse:
    run = db.get(RunRecord, run_id)
    if not run:
        raise HTTPException(404, "run not found")
    return run_response(run)


@app.get("/runs", response_model=list[RunResponse])
def list_runs(db: Session = Depends(get_db)) -> list[RunResponse]:
    rows = db.scalars(select(RunRecord).order_by(RunRecord.created_at.desc())).unique().all()
    return [run_response(row) for row in rows]


@app.post("/runs/{run_id}/cancel", response_model=RunResponse)
async def cancel_run(run_id: str, db: Session = Depends(get_db)) -> RunResponse:
    run = db.get(RunRecord, run_id)
    if not run:
        raise HTTPException(404, "run not found")
    run.status = NodeStatus.CANCELED
    run.canceled_at = utc_now()
    for node in run.node_runs:
        if node.status not in {NodeStatus.SUCCEEDED, NodeStatus.FAILED}:
            node.status = NodeStatus.CANCELED
    audit(db, "run.canceled", run.id)
    db.commit()
    if uses_temporal():
        client = await temporal_client()
        await client.get_workflow_handle(f"frameflow/{run.id}").cancel()
    return run_response(run)


@app.get("/runs/{run_id}/events")
async def run_events(run_id: str, request: Request, offset: int = Query(default=0, ge=0)) -> StreamingResponse:
    async def stream() -> AsyncIterator[str]:
        cursor = offset
        while not await request.is_disconnected():
            events = broker.snapshot(run_id, cursor)
            if events:
                for event in events:
                    cursor += 1
                    yield f"event: {event.event}\ndata: {event.model_dump_json()}\n\n"
            else:
                yield ": keepalive\n\n"
                await broker.wait(run_id)
    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def require_node(node_run_id: str, db: Session) -> NodeRunRecord:
    node = db.get(NodeRunRecord, node_run_id)
    if not node:
        raise HTTPException(404, "node run not found")
    return node


@app.post("/node-runs/{node_run_id}/retry")
async def retry_node(node_run_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    node = require_node(node_run_id, db)
    node.status = NodeStatus.READY
    audit(db, "node.retry", node.id, {"attempt": node.attempt_count + 1})
    db.commit()
    await local_engine.start(node.run_id)
    return {"node_run_id": node.id, "status": node.status, "attempt_count": node.attempt_count}


@app.post("/node-runs/{node_run_id}/regenerate", status_code=201)
def regenerate_node(node_run_id: str, payload: RegenerateRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    node = require_node(node_run_id, db)
    artifact = create_artifact(db, "RegenerationRequest", schema_id="regenerate.v1", producer_node_run_id=node.id, input_artifact_ids=node.output_artifact_ids, metadata=payload.model_dump(exclude_none=True))
    node.status = NodeStatus.READY
    audit(db, "node.regenerate", node.id, payload.model_dump(exclude_none=True))
    db.commit()
    return {"node_run_id": node.id, "request_artifact_id": artifact.id, "status": node.status}


@app.post("/node-runs/{node_run_id}/fork", status_code=201)
def fork_node(node_run_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    node = require_node(node_run_id, db)
    source = db.get(RunRecord, node.run_id)
    if not source:
        raise HTTPException(404, "source run not found")
    fork = RunRecord(id=new_id("run"), name=f"{source.name} · Fork", status=NodeStatus.READY, progress=source.progress, estimated_cost_usd=source.estimated_cost_usd, actual_cost_usd=source.actual_cost_usd, budget_limit_usd=source.budget_limit_usd, execution_plan={**source.execution_plan, "forked_from": source.id, "forked_at_node": node.node_key})
    db.add(fork)
    for old in source.node_runs:
        reusable = old.ordinal < node.ordinal and old.status == NodeStatus.SUCCEEDED
        db.add(NodeRunRecord(id=new_id("node"), run_id=fork.id, node_key=old.node_key, ordinal=old.ordinal, status=NodeStatus.SUCCEEDED if reusable else NodeStatus.STALE, progress=100 if reusable else 0, cost_usd=0, attempt_count=0, output_artifact_ids=old.output_artifact_ids if reusable else []))
    audit(db, "run.forked", fork.id, {"source_run_id": source.id, "node_run_id": node.id})
    db.commit()
    return {"run_id": fork.id, "source_run_id": source.id, "forked_at": node.node_key}


@app.post("/node-runs/{node_run_id}/select", status_code=201)
async def select_candidate(node_run_id: str, payload: SelectionRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    node = require_node(node_run_id, db)
    run_id = node.run_id
    db.close()
    if uses_temporal():
        client = await temporal_client()
        handle = client.get_workflow_handle_for(GenerationRunWorkflow.run, f"frameflow/{run_id}")
        await handle.signal(GenerationRunWorkflow.candidate_selected, payload.artifact_id)
        return {"node_run_id": node_run_id, "selected_artifact_id": payload.artifact_id, "status": NodeStatus.WAITING_INPUT, "signal_accepted": True}
    try:
        await local_engine.resume_after_selection(run_id, node_run_id, payload.artifact_id)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"node_run_id": node_run_id, "selected_artifact_id": payload.artifact_id, "status": NodeStatus.SUCCEEDED}


@app.get("/artifacts")
def list_artifacts(
    types: str = Query(default="Image,Video,Audio,Text,FinalVideo"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    requested = {value.strip() for value in types.split(",") if value.strip()}
    rows = db.scalars(
        select(ArtifactRecord).where(ArtifactRecord.type.in_(requested)).order_by(ArtifactRecord.created_at.desc()).offset(offset).limit(limit)
    ).all()
    result: list[dict[str, Any]] = []
    for row in rows:
        playback_id = str(row.metadata_json.get("playback_artifact_id") or row.id)
        result.append({
            "id": row.id,
            "created_at": row.created_at,
            "type": row.type,
            "content_type": str((row.metadata_json.get("storage") or {}).get("content_type") or "application/octet-stream"),
            "size_bytes": int((row.metadata_json.get("storage") or {}).get("size_bytes") or 0),
            "filename": str(row.metadata_json.get("filename") or row.metadata_json.get("output", {}).get("title") or f"{row.type} · {row.id[:10]}"),
            "source": str(row.metadata_json.get("source") or ("generated" if row.producer_node_run_id or row.metadata_json.get("experiment_id") else "artifact")),
            "duration_ms": int(row.metadata_json.get("duration_ms") or 0),
            "url": artifact_content_url(playback_id),
        })
    return result


@app.get("/characters")
def list_characters(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(ArtifactRecord).where(ArtifactRecord.type == "Character").order_by(ArtifactRecord.created_at.desc())
    ).all()
    result: list[dict[str, Any]] = []
    for row in rows:
        metadata = row.metadata_json or {}
        image_ids = [str(value) for value in metadata.get("image_artifact_ids") or []]
        roles = [str(value) for value in metadata.get("image_roles") or []]
        images = [
            {
                "artifact_id": artifact_id,
                "role": roles[index] if index < len(roles) else f"view_{index + 1}",
                "url": artifact_content_url(artifact_id),
            }
            for index, artifact_id in enumerate(image_ids)
            if db.get(ArtifactRecord, artifact_id)
        ]
        cover_id = str(metadata.get("cover_artifact_id") or (image_ids[0] if image_ids else ""))
        result.append({
            "id": row.id,
            "created_at": row.created_at,
            "name": str(metadata.get("name") or metadata.get("filename") or f"Character {row.id[:8]}"),
            "synopsis": str(metadata.get("synopsis") or ""),
            "model_alias": str(metadata.get("model_alias") or ""),
            "exact_model_id": str(metadata.get("exact_model_id") or ""),
            "cover_url": artifact_content_url(cover_id) if cover_id else None,
            "image_count": len(images),
            "images": images,
            "lora": {
                "status": str(metadata.get("lora_status") or "UNTRAINED"),
                "trigger_word": str(metadata.get("lora_trigger_word") or ""),
                "training_artifact_id": metadata.get("lora_training_artifact_id"),
                "artifact_id": metadata.get("lora_artifact_id"),
                "weights_url": metadata.get("lora_url"),
                "base_model": str(metadata.get("lora_base_model") or "fal-ai/flux-2"),
                "error": metadata.get("lora_error"),
            },
        })
    return result


def _character_lora_response(character: ArtifactRecord) -> dict[str, Any]:
    return character_lora_state(character)


@app.post("/characters/{character_id}/lora-training", status_code=status.HTTP_202_ACCEPTED)
def start_character_lora_training(
    character_id: str,
    payload: CharacterLoraTrainRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return submit_character_lora_training(
            db,
            character_id,
            trigger_word=payload.trigger_word,
            steps=payload.steps,
            learning_rate=payload.learning_rate,
            service=get_fal_generation_services(),
            dataset_store=get_r2_training_dataset_store(),
        )
    except ValueError as exc:
        status_code = 404 if str(exc) == "character not found" else 409 if "already running" in str(exc) else 422
        raise HTTPException(status_code, str(exc)) from exc


@app.get("/characters/{character_id}/lora-training")
def get_character_lora_training(character_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        return refresh_character_lora_training(db, character_id, service=get_fal_generation_services())
    except ValueError as exc:
        status_code = 404 if str(exc) == "character not found" else 409 if "artifact is missing" in str(exc) else 422
        raise HTTPException(status_code, str(exc)) from exc


@app.get("/artifacts/{artifact_id}", response_model=ArtifactResponse)
def get_artifact(artifact_id: str, db: Session = Depends(get_db)) -> ArtifactResponse:
    artifact = db.get(ArtifactRecord, artifact_id)
    if not artifact:
        raise HTTPException(404, "artifact not found")
    return artifact_response(artifact)


@app.post("/artifacts/{artifact_id}/audio-asset", status_code=status.HTTP_201_CREATED)
def create_audio_asset_from_reference(artifact_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    source = db.get(ArtifactRecord, artifact_id)
    if not source:
        raise HTTPException(404, "reference audio artifact not found")
    allowed_types = {
        "ReferenceAudioMix": "reference-audio.wav",
        "ReferenceVocals": "vocals.wav",
        "ReferenceAccompaniment": "accompaniment.wav",
    }
    if source.type not in allowed_types:
        raise HTTPException(415, "only Reference Analyzer audio outputs can be saved as Audio assets")

    existing = next((
        artifact
        for artifact in db.scalars(select(ArtifactRecord).where(ArtifactRecord.type == "Audio")).all()
        if artifact.metadata_json.get("source") == "reference_audio_export"
        and artifact.metadata_json.get("source_artifact_id") == source.id
    ), None)
    if existing:
        storage_metadata = existing.metadata_json.get("storage") or {}
        return {
            "artifact_id": existing.id,
            "type": existing.type,
            "content_type": str(storage_metadata.get("content_type") or "audio/wav"),
            "size_bytes": int(storage_metadata.get("size_bytes") or 0),
            "filename": str(existing.metadata_json.get("filename") or allowed_types[source.type]),
            "source": "reference_audio_export",
            "url": artifact_content_url(existing.id),
        }

    storage = get_storage()
    try:
        bucket, key = storage_location(source.uri, source.metadata_json)
        content = storage.get_bytes(bucket=bucket, key=key)
    except StorageError as exc:
        raise HTTPException(409, str(exc)) from exc

    source_storage = source.metadata_json.get("storage") or {}
    content_type = str(source_storage.get("content_type") or "audio/wav")
    filename = str(source.metadata_json.get("filename") or allowed_types[source.type])
    artifact = create_artifact(
        db,
        "Audio",
        schema_id="audio.asset.v1",
        input_artifact_ids=[source.id],
        input_artifact_roles={source.id: "reference_audio_source"},
        metadata={
            "source": "reference_audio_export",
            "source_artifact_id": source.id,
            "reference_component_type": source.type,
            "filename": filename,
            "duration_ms": int(source.metadata_json.get("duration_ms") or 0),
            "immutable": True,
            "storage_scope": "generation",
        },
        content=content,
        content_type=content_type,
        filename=filename,
    )
    audit(db, "artifact.reference_audio_exported", artifact.id, {"source_artifact_id": source.id, "source_type": source.type})
    db.commit()
    artifact_storage = artifact.metadata_json.get("storage") or {}
    return {
        "artifact_id": artifact.id,
        "type": artifact.type,
        "content_type": str(artifact_storage.get("content_type") or content_type),
        "size_bytes": int(artifact_storage.get("size_bytes") or len(content)),
        "filename": filename,
        "source": "reference_audio_export",
        "url": artifact_content_url(artifact.id),
    }


@app.get("/artifacts/{artifact_id}/lineage")
def get_artifact_lineage(
    artifact_id: str,
    direction: Literal["ancestors", "descendants", "both"] = Query(default="both"),
    depth: int = Query(default=8, ge=0, le=32),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    try:
        return artifact_lineage_graph(db, artifact_id, direction=direction, depth=depth)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.post("/artifacts/{artifact_id}/scene-search")
def search_artifact_scenes(
    artifact_id: str,
    payload: SceneSearchRequest,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    source = db.get(ArtifactRecord, artifact_id)
    if not source:
        raise HTTPException(404, "source video artifact not found")
    if source.type not in {"Video", "FinalVideo"}:
        raise HTTPException(415, "only video artifacts support scene search")
    storage = get_storage()
    try:
        bucket, key = storage_location(source.uri, source.metadata_json)
        content_type = str((source.metadata_json.get("storage") or {}).get("content_type") or "video/mp4")
        result = search_video_scenes(
            storage.get_bytes(bucket=bucket, key=key),
            content_type,
            payload.prompt,
            candidate_count=payload.candidate_count,
            sample_count=payload.sample_count,
            provider=payload.provider,
            model_alias=payload.model_alias,
        )
    except StorageError as exc:
        raise HTTPException(409, str(exc)) from exc
    except SceneSearchError as exc:
        raise HTTPException(422, str(exc)) from exc
    search_id = new_id("search")
    audit(db, "artifact.scene_searched", source.id, {
        "search_id": search_id,
        "prompt": payload.prompt,
        "provider": result.provider,
        "model_alias": result.model_alias,
        "provider_request_id": result.provider_request_id,
        "candidate_count": len(result.scenes),
    })
    db.commit()
    return {
        "search_id": search_id,
        "source_artifact_id": source.id,
        "prompt": payload.prompt,
        "provider": result.provider,
        "model_alias": result.model_alias,
        "exact_model_id": result.exact_model_id,
        "provider_request_id": result.provider_request_id,
        "source_duration_ms": result.source_duration_ms,
        "candidates": [{
            "index": scene.frame.index,
            "timestamp_ms": scene.frame.timestamp_ms,
            "score": scene.score,
            "reason": scene.reason,
            "thumbnail_data_url": f"data:{scene.frame.content_type};base64,{base64.b64encode(scene.frame.content).decode()}",
        } for scene in result.scenes],
    }


@app.post("/artifacts/{artifact_id}/capture-frame", status_code=status.HTTP_201_CREATED)
def capture_artifact_frame(
    artifact_id: str,
    payload: FrameCaptureRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    source = db.get(ArtifactRecord, artifact_id)
    if not source:
        raise HTTPException(404, "source video artifact not found")
    if source.type not in {"Video", "FinalVideo"}:
        raise HTTPException(415, "only video artifacts support frame capture")
    storage = get_storage()
    try:
        bucket, key = storage_location(source.uri, source.metadata_json)
        content_type = str((source.metadata_json.get("storage") or {}).get("content_type") or "video/mp4")
        captured = capture_video_frame(storage.get_bytes(bucket=bucket, key=key), content_type, payload.timestamp_ms)
    except StorageError as exc:
        raise HTTPException(409, str(exc)) from exc
    except MediaCaptureError as exc:
        raise HTTPException(422, str(exc)) from exc

    source_filename = str(source.metadata_json.get("filename") or source.metadata_json.get("output", {}).get("title") or source.id)
    source_stem = re.sub(r"\.[A-Za-z0-9]{1,10}$", "", source_filename)
    safe_stem = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "-", source_stem).strip(" .") or source.id
    total_seconds, milliseconds = divmod(captured.timestamp_ms, 1000)
    minutes, seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    timestamp_label = f"{hours:02d}-{minutes:02d}-{seconds:02d}-{milliseconds:03d}"
    filename = f"{safe_stem[:150]}-frame-{timestamp_label}.jpg"
    search_context = payload.model_dump(exclude={"timestamp_ms"}, exclude_none=True)
    capture_metadata = {
        "operation": "ffmpeg-accurate-seek.v1",
        "source_artifact_id": source.id,
        "timestamp_ms": captured.timestamp_ms,
        "source_duration_ms": captured.source_duration_ms,
        "width": captured.width,
        "height": captured.height,
        **({"scene_search": search_context} if search_context else {}),
    }
    artifact = create_artifact(
        db,
        "Image",
        input_artifact_ids=[source.id],
        input_artifact_roles={source.id: "source_video"},
        content=captured.content,
        content_type=captured.content_type,
        filename=filename,
        metadata={
            "source": "video_frame_capture",
            "filename": filename,
            "source_artifact_id": source.id,
            "timestamp_ms": captured.timestamp_ms,
            "capture": capture_metadata,
            "immutable": True,
        },
    )
    db.flush()
    audit(db, "artifact.video_frame_captured", artifact.id, {
        "source_artifact_id": source.id,
        "timestamp_ms": captured.timestamp_ms,
        **({"search_id": payload.search_id} if payload.search_id else {}),
    })
    db.commit()
    return {
        "id": artifact.id,
        "created_at": artifact.created_at,
        "type": artifact.type,
        "content_type": captured.content_type,
        "size_bytes": len(captured.content),
        "filename": filename,
        "source": "video_frame_capture",
        "duration_ms": 0,
        "source_artifact_id": source.id,
        "timestamp_ms": captured.timestamp_ms,
        "url": artifact_content_url(artifact.id),
    }


@app.get("/artifacts/{artifact_id}/frame-preview")
def preview_artifact_frame(
    artifact_id: str,
    timestamp_ms: int = Query(ge=0),
    db: Session = Depends(get_db),
) -> Response:
    source = db.get(ArtifactRecord, artifact_id)
    if not source:
        raise HTTPException(404, "source video artifact not found")
    if source.type not in {"Video", "FinalVideo"}:
        raise HTTPException(415, "only video artifacts support frame previews")
    storage = get_storage()
    try:
        bucket, key = storage_location(source.uri, source.metadata_json)
        content_type = str((source.metadata_json.get("storage") or {}).get("content_type") or "video/mp4")
        captured = capture_video_frame(storage.get_bytes(bucket=bucket, key=key), content_type, timestamp_ms)
    except StorageError as exc:
        raise HTTPException(409, str(exc)) from exc
    except MediaCaptureError as exc:
        raise HTTPException(422, str(exc)) from exc
    return Response(
        content=captured.content,
        media_type=captured.content_type,
        headers={
            "Cache-Control": "public, max-age=86400, immutable",
            "X-Frame-Timestamp-Ms": str(captured.timestamp_ms),
            "X-Source-Duration-Ms": str(captured.source_duration_ms),
        },
    )


@app.post("/artifacts/upload-url")
def artifact_upload_url(payload: SignedUrlRequest) -> dict[str, Any]:
    upload_id = new_id("upload")
    storage = get_storage()
    key = safe_upload_key(upload_id, payload.filename)
    try:
        target = storage.create_upload_url(bucket=storage.settings.buckets.generation, key=key, content_type=payload.content_type)
    except StorageError as exc:
        raise HTTPException(503, str(exc)) from exc
    return {
        "upload_id": upload_id,
        "provider": target.provider,
        "bucket": target.bucket,
        "object_key": target.key,
        "object_uri": target.uri,
        "method": "PUT",
        "url": target.url,
        "expires_in_seconds": target.expires_in_seconds,
        "headers": target.headers,
    }


@app.post("/artifacts/import-url", status_code=status.HTTP_201_CREATED)
def import_artifact_url(payload: ArtifactUrlImportRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    source_url = str(payload.url)
    try:
        provider = get_video_downloader()
        inspected = provider.inspect(source_url)
        downloaded = provider.download(
            inspected.canonical_url,
            max_duration_seconds=600,
            max_filesize_bytes=CANVAS_ARTIFACT_MAX_BYTES,
        )
    except ReferenceIngestError as exc:
        raise HTTPException(422, str(exc)) from exc
    if not downloaded.video:
        raise HTTPException(422, "downloaded video is empty")
    if len(downloaded.video) > CANVAS_ARTIFACT_MAX_BYTES:
        raise HTTPException(413, "downloaded video exceeds the 250 MB Canvas limit")

    content_type = downloaded.video_content_type.split(";", 1)[0].lower()
    if not content_type.startswith("video/"):
        raise HTTPException(415, "the URL did not resolve to a supported video")
    title = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "-", inspected.title).strip(" .") or inspected.source_id
    suffix = {
        "video/mp4": ".mp4",
        "video/webm": ".webm",
        "video/quicktime": ".mov",
        "video/mkv": ".mkv",
        "video/x-matroska": ".mkv",
    }.get(content_type, extension_for(content_type))
    if suffix == ".bin":
        suffix = ".video"
    filename = f"{title[:180]}{suffix}"
    artifact = create_artifact(
        db,
        "Video",
        content=downloaded.video,
        content_type=content_type,
        filename=filename,
        metadata={
            "source": "canvas_url_import",
            "source_url": inspected.canonical_url,
            "source_id": inspected.source_id,
            "source_title": inspected.title,
            "source_creator": inspected.creator,
            "downloader_provider": provider.provider_name,
            "duration_ms": inspected.duration_ms,
            "filename": filename,
            "immutable": True,
        },
    )
    db.flush()
    try:
        playback_artifact = ensure_video_playback_artifact(
            db,
            artifact,
            content=downloaded.video,
            content_type=content_type,
            filename=filename,
        )
    except BrowserVideoError as exc:
        db.rollback()
        raise HTTPException(422, str(exc)) from exc
    audit(db, "artifact.canvas_url_imported", artifact.id, {
        "source_url": inspected.canonical_url,
        "downloader_provider": provider.provider_name,
        "content_type": content_type,
        "size_bytes": len(downloaded.video),
    })
    db.commit()
    return {
        "artifact_id": artifact.id,
        "type": artifact.type,
        "content_type": content_type,
        "size_bytes": len(downloaded.video),
        "filename": filename,
        "source_url": inspected.canonical_url,
        "downloader_provider": provider.provider_name,
        "url": artifact_content_url(playback_artifact.id),
    }


@app.post("/artifacts/upload", status_code=status.HTTP_201_CREATED)
async def upload_artifact(file: UploadFile = File(...), db: Session = Depends(get_db)) -> dict[str, Any]:
    content_type = (file.content_type or "application/octet-stream").split(";", 1)[0].lower()
    if content_type == "application/octet-stream" and file.filename:
        content_type = (mimetypes.guess_type(file.filename)[0] or content_type).lower()
    artifact_type = (
        "Image" if content_type.startswith("image/")
        else "Video" if content_type.startswith("video/")
        else "Audio" if content_type.startswith("audio/")
        else "Text" if content_type.startswith("text/")
        else None
    )
    if not artifact_type:
        raise HTTPException(415, "only image, video, audio, and text files can be added to the Canvas")
    content = await file.read(CANVAS_ARTIFACT_MAX_BYTES + 1)
    if not content:
        raise HTTPException(422, "uploaded file is empty")
    if len(content) > CANVAS_ARTIFACT_MAX_BYTES:
        raise HTTPException(413, "uploaded file exceeds the 250 MB Canvas limit")
    artifact = create_artifact(
        db,
        artifact_type,
        content=content,
        content_type=content_type,
        filename=file.filename or "upload.bin",
        metadata={"source": "canvas_upload", "filename": file.filename or "upload.bin", "immutable": True},
    )
    db.flush()
    playback_artifact = artifact
    if artifact_type == "Video":
        try:
            playback_artifact = ensure_video_playback_artifact(
                db,
                artifact,
                content=content,
                content_type=content_type,
                filename=file.filename or "upload.mp4",
            )
        except BrowserVideoError as exc:
            db.rollback()
            raise HTTPException(422, str(exc)) from exc
    audit(db, "artifact.canvas_uploaded", artifact.id, {"content_type": content_type, "size_bytes": len(content)})
    db.commit()
    return {
        "artifact_id": artifact.id,
        "type": artifact.type,
        "content_type": content_type,
        "size_bytes": len(content),
        "filename": file.filename or "upload.bin",
        "url": artifact_content_url(playback_artifact.id),
    }


@app.post("/artifacts/{artifact_id}/image-edits", status_code=status.HTTP_201_CREATED)
async def save_manual_image_edit(
    artifact_id: str,
    file: UploadFile = File(...),
    edit_document: str = Form(...),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    source = db.get(ArtifactRecord, artifact_id)
    if not source:
        raise HTTPException(404, "source image artifact not found")
    if source.type != "Image":
        raise HTTPException(415, "only image artifacts can be edited")
    content_type = (file.content_type or "").split(";", 1)[0].lower()
    if content_type not in {"image/png", "image/jpeg", "image/webp"}:
        raise HTTPException(415, "edited image must be PNG, JPEG, or WebP")
    if len(edit_document.encode()) > 32_000:
        raise HTTPException(413, "image edit document is too large")
    try:
        document = ImageEditDocument.model_validate(json.loads(edit_document))
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(422, f"invalid image edit document: {exc}") from exc
    content = await file.read(CANVAS_ARTIFACT_MAX_BYTES + 1)
    if not content:
        raise HTTPException(422, "edited image is empty")
    if len(content) > CANVAS_ARTIFACT_MAX_BYTES:
        raise HTTPException(413, "edited image exceeds the 250 MB Canvas limit")

    source_filename = str(source.metadata_json.get("filename") or f"{source.id}.png")
    source_stem = re.sub(r"\.[A-Za-z0-9]{1,10}$", "", source_filename)
    safe_stem = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "-", source_stem).strip(" .") or source.id
    extension = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}[content_type]
    filename = f"{safe_stem[:170]}-edited{extension}"
    document_payload = document.model_dump(exclude_none=True)
    artifact = create_artifact(
        db,
        "Image",
        schema_id="image.manual-edit.v1",
        input_artifact_ids=[source.id],
        input_artifact_roles={source.id: "source_image"},
        content=content,
        content_type=content_type,
        filename=filename,
        metadata={
            "source": "image_manual_edit",
            "filename": filename,
            "operation": "image.manual.edit",
            "image_edit": document_payload,
            "immutable": True,
        },
    )
    db.flush()
    audit(db, "artifact.image_manually_edited", artifact.id, {
        "source_artifact_id": source.id,
        "content_type": content_type,
        "image_edit": document_payload,
    })
    db.commit()
    return {
        "id": artifact.id,
        "created_at": artifact.created_at,
        "type": artifact.type,
        "content_type": content_type,
        "size_bytes": len(content),
        "filename": filename,
        "source": "image_manual_edit",
        "duration_ms": 0,
        "url": artifact_content_url(artifact.id),
    }


@app.get("/artifacts/{artifact_id}/download-url")
def artifact_download_url(artifact_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    artifact = db.get(ArtifactRecord, artifact_id)
    if not artifact:
        raise HTTPException(404, "artifact not found")
    storage = get_storage()
    try:
        bucket, key = storage_location(artifact.uri, artifact.metadata_json)
        url = storage.create_download_url(bucket=bucket, key=key)
    except StorageError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"provider": storage.settings.provider, "url": url, "expires_in_seconds": storage.settings.signed_url_ttl_seconds}


@app.get("/artifacts/{artifact_id}/content")
def artifact_content(artifact_id: str, request: Request, db: Session = Depends(get_db)) -> Response:
    artifact = db.get(ArtifactRecord, artifact_id)
    if not artifact:
        raise HTTPException(404, "artifact not found")
    storage = get_storage()
    try:
        bucket, key = storage_location(artifact.uri, artifact.metadata_json)
        if storage.settings.provider == "memory":
            content_type = str((artifact.metadata_json.get("storage") or {}).get("content_type") or "application/octet-stream")
            content = storage.get_bytes(bucket=bucket, key=key)
            range_header = request.headers.get("range")
            if not range_header:
                return Response(content, media_type=content_type, headers={
                    "Accept-Ranges": "bytes",
                    "Content-Length": str(len(content)),
                })
            match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header.strip())
            if not match or not any(match.groups()):
                return Response(status_code=416, headers={"Content-Range": f"bytes */{len(content)}"})
            start_text, end_text = match.groups()
            if start_text:
                start = int(start_text)
                end = min(int(end_text), len(content) - 1) if end_text else len(content) - 1
            else:
                suffix_length = int(end_text)
                start = max(0, len(content) - suffix_length)
                end = len(content) - 1
            if start >= len(content) or end < start:
                return Response(status_code=416, headers={"Content-Range": f"bytes */{len(content)}"})
            partial = content[start:end + 1]
            return Response(partial, status_code=206, media_type=content_type, headers={
                "Accept-Ranges": "bytes",
                "Content-Range": f"bytes {start}-{end}/{len(content)}",
                "Content-Length": str(len(partial)),
            })
        url = storage.create_download_url(bucket=bucket, key=key)
    except StorageError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse(url, status_code=307)


@app.get("/settings/providers")
def list_provider_settings(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    return [provider_settings_payload(record) for record in ensure_provider_settings(db)]


@app.put("/settings/providers/{provider}")
def save_provider_settings(
    provider: str,
    payload: ProviderSettingsUpdateRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    normalized_provider = provider.strip().lower()
    if normalized_provider not in PROVIDER_DEFINITIONS:
        raise HTTPException(404, "provider not found")
    record = get_provider_record(db, normalized_provider)
    if not record:
        ensure_provider_settings(db)
        record = get_provider_record(db, normalized_provider)
    if not record:
        raise HTTPException(404, "provider not found")
    try:
        updated = update_provider_settings(
            db,
            record,
            enabled=payload.enabled,
            auth_method=payload.auth_method,
            values=payload.values,
            clear_fields=payload.clear_fields,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    audit(db, "provider.settings.updated", updated.id, {
        "provider": normalized_provider,
        "enabled": updated.enabled,
        "auth_method": payload.auth_method,
        "updated_fields": sorted(payload.values),
        "cleared_fields": sorted(payload.clear_fields),
    })
    db.commit()
    return provider_settings_payload(updated)


@app.get("/models")
def list_models(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    usage = {
        str(alias): {
            "usage_count": int(count),
            "recorded_cost_usd": float(cost or 0),
            "last_used_at": last_used_at,
        }
        for alias, count, cost, last_used_at in db.execute(
            select(
                ExperimentRunRecord.model_alias,
                func.count(),
                func.coalesce(func.sum(ExperimentRunRecord.cost_usd), 0.0),
                func.max(ExperimentRunRecord.created_at),
            ).group_by(ExperimentRunRecord.model_alias)
        ).all()
    }
    google_settings = get_provider_record(db, "google")
    google_configuration = dict(google_settings.configuration or {}) if google_settings else {}
    configured = bool(google_settings and provider_is_configured(google_settings))
    google_project = google_configuration.get("project_id") or None
    google_auth_method = str(google_configuration.get("_auth_method") or "vertex")
    using_gemini_api = google_auth_method == "api_key"
    location = "Gemini API" if using_gemini_api else str(google_configuration.get("location") or "global")
    speech_location = str(google_configuration.get("speech_location") or "us")
    rows = [{
        "logical_alias": alias,
        "exact_model_id": model_id_for_alias(alias, gemini_api=using_gemini_api) or model_id,
        "provider": "Google",
        "modality": alias.split(".")[1],
        "region": (
            speech_location
            if ".stt." in alias
            else "global"
            if alias == "google.tts.latest" and not using_gemini_api
            else location
        ),
        "status": "active" if configured else "disabled",
        "configured": configured,
        "configuration": "Gemini API key configured" if using_gemini_api and configured else google_project or "Google credentials are not configured",
        **usage.get(alias, {"usage_count": 0, "recorded_cost_usd": 0.0, "last_used_at": None}),
    } for alias, model_id in MODEL_REGISTRY.items()]
    rows.append({
        "logical_alias": "google.localization.pipeline",
        "exact_model_id": "chirp_3 + gemini-3.1-pro-preview + gemini-2.5-flash-tts",
        "provider": "Google",
        "modality": "video",
        "region": f"{speech_location} / {location}",
        "status": "active" if configured else "disabled",
        "configured": configured,
        "configuration": "Gemini API key configured" if using_gemini_api and configured else google_project or "Google credentials are not configured",
        **usage.get("google.localization.pipeline", {"usage_count": 0, "recorded_cost_usd": 0.0, "last_used_at": None}),
    })
    openai_settings = get_provider_record(db, "openai")
    openai_configured = bool(openai_settings and provider_is_configured(openai_settings))
    rows.extend({
        "logical_alias": alias,
        "exact_model_id": model_id,
        "provider": "OpenAI",
        "modality": alias.split(".")[1],
        "region": "OpenAI API",
        "status": "active" if openai_configured else "disabled",
        "configured": openai_configured,
        "configuration": "OPENAI_API_KEY configured" if openai_configured else "OPENAI_API_KEY is not set",
        **usage.get(alias, {"usage_count": 0, "recorded_cost_usd": 0.0, "last_used_at": None}),
    } for alias, model_id in OPENAI_MODEL_REGISTRY.items())
    fal_settings = get_provider_record(db, "fal")
    fal_configured = bool(fal_settings and provider_is_configured(fal_settings))
    rows.extend({
        "logical_alias": alias,
        "exact_model_id": model_id,
        "provider": "fal.ai",
        "modality": alias.split(".")[1],
        "region": "fal Queue API",
        "status": "active" if fal_configured else "disabled",
        "configured": fal_configured,
        "configuration": "FAL_KEY configured" if fal_configured else "FAL_KEY is not set",
        **usage.get(alias, {"usage_count": 0, "recorded_cost_usd": 0.0, "last_used_at": None}),
    } for alias, model_id in FAL_MODEL_REGISTRY.items())
    return rows
