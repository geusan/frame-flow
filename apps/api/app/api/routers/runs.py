from __future__ import annotations

from ...access import AccessDenied

import asyncio
import json
from typing import Any, AsyncIterator, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from ...contexts.runs.application import (
    ApproveCanvasNodeCommand,
    CreateExperimentCommand,
    CreateGenerationRunCommand,
    RegenerateNodeCommand,
    RunApplication,
    SelectCanvasCandidateCommand,
    SelectGenerationCandidateCommand,
    StartCanvasRunCommand,
)
from ...contexts.runs.domain import RunConflictError, RunNotFoundError, RunValidationError
from ...domain import (
    CanvasNodeApprovalRequest,
    CanvasRunRequest,
    CanvasRunResponse,
    CanvasSelectionRequest,
    ExperimentRunRequest,
    ExperimentRunResponse,
    GenerationRunRequest,
    RegenerateRequest,
    RunResponse,
    SelectionRequest,
)
from ..dependencies import get_run_application


router = APIRouter(tags=["runs"])


@router.get("/costs")
def list_costs(
    owner_id: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    application: RunApplication = Depends(get_run_application),
) -> list[dict[str, Any]]:
    return application.list_costs(owner_id, limit, offset)


def _raise_run_http_error(exc: Exception) -> NoReturn:
    if isinstance(exc, RunNotFoundError):
        raise HTTPException(404, str(exc)) from exc
    if isinstance(exc, RunConflictError):
        raise HTTPException(409, str(exc)) from exc
    if isinstance(exc, RunValidationError):
        raise HTTPException(422, str(exc)) from exc
    raise exc


@router.post("/experiments", response_model=ExperimentRunResponse, status_code=201)
def create_experiment(
    payload: ExperimentRunRequest,
    application: RunApplication = Depends(get_run_application),
) -> ExperimentRunResponse:
    try:
        return application.create_experiment(
            CreateExperimentCommand(payload.model_dump(mode="python"))
        )
    except RunValidationError as exc:
        _raise_run_http_error(exc)


@router.post("/canvas-runs", response_model=CanvasRunResponse, status_code=201)
async def start_canvas_run(
    payload: CanvasRunRequest,
    application: RunApplication = Depends(get_run_application),
) -> CanvasRunResponse:
    try:
        return await application.start_canvas_run(
            StartCanvasRunCommand(payload.model_dump(mode="python"))
        )
    except RunValidationError as exc:
        _raise_run_http_error(exc)


@router.get("/canvas-runs/{run_id}", response_model=CanvasRunResponse)
def get_canvas_run(
    run_id: str,
    application: RunApplication = Depends(get_run_application),
) -> CanvasRunResponse:
    try:
        return application.get_canvas_run(run_id)
    except RunNotFoundError as exc:
        _raise_run_http_error(exc)


@router.get("/canvas-runs/{run_id}/events")
async def canvas_run_events(
    run_id: str,
    request: Request,
    application: RunApplication = Depends(get_run_application),
) -> StreamingResponse:
    async def stream() -> AsyncIterator[str]:
        previous = ""
        while not await request.is_disconnected():
            try:
                payload = application.get_canvas_run(run_id)
            except AccessDenied:
                yield "event: access.revoked\ndata: {}\n\n"
                return
            except RunNotFoundError:
                yield (
                    "event: canvas.run.error\n"
                    f"data: {json.dumps({'error': 'Canvas run not found'})}\n\n"
                )
                return
            serialized = payload.model_dump_json()
            terminal = str(payload.status) in {"SUCCEEDED", "FAILED", "CANCELED"}
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
    application: RunApplication = Depends(get_run_application),
) -> CanvasRunResponse:
    try:
        return await application.cancel_canvas_run(run_id)
    except RunNotFoundError as exc:
        _raise_run_http_error(exc)


@router.post(
    "/canvas-runs/{run_id}/nodes/{canvas_node_id}/select",
    response_model=CanvasRunResponse,
)
async def select_canvas_candidate(
    run_id: str,
    canvas_node_id: str,
    payload: CanvasSelectionRequest,
    application: RunApplication = Depends(get_run_application),
) -> CanvasRunResponse:
    try:
        return await application.select_canvas_candidate(
            SelectCanvasCandidateCommand(
                run_id=run_id,
                canvas_node_id=canvas_node_id,
                artifact_id=payload.artifact_id,
            )
        )
    except (RunConflictError, RunNotFoundError) as exc:
        _raise_run_http_error(exc)


