from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from temporalio.client import Client

from .compiler import CompileError, DEFAULT_NODES, compile_generation_plan
from .database import (
    ArtifactRecord,
    DefinitionRecord,
    ExperimentRunRecord,
    FormatRecord,
    GenerationBriefRecord,
    NodeRunRecord,
    ReferenceRecord,
    ReferenceSetRecord,
    RunRecord,
    create_all,
    get_db,
)
from .domain import (
    ArtifactResponse,
    ExperimentRunRequest,
    ExperimentRunResponse,
    ExtractionRecipeRequest,
    FormatProfilePayload,
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
from .providers import MODEL_REGISTRY
from .experiments import experiment_response, run_experiment
from .temporal_runtime import TASK_QUEUE
from .temporal_workflow import GenerationRunWorkflow, GenerationWorkflowInput
from .storage import StorageError, get_storage, safe_upload_key, storage_location
from .service import (
    artifact_response,
    audit,
    broker,
    canonicalize_url,
    create_artifact,
    demo_engine,
    new_id,
    node_response,
    run_response,
    source_id_for,
)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    create_all()
    get_storage().initialize()
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
    return os.getenv("EXECUTION_BACKEND", "demo").lower() == "temporal"


async def temporal_client() -> Client:
    return await Client.connect(
        os.getenv("TEMPORAL_ADDRESS", "localhost:7233"),
        namespace=os.getenv("TEMPORAL_NAMESPACE", "default"),
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "frameflow-api", "storage_provider": get_storage().settings.provider}


@app.post("/experiments", response_model=ExperimentRunResponse, status_code=201)
def create_experiment(payload: ExperimentRunRequest, db: Session = Depends(get_db)) -> ExperimentRunResponse:
    try:
        record = run_experiment(db, payload)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return experiment_response(record)


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
    for index, raw_url in enumerate(payload.urls):
        try:
            canonical = canonicalize_url(str(raw_url))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        existing = db.scalar(select(ReferenceRecord).where(ReferenceRecord.canonical_url == canonical))
        source_id = source_id_for(canonical)
        results.append(
            ReferenceMetadata(
                canonical_url=canonical,
                source_id=source_id,
                title=f"Reference preview {source_id}",
                creator="Metadata adapter",
                duration_ms=35_000 + index * 3_000,
                width=1080,
                height=1920,
                has_subtitles=True,
                estimated_bytes=18_400_000 + index * 1_200_000,
                thumbnail_url=f"https://i.ytimg.com/vi/{source_id}/hqdefault.jpg",
                duplicate_reference_id=existing.id if existing else None,
            )
        )
    return results


@app.post("/references/import", status_code=status.HTTP_201_CREATED)
def import_reference(payload: ReferenceImportRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    existing = db.scalar(select(ReferenceRecord).where(ReferenceRecord.canonical_url == payload.metadata.canonical_url))
    if existing:
        return {"reference_id": existing.id, "deduplicated": True, "artifact_ids": []}
    reference = ReferenceRecord(
        id=new_id("ref"),
        canonical_url=payload.metadata.canonical_url,
        source_id=payload.metadata.source_id,
        title=payload.metadata.title,
        creator=payload.metadata.creator,
        duration_ms=payload.metadata.duration_ms,
        rights_basis=payload.rights_basis,
        allow_generation_input=payload.allow_generation_input,
        allow_direct_asset_use=payload.allow_direct_asset_use,
        status="ready",
        metadata_json=payload.metadata.model_dump(mode="json"),
    )
    db.add(reference)
    artifacts = [
        create_artifact(db, "ReferenceOriginal", metadata={"access_scope": "reference-analyzer-only"}, content_seed=payload.metadata.canonical_url),
        create_artifact(db, "ProxyVideo", metadata={"width": 540, "height": 960}),
        create_artifact(db, "Thumbnail", metadata={"format": "webp"}),
        create_artifact(db, "Subtitle", schema_id="subtitle.source.v1"),
    ]
    audit(db, "reference.imported", reference.id, {"rights_basis": payload.rights_basis})
    db.commit()
    return {"reference_id": reference.id, "deduplicated": False, "artifact_ids": [artifact.id for artifact in artifacts]}


@app.get("/references")
def list_references(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    rows = db.scalars(select(ReferenceRecord).order_by(ReferenceRecord.created_at.desc())).all()
    return [{"id": row.id, "created_at": row.created_at, "title": row.title, "creator": row.creator, "duration_ms": row.duration_ms, "rights_basis": row.rights_basis, "allow_generation_input": row.allow_generation_input, "status": row.status, "metadata": row.metadata_json} for row in rows]


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


def default_format_payload(reference_ids: list[str]) -> FormatProfilePayload:
    evidence = {"editing.median_shot_duration_ms": {"value": 2200, "confidence": 0.91, "evidence": [{"reference_id": reference_ids[0], "start_ms": 1700, "end_ms": 4400, "artifact_id": "scene_02"}]}}
    return FormatProfilePayload.model_validate({"core": {"duration": {"target_ms": 38_000}, "narrative": {"beats": [{"role": "hook", "start_ratio": 0, "end_ratio": 0.08, "pattern": "contradiction"}, {"role": "context", "start_ratio": 0.08, "end_ratio": 0.30}, {"role": "escalation", "start_ratio": 0.30, "end_ratio": 0.76}, {"role": "payoff", "start_ratio": 0.76, "end_ratio": 0.95}]}, "editing": {"median_shot_duration_ms": 2200, "cuts_per_10_seconds": 4.4, "transition_policy": "mostly_hard_cut"}, "captions": {"position": "center_lower", "max_lines": 2, "max_chars_per_line": 12, "words_per_chunk": 4}, "voice": {"tone": "confident_explanatory", "pace_syllables_per_second": 4.7}, "music": {"bpm_range": [110, 120], "ducking_under_voice_db": -8}, "visual": {"motion_intensity": 0.65, "preferred_shot_types": ["close_up", "medium", "detail"]}}, "extensions": {"historical_storytelling_v2": {"fact_reveal_position": 0.78, "myth_busting_pattern": "common_belief_reversal"}}, "evidence": evidence})


@app.post("/format-runs", status_code=201)
def create_format_run(payload: FormatRunRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    reference_set = db.get(ReferenceSetRecord, payload.reference_set_id)
    if not reference_set:
        raise HTTPException(404, "reference set not found")
    profile = default_format_payload(reference_set.reference_ids)
    record = FormatRecord(id=new_id("fmt"), name=payload.name, kind="profile", parent_ids=reference_set.reference_ids, payload=profile.model_dump(mode="json"), lineage={"recipe_id": payload.recipe_id, "recipe_version": payload.recipe_version})
    db.add(record)
    artifact = create_artifact(db, "FormatProfile", schema_id="format.profile.v1", content_seed=json.dumps(record.payload, sort_keys=True), metadata={"format_id": record.id})
    db.commit()
    return {"id": record.id, "name": record.name, "kind": record.kind, "payload": record.payload, "lineage": record.lineage, "artifact_id": artifact.id}


@app.get("/formats/{format_id}")
def get_format(format_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    record = db.get(FormatRecord, format_id)
    if not record:
        raise HTTPException(404, "format not found")
    return {"id": record.id, "name": record.name, "kind": record.kind, "parent_ids": record.parent_ids, "payload": record.payload, "lineage": record.lineage}


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
    run = RunRecord(id=new_id("run"), name=brief.topic, status=NodeStatus.READY, progress=0, estimated_cost_usd=plan.estimated_cost_usd, actual_cost_usd=0, budget_limit_usd=brief.payload["budget_limit_usd"], execution_plan=plan.payload)
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
            await demo_engine.start(run.id)
    return run_response(run)


@app.get("/runs/{run_id}", response_model=RunResponse)
def get_run(run_id: str, db: Session = Depends(get_db)) -> RunResponse:
    run = db.get(RunRecord, run_id)
    if not run:
        raise HTTPException(404, "run not found")
    return run_response(run)


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
    await demo_engine.start(node.run_id)
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
        await demo_engine.resume_after_selection(run_id, node_run_id, payload.artifact_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"node_run_id": node_run_id, "selected_artifact_id": payload.artifact_id, "status": NodeStatus.SUCCEEDED}


@app.get("/artifacts/{artifact_id}", response_model=ArtifactResponse)
def get_artifact(artifact_id: str, db: Session = Depends(get_db)) -> ArtifactResponse:
    artifact = db.get(ArtifactRecord, artifact_id)
    if not artifact:
        raise HTTPException(404, "artifact not found")
    return artifact_response(artifact)


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


@app.get("/artifacts/{artifact_id}/content", response_class=RedirectResponse)
def artifact_content(artifact_id: str, db: Session = Depends(get_db)) -> RedirectResponse:
    artifact = db.get(ArtifactRecord, artifact_id)
    if not artifact:
        raise HTTPException(404, "artifact not found")
    storage = get_storage()
    try:
        bucket, key = storage_location(artifact.uri, artifact.metadata_json)
        url = storage.create_download_url(bucket=bucket, key=key)
    except StorageError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse(url, status_code=307)


@app.get("/models")
def list_models() -> list[dict[str, str]]:
    return [{"logical_alias": alias, "exact_model_id": model_id, "provider": "google"} for alias, model_id in MODEL_REGISTRY.items()]
