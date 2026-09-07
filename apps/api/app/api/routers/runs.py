from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...canvas_runs import (
    canvas_run_response,
    create_canvas_run,
    local_canvas_engine,
    record_canvas_approval,
    record_canvas_selection,
)
from ...canvas_temporal import CanvasRunWorkflow
from ...compiler import CompileError, DEFAULT_NODES, compile_generation_plan
from ...database import (
    CanvasRecord,
    CanvasRunRecord,
    ExperimentRunRecord,
    GenerationBriefRecord,
    NodeRunRecord,
    RunRecord,
    SessionLocal,
    get_db,
)
from ...domain import (
    CanvasNodeApprovalRequest,
    CanvasRunRequest,
    CanvasRunResponse,
    CanvasSelectionRequest,
    ExperimentRunRequest,
    ExperimentRunResponse,
    GenerationRunRequest,
    NodeStatus,
    RegenerateRequest,
    RunResponse,
    SelectionRequest,
    utc_now,
)
from ...experiments import experiment_response, run_experiment
from ...service import (
    audit,
    broker,
    create_artifact,
    local_engine,
    new_id,
    run_response,
)
from ...temporal_runtime import TASK_QUEUE
from ...temporal_workflow import GenerationRunWorkflow, GenerationWorkflowInput
from ...workflow_runtime_service import (
    schedule_canvas_run,
    temporal_client,
    uses_temporal,
)


router = APIRouter(tags=["runs"])


@router.post("/experiments", response_model=ExperimentRunResponse, status_code=201)
def create_experiment(
    payload: ExperimentRunRequest,
    db: Session = Depends(get_db),
) -> ExperimentRunResponse:
    try:
        record = run_experiment(db, payload)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(422, str(exc)) from exc
    return experiment_response(record)


@router.post("/canvas-runs", response_model=CanvasRunResponse, status_code=201)
async def start_canvas_run(
    payload: CanvasRunRequest,
    db: Session = Depends(get_db),
) -> CanvasRunResponse:
    try:
        run = create_canvas_run(db, payload)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(422, str(exc)) from exc
    canvas = db.get(CanvasRecord, payload.canvas_id)
    if canvas:
        canvas.active_run_id = run.id
        canvas.updated_at = utc_now()
        db.commit()
    await schedule_canvas_run(
        run,
        list((run.graph_snapshot or {}).get("nodes") or []),
    )
    return canvas_run_response(run)


@router.get("/canvas-runs/{run_id}", response_model=CanvasRunResponse)
def get_canvas_run(
    run_id: str,
    db: Session = Depends(get_db),
) -> CanvasRunResponse:
    run = db.get(CanvasRunRecord, run_id)
    if not run:
        raise HTTPException(404, "Canvas run not found")
    return canvas_run_response(run)


@router.get("/canvas-runs/{run_id}/events")
async def canvas_run_events(run_id: str, request: Request) -> StreamingResponse:
    async def stream() -> AsyncIterator[str]:
        previous = ""
        while not await request.is_disconnected():
            with SessionLocal() as event_db:
                run = event_db.get(CanvasRunRecord, run_id)
                if not run:
                    yield (
                        "event: canvas.run.error\n"
                        f"data: {json.dumps({'error': 'Canvas run not found'})}\n\n"
                    )
                    return
                payload = canvas_run_response(run)
                serialized = payload.model_dump_json()
                terminal = run.status in {
                    NodeStatus.SUCCEEDED,
                    NodeStatus.FAILED,
                    NodeStatus.CANCELED,
                }
            if serialized != previous:
                previous = serialized
                yield f"event: canvas.run.updated\ndata: {serialized}\n\n"
            else:
                yield ": keepalive\n\n"
            if terminal:
                return
            await asyncio.sleep(0.4)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/canvas-runs/{run_id}/cancel", response_model=CanvasRunResponse)
async def cancel_canvas_run(
    run_id: str,
    db: Session = Depends(get_db),
) -> CanvasRunResponse:
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


@router.post(
    "/canvas-runs/{run_id}/nodes/{canvas_node_id}/select",
    response_model=CanvasRunResponse,
)
async def select_canvas_candidate(
    run_id: str,
    canvas_node_id: str,
    payload: CanvasSelectionRequest,
    db: Session = Depends(get_db),
) -> CanvasRunResponse:
    run = db.get(CanvasRunRecord, run_id)
    if not run:
        raise HTTPException(404, "Canvas run not found")
    if uses_temporal():
        client = await temporal_client()
        handle = client.get_workflow_handle_for(
            CanvasRunWorkflow.run,
            f"frameflow/canvas/{run.id}",
        )
        await handle.signal(
            CanvasRunWorkflow.candidate_selected,
            canvas_node_id,
            payload.artifact_id,
        )
    else:
        try:
            record_canvas_selection(run_id, canvas_node_id, payload.artifact_id)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        await local_canvas_engine.start(run_id)
    db.expire_all()
    return canvas_run_response(db.get(CanvasRunRecord, run_id))


