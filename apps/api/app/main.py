from __future__ import annotations

import asyncio
import json
import mimetypes
import os
import re
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, Response, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from temporalio.client import Client

from .compiler import CompileError, DEFAULT_NODES, compile_generation_plan
from .database import (
    ArtifactRecord,
    CanvasRunRecord,
    DefinitionRecord,
    ExperimentRunRecord,
    FormatRecord,
    GenerationBriefRecord,
    NodeRunRecord,
    ReferenceRecord,
    ReferenceSetRecord,
    RunRecord,
    SessionLocal,
    create_all,
    get_db,
)
from .domain import (
    ArtifactResponse,
    ArtifactUrlImportRequest,
    CanvasRunRequest,
    CanvasRunResponse,
    CanvasSelectionRequest,
    ExperimentRunRequest,
    ExperimentRunResponse,
    ExtractionRecipeRequest,
    FrameCaptureRequest,
    FormatRunRequest,
    GenerationBriefRequest,
    GenerationRunRequest,
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
    VariationRequest,
    utc_now,
)
from .canvas_runs import canvas_run_response, create_canvas_run, local_canvas_engine, record_canvas_selection
from .canvas_temporal import CanvasRunWorkflow, CanvasWorkflowInput
from .format_extraction import FormatSource, get_format_extractor
from .media_capture import MediaCaptureError, capture_video_frame
from .providers import MODEL_REGISTRY, OPENAI_MODEL_REGISTRY
from .reference_ingest import ReferenceIngestError, get_reference_provider, render_proxy
from .experiments import experiment_response, run_experiment
from .temporal_runtime import TASK_QUEUE
from .temporal_workflow import GenerationRunWorkflow, GenerationWorkflowInput
from .storage import StorageError, artifact_content_url, extension_for, get_storage, safe_upload_key, storage_location
from .video_downloaders import configured_video_downloader_name, get_video_downloader
from .service import (
    artifact_response,
    audit,
    broker,
    canonicalize_url,
    create_artifact,
    local_engine,
    new_id,
    node_response,
    run_response,
)


CANVAS_ARTIFACT_MAX_BYTES = 250 * 1024 * 1024


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    create_all()
    get_storage().initialize()
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
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "frameflow-api",
        "storage_provider": get_storage().settings.provider,
        "generation_provider_mode": os.getenv("GENERATION_PROVIDER_MODE", "live"),
        "reference_provider_mode": os.getenv("REFERENCE_PROVIDER_MODE", "live"),
        "video_downloader_provider": configured_video_downloader_name(),
        "format_provider_mode": os.getenv("FORMAT_PROVIDER_MODE", "live"),
        "google_configured": bool(os.getenv("GOOGLE_CLOUD_PROJECT")),
        "openai_configured": bool(os.getenv("OPENAI_API_KEY")),
    }


@app.post("/experiments", response_model=ExperimentRunResponse, status_code=201)
def create_experiment(payload: ExperimentRunRequest, db: Session = Depends(get_db)) -> ExperimentRunResponse:
    try:
        record = run_experiment(db, payload)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return experiment_response(record)