@router.post(
    "/canvas-runs/{run_id}/nodes/{canvas_node_id}/approve",
    response_model=CanvasRunResponse,
)
async def approve_canvas_node(
    run_id: str,
    canvas_node_id: str,
    payload: CanvasNodeApprovalRequest,
    application: RunApplication = Depends(get_run_application),
) -> CanvasRunResponse:
    try:
        return await application.approve_canvas_node(
            ApproveCanvasNodeCommand(
                run_id=run_id,
                canvas_node_id=canvas_node_id,
                parameters=payload.parameters,
            )
        )
    except (RunConflictError, RunNotFoundError) as exc:
        _raise_run_http_error(exc)


@router.get("/experiments", response_model=list[ExperimentRunResponse])
def list_experiments(
    canvas_id: str = Query(min_length=1, max_length=128),
    node_id: str | None = Query(default=None, min_length=1, max_length=128),
    limit: int = Query(default=20, ge=1, le=100),
    application: RunApplication = Depends(get_run_application),
) -> list[ExperimentRunResponse]:
    return application.list_experiments(canvas_id, node_id, limit)


@router.post("/experiments/{experiment_id}/baseline", response_model=ExperimentRunResponse)
def set_experiment_baseline(
    experiment_id: str,
    application: RunApplication = Depends(get_run_application),
) -> ExperimentRunResponse:
    try:
        return application.set_experiment_baseline(experiment_id)
    except (RunConflictError, RunNotFoundError) as exc:
        _raise_run_http_error(exc)


@router.post("/generation-runs", response_model=RunResponse, status_code=201)
async def create_generation_run(
    payload: GenerationRunRequest,
    application: RunApplication = Depends(get_run_application),
) -> RunResponse:
    try:
        return await application.create_generation_run(
            CreateGenerationRunCommand(payload.model_dump(mode="python"))
        )
    except (RunNotFoundError, RunValidationError) as exc:
        _raise_run_http_error(exc)


@router.get("/runs/{run_id}", response_model=RunResponse)
def get_run(
    run_id: str,
    application: RunApplication = Depends(get_run_application),
) -> RunResponse:
    try:
        return application.get_run(run_id)
    except RunNotFoundError as exc:
        _raise_run_http_error(exc)


@router.get("/runs", response_model=list[RunResponse])
def list_runs(
    application: RunApplication = Depends(get_run_application),
) -> list[RunResponse]:
    return application.list_runs()


@router.post("/runs/{run_id}/cancel", response_model=RunResponse)
async def cancel_run(
    run_id: str,
    application: RunApplication = Depends(get_run_application),
) -> RunResponse:
    try:
        return await application.cancel_run(run_id)
    except RunNotFoundError as exc:
        _raise_run_http_error(exc)


@router.get("/runs/{run_id}/events")
async def run_events(
    run_id: str,
    request: Request,
    offset: int = Query(default=0, ge=0),
    application: RunApplication = Depends(get_run_application),
) -> StreamingResponse:
    async def stream() -> AsyncIterator[str]:
        cursor = offset
        while not await request.is_disconnected():
            events = application.event_snapshot(run_id, cursor)
            if events:
                for event in events:
                    cursor += 1
                    yield f"event: {event.event}\ndata: {event.model_dump_json()}\n\n"
            else:
                yield ": keepalive\n\n"
                await application.wait_for_event(run_id)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/node-runs/{node_run_id}/retry")
async def retry_node(
    node_run_id: str,
    application: RunApplication = Depends(get_run_application),
) -> dict[str, Any]:
    try:
        return await application.retry_node(node_run_id)
    except RunNotFoundError as exc:
        _raise_run_http_error(exc)


@router.post("/node-runs/{node_run_id}/regenerate", status_code=201)
def regenerate_node(
    node_run_id: str,
    payload: RegenerateRequest,
    application: RunApplication = Depends(get_run_application),
) -> dict[str, Any]:
    try:
        return application.regenerate_node(
            RegenerateNodeCommand(
                node_run_id=node_run_id,
                values=payload.model_dump(mode="python"),
            )
        )
    except RunNotFoundError as exc:
        _raise_run_http_error(exc)


@router.post("/node-runs/{node_run_id}/fork", status_code=201)
def fork_node(
    node_run_id: str,
    application: RunApplication = Depends(get_run_application),
) -> dict[str, Any]:
    try:
        return application.fork_node(node_run_id)
    except RunNotFoundError as exc:
        _raise_run_http_error(exc)


@router.post("/node-runs/{node_run_id}/select", status_code=201)
async def select_candidate(
    node_run_id: str,
    payload: SelectionRequest,
    application: RunApplication = Depends(get_run_application),
) -> dict[str, Any]:
    try:
        return await application.select_generation_candidate(
            SelectGenerationCandidateCommand(
                node_run_id=node_run_id,
                artifact_id=payload.artifact_id,
            )
        )
    except (RunConflictError, RunNotFoundError) as exc:
        _raise_run_http_error(exc)