@router.post(
    "/canvas-runs/{run_id}/nodes/{canvas_node_id}/approve",
    response_model=CanvasRunResponse,
)
async def approve_canvas_node(
    run_id: str,
    canvas_node_id: str,
    payload: CanvasNodeApprovalRequest,
    db: Session = Depends(get_db),
) -> CanvasRunResponse:
    run = db.get(CanvasRunRecord, run_id)
    if not run:
        raise HTTPException(404, "Canvas run not found")
    if uses_temporal():
        client = await temporal_client()
        handle = client.get_workflow_handle_for(
            CanvasRunWorkflow.run,
            f"frameflow/canvas/{run.id}",
        )
        await handle.signal(
            CanvasRunWorkflow.node_approved,
            canvas_node_id,
            payload.parameters,
        )
    else:
        try:
            record_canvas_approval(run_id, canvas_node_id, payload.parameters)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        await local_canvas_engine.start(run_id)
    db.expire_all()
    return canvas_run_response(db.get(CanvasRunRecord, run_id))


@router.get("/experiments", response_model=list[ExperimentRunResponse])
def list_experiments(
    canvas_id: str = Query(min_length=1, max_length=128),
    node_id: str | None = Query(default=None, min_length=1, max_length=128),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> list[ExperimentRunResponse]:
    query = select(ExperimentRunRecord).where(
        ExperimentRunRecord.canvas_id == canvas_id
    )
    if node_id:
        query = query.where(ExperimentRunRecord.node_id == node_id)
    rows = db.scalars(
        query.order_by(ExperimentRunRecord.created_at.desc()).limit(limit)
    ).all()
    return [experiment_response(row) for row in rows]


@router.post("/experiments/{experiment_id}/baseline", response_model=ExperimentRunResponse)
def set_experiment_baseline(
    experiment_id: str,
    db: Session = Depends(get_db),
) -> ExperimentRunResponse:
    record = db.get(ExperimentRunRecord, experiment_id)
    if not record:
        raise HTTPException(404, "experiment not found")
    if record.status != NodeStatus.SUCCEEDED:
        raise HTTPException(409, "only successful experiments can be a baseline")
    siblings = db.scalars(
        select(ExperimentRunRecord).where(
            ExperimentRunRecord.canvas_id == record.canvas_id,
            ExperimentRunRecord.node_id == record.node_id,
            ExperimentRunRecord.is_baseline.is_(True),
        )
    ).all()
    for sibling in siblings:
        sibling.is_baseline = False
    record.is_baseline = True
    audit(db, "experiment.baseline_set", record.id)
    db.commit()
    db.refresh(record)
    return experiment_response(record)


@router.post("/generation-runs", response_model=RunResponse, status_code=201)
async def create_generation_run(
    payload: GenerationRunRequest,
    db: Session = Depends(get_db),
) -> RunResponse:
    brief = db.get(GenerationBriefRecord, payload.brief_id)
    if not brief:
        raise HTTPException(404, "generation brief not found")
    try:
        plan = compile_generation_plan(brief.payload, payload.workflow_definition_id)
    except CompileError as exc:
        raise HTTPException(422, str(exc)) from exc
    execution_plan = {
        **plan.payload,
        "brief_id": brief.id,
        "format_id": brief.format_id,
    }
    run = RunRecord(
        id=new_id("run"),
        name=brief.topic,
        status=NodeStatus.READY,
        progress=0,
        estimated_cost_usd=plan.estimated_cost_usd,
        actual_cost_usd=0,
        budget_limit_usd=brief.payload["budget_limit_usd"],
        execution_plan=execution_plan,
    )
    db.add(run)
    for ordinal, (node_key, _pool, _cost) in enumerate(DEFAULT_NODES):
        db.add(
            NodeRunRecord(
                id=new_id("node"),
                run_id=run.id,
                node_key=node_key,
                ordinal=ordinal,
                status=NodeStatus.READY if ordinal == 0 else NodeStatus.BLOCKED,
                progress=0,
                cost_usd=0,
                attempt_count=0,
                output_artifact_ids=[],
            )
        )
    audit(db, "run.created", run.id, {"brief_id": brief.id, "dry_run": payload.dry_run})
    db.commit()
    db.refresh(run)
    if not payload.dry_run:
        if uses_temporal():
            client = await temporal_client()
            await client.start_workflow(
                GenerationRunWorkflow.run,
                GenerationWorkflowInput(
                    run_id=run.id,
                    node_keys=[node[0] for node in DEFAULT_NODES],
                ),
                id=f"frameflow/{run.id}",
                task_queue=TASK_QUEUE,
            )
        else:
            await local_engine.start(run.id)
    return run_response(run)


@router.get("/runs/{run_id}", response_model=RunResponse)
def get_run(run_id: str, db: Session = Depends(get_db)) -> RunResponse:
    run = db.get(RunRecord, run_id)
    if not run:
        raise HTTPException(404, "run not found")
    return run_response(run)


@router.get("/runs", response_model=list[RunResponse])
def list_runs(db: Session = Depends(get_db)) -> list[RunResponse]:
    rows = db.scalars(
        select(RunRecord).order_by(RunRecord.created_at.desc())
    ).unique().all()
    return [run_response(row) for row in rows]


@router.post("/runs/{run_id}/cancel", response_model=RunResponse)
async def cancel_run(
    run_id: str,
    db: Session = Depends(get_db),
) -> RunResponse:
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


@router.get("/runs/{run_id}/events")
async def run_events(
    run_id: str,
    request: Request,
    offset: int = Query(default=0, ge=0),
) -> StreamingResponse:
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

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def require_node(node_run_id: str, db: Session) -> NodeRunRecord:
    node = db.get(NodeRunRecord, node_run_id)
    if not node:
        raise HTTPException(404, "node run not found")
    return node


@router.post("/node-runs/{node_run_id}/retry")
async def retry_node(
    node_run_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    node = require_node(node_run_id, db)
    node.status = NodeStatus.READY
    audit(db, "node.retry", node.id, {"attempt": node.attempt_count + 1})
    db.commit()
    await local_engine.start(node.run_id)
    return {
        "node_run_id": node.id,
        "status": node.status,
        "attempt_count": node.attempt_count,
    }


@router.post("/node-runs/{node_run_id}/regenerate", status_code=201)
def regenerate_node(
    node_run_id: str,
    payload: RegenerateRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    node = require_node(node_run_id, db)
    artifact = create_artifact(
        db,
        "RegenerationRequest",
        schema_id="regenerate.v1",
        producer_node_run_id=node.id,
        input_artifact_ids=node.output_artifact_ids,
        metadata=payload.model_dump(exclude_none=True),
    )
    node.status = NodeStatus.READY
    audit(db, "node.regenerate", node.id, payload.model_dump(exclude_none=True))
    db.commit()
    return {
        "node_run_id": node.id,
        "request_artifact_id": artifact.id,
        "status": node.status,
    }


@router.post("/node-runs/{node_run_id}/fork", status_code=201)
def fork_node(
    node_run_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    node = require_node(node_run_id, db)
    source = db.get(RunRecord, node.run_id)
    if not source:
        raise HTTPException(404, "source run not found")
    fork = RunRecord(
        id=new_id("run"),
        name=f"{source.name} · Fork",
        status=NodeStatus.READY,
        progress=source.progress,
        estimated_cost_usd=source.estimated_cost_usd,
        actual_cost_usd=source.actual_cost_usd,
        budget_limit_usd=source.budget_limit_usd,
        execution_plan={
            **source.execution_plan,
            "forked_from": source.id,
            "forked_at_node": node.node_key,
        },
    )
    db.add(fork)
    for old in source.node_runs:
        reusable = old.ordinal < node.ordinal and old.status == NodeStatus.SUCCEEDED
        db.add(
            NodeRunRecord(
                id=new_id("node"),
                run_id=fork.id,
                node_key=old.node_key,
                ordinal=old.ordinal,
                status=NodeStatus.SUCCEEDED if reusable else NodeStatus.STALE,
                progress=100 if reusable else 0,
                cost_usd=0,
                attempt_count=0,
                output_artifact_ids=old.output_artifact_ids if reusable else [],
            )
        )
    audit(
        db,
        "run.forked",
        fork.id,
        {"source_run_id": source.id, "node_run_id": node.id},
    )
    db.commit()
    return {
        "run_id": fork.id,
        "source_run_id": source.id,
        "forked_at": node.node_key,
    }


@router.post("/node-runs/{node_run_id}/select", status_code=201)
async def select_candidate(
    node_run_id: str,
    payload: SelectionRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    node = require_node(node_run_id, db)
    run_id = node.run_id
    db.close()
    if uses_temporal():
        client = await temporal_client()
        handle = client.get_workflow_handle_for(
            GenerationRunWorkflow.run,
            f"frameflow/{run_id}",
        )
        await handle.signal(
            GenerationRunWorkflow.candidate_selected,
            payload.artifact_id,
        )
        return {
            "node_run_id": node_run_id,
            "selected_artifact_id": payload.artifact_id,
            "status": NodeStatus.WAITING_INPUT,
            "signal_accepted": True,
        }
    try:
        await local_engine.resume_after_selection(
            run_id,
            node_run_id,
            payload.artifact_id,
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return {
        "node_run_id": node_run_id,
        "selected_artifact_id": payload.artifact_id,
        "status": NodeStatus.SUCCEEDED,
    }