@app.post("/canvas-runs", response_model=CanvasRunResponse, status_code=201)
async def start_canvas_run(payload: CanvasRunRequest, db: Session = Depends(get_db)) -> CanvasRunResponse:
    try:
        run = create_canvas_run(db, payload)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if uses_temporal():
        dependencies = {str(node.get("id")): [] for node in payload.nodes}
        for edge in payload.edges:
            dependencies[str(edge.get("target"))].append(str(edge.get("source")))
        node_keys = {str(node.get("id")): str((node.get("data") or {}).get("key") or "unknown") for node in payload.nodes}
        completed = [
            node.canvas_node_id for node in run.node_runs if node.status == NodeStatus.SUCCEEDED
        ]
        client = await temporal_client()
        await client.start_workflow(
            CanvasRunWorkflow.run,
            CanvasWorkflowInput(run.id, list(node_keys), node_keys, dependencies, completed),
            id=f"frameflow/canvas/{run.id}",
            task_queue=TASK_QUEUE,
        )
    else:
        await local_canvas_engine.start(run.id)
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
    except ValueError as exc:
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
    except ValueError as exc:
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
    return [{
        "id": row.id,
        "created_at": row.created_at,
        "type": row.type,
        "content_type": str((row.metadata_json.get("storage") or {}).get("content_type") or "application/octet-stream"),
        "size_bytes": int((row.metadata_json.get("storage") or {}).get("size_bytes") or 0),
        "filename": str(row.metadata_json.get("filename") or row.metadata_json.get("output", {}).get("title") or f"{row.type} · {row.id[:10]}"),
        "source": str(row.metadata_json.get("source") or ("generated" if row.producer_node_run_id or row.metadata_json.get("experiment_id") else "artifact")),
        "duration_ms": int(row.metadata_json.get("duration_ms") or 0),
        "url": artifact_content_url(row.id),
    } for row in rows]


@app.get("/artifacts/{artifact_id}", response_model=ArtifactResponse)
def get_artifact(artifact_id: str, db: Session = Depends(get_db)) -> ArtifactResponse:
    artifact = db.get(ArtifactRecord, artifact_id)
    if not artifact:
        raise HTTPException(404, "artifact not found")
    return artifact_response(artifact)


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
    artifact = create_artifact(
        db,
        "Image",
        input_artifact_ids=[source.id],
        content=captured.content,
        content_type=captured.content_type,
        filename=filename,
        metadata={
            "source": "video_frame_capture",
            "filename": filename,
            "source_artifact_id": source.id,
            "timestamp_ms": captured.timestamp_ms,
            "capture": {
                "operation": "ffmpeg-accurate-seek.v1",
                "source_artifact_id": source.id,
                "timestamp_ms": captured.timestamp_ms,
                "source_duration_ms": captured.source_duration_ms,
                "width": captured.width,
                "height": captured.height,
            },
            "immutable": True,
        },
    )
    db.flush()
    audit(db, "artifact.video_frame_captured", artifact.id, {
        "source_artifact_id": source.id,
        "timestamp_ms": captured.timestamp_ms,
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
        "url": artifact_content_url(artifact.id),
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
    audit(db, "artifact.canvas_uploaded", artifact.id, {"content_type": content_type, "size_bytes": len(content)})
    db.commit()
    return {
        "artifact_id": artifact.id,
        "type": artifact.type,
        "content_type": content_type,
        "size_bytes": len(content),
        "filename": file.filename or "upload.bin",
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


@app.get("/models")
def list_models() -> list[dict[str, Any]]:
    configured = bool(os.getenv("GOOGLE_CLOUD_PROJECT"))
    location = os.getenv("GOOGLE_CLOUD_LOCATION", "global")
    rows = [{
        "logical_alias": alias,
        "exact_model_id": model_id,
        "provider": "Google",
        "modality": alias.split(".")[1],
        "region": os.getenv("GOOGLE_SPEECH_LOCATION", "global") if ".stt." in alias else location,
        "status": "active" if configured else "disabled",
        "configured": configured,
    } for alias, model_id in MODEL_REGISTRY.items()]
    rows.append({
        "logical_alias": "google.localization.pipeline",
        "exact_model_id": "chirp_3 + gemini-2.5-pro + gemini-2.5-flash-tts",
        "provider": "Google",
        "modality": "video",
        "region": f"{os.getenv('GOOGLE_SPEECH_LOCATION', 'global')} / {location}",
        "status": "active" if configured else "disabled",
        "configured": configured,
    })
    openai_configured = bool(os.getenv("OPENAI_API_KEY"))
    rows.extend({
        "logical_alias": alias,
        "exact_model_id": model_id,
        "provider": "OpenAI",
        "modality": alias.split(".")[1],
        "region": "OpenAI API",
        "status": "active" if openai_configured else "disabled",
        "configured": openai_configured,
    } for alias, model_id in OPENAI_MODEL_REGISTRY.items())
    return rows
