from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...canvas_runs import canvas_run_response, create_canvas_run
from ...database import (
    CanvasRunRecord,
    RunRecord,
    WorkflowAnnotationRecord,
    WorkflowDefinitionRecord,
    WorkflowVersionRecord,
    get_db,
)
from ...domain import (
    CanvasRunResponse,
    NodeStatus,
    WorkflowAnnotationCreateRequest,
    WorkflowAnnotationUpdateRequest,
    WorkflowCreateRequest,
    WorkflowPublishRequest,
    WorkflowUpdateRequest,
    WorkflowVersionRunRequest,
    utc_now,
)
from ...service import audit
from ...workflow_definitions import (
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
from ...workflow_runtime_service import schedule_canvas_run


router = APIRouter(tags=["workflows"])


def _workflow_or_404(db: Session, workflow_id: str) -> WorkflowDefinitionRecord:
    record = db.get(WorkflowDefinitionRecord, workflow_id)
    if not record:
        raise HTTPException(404, "Workflow not found")
    return record


def _workflow_version_or_404(
    db: Session,
    workflow_id: str,
    version_number: int,
) -> WorkflowVersionRecord:
    record = db.scalar(
        select(WorkflowVersionRecord).where(
            WorkflowVersionRecord.workflow_definition_id == workflow_id,
            WorkflowVersionRecord.version_number == version_number,
        )
    )
    if not record:
        raise HTTPException(404, "Workflow Version not found")
    return record


def _workflow_contract_http_error(exc: WorkflowContractError) -> HTTPException:
    message = str(exc)
    status_code = (
        409
        if "conflict" in message.lower() or "already belongs" in message.lower()
        else 422
    )
    return HTTPException(status_code, message)


@router.post("/workflows", status_code=status.HTTP_201_CREATED)
def create_workflow(
    payload: WorkflowCreateRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        record = create_workflow_definition(db, payload)
    except WorkflowContractError as exc:
        raise _workflow_contract_http_error(exc) from exc
    return workflow_definition_payload(record, db)


@router.get("/workflows")
def list_workflows(
    status_filter: str | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    query = select(WorkflowDefinitionRecord)
    if status_filter:
        query = query.where(WorkflowDefinitionRecord.status == status_filter.upper())
    records = db.scalars(
        query.order_by(WorkflowDefinitionRecord.updated_at.desc())
    ).all()
    return [workflow_definition_payload(record, db) for record in records]


@router.get("/workflows/{workflow_id}")
def get_workflow(
    workflow_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return workflow_definition_payload(_workflow_or_404(db, workflow_id), db)


@router.patch("/workflows/{workflow_id}")
def update_workflow(
    workflow_id: str,
    payload: WorkflowUpdateRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    record = update_workflow_definition(db, _workflow_or_404(db, workflow_id), payload)
    return workflow_definition_payload(record, db)


@router.post("/workflows/{workflow_id}/publish", status_code=status.HTTP_201_CREATED)
def publish_workflow(
    workflow_id: str,
    payload: WorkflowPublishRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        version, warnings = publish_workflow_version(db, workflow_id, payload)
    except WorkflowContractError as exc:
        raise _workflow_contract_http_error(exc) from exc
    return {**workflow_version_payload(version), "warnings": warnings}


@router.post(
    "/workflows/{workflow_id}/runs",
    response_model=CanvasRunResponse,
    status_code=status.HTTP_201_CREATED,
)
async def start_workflow_version_run(
    workflow_id: str,
    payload: WorkflowVersionRunRequest,
    db: Session = Depends(get_db),
) -> CanvasRunResponse:
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
        run_payload, resolved_inputs, model_snapshot = resolve_workflow_execution(
            db,
            definition,
            version,
            payload,
        )
        run = create_canvas_run(db, run_payload)
    except (WorkflowContractError, ValueError, RuntimeError) as exc:
        raise HTTPException(422, str(exc)) from exc
    run.source_type = "WORKFLOW_VERSION"
    run.workflow_definition_id = definition.id
    run.workflow_version_id = version.id
    run.input_snapshot = resolved_inputs
    run.model_snapshot = model_snapshot
    run.compiler_version = WORKFLOW_COMPILER_VERSION
    audit(
        db,
        "workflow.run_created",
        run.id,
        {
            "workflow_definition_id": definition.id,
            "workflow_version_id": version.id,
            "version_number": version.version_number,
        },
    )
    db.commit()
    db.refresh(run)
    await schedule_canvas_run(run, run_payload.nodes)
    return canvas_run_response(run)


@router.get("/workflows/{workflow_id}/versions")
def list_workflow_versions(
    workflow_id: str,
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    _workflow_or_404(db, workflow_id)
    records = db.scalars(
        select(WorkflowVersionRecord)
        .where(WorkflowVersionRecord.workflow_definition_id == workflow_id)
        .order_by(WorkflowVersionRecord.version_number.desc())
    ).all()
    return [workflow_version_payload(record) for record in records]


@router.get("/workflows/{workflow_id}/versions/{version_number}")
def get_workflow_version(
    workflow_id: str,
    version_number: int,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return workflow_version_payload(
        _workflow_version_or_404(db, workflow_id, version_number)
    )


def _list_annotations(
    db: Session,
    workflow_id: str,
    version_id: str | None,
) -> list[dict[str, Any]]:
    query = select(WorkflowAnnotationRecord).where(
        WorkflowAnnotationRecord.workflow_definition_id == workflow_id,
        WorkflowAnnotationRecord.deleted_at.is_(None),
    )
    query = query.where(
        WorkflowAnnotationRecord.workflow_version_id == version_id
        if version_id is not None
        else WorkflowAnnotationRecord.workflow_version_id.is_(None)
    )
    records = db.scalars(
        query.order_by(WorkflowAnnotationRecord.created_at)
    ).all()
    return [workflow_annotation_payload(record) for record in records]


@router.get("/workflows/{workflow_id}/annotations")
def list_workflow_annotations(
    workflow_id: str,
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    _workflow_or_404(db, workflow_id)
    return _list_annotations(db, workflow_id, None)


@router.post(
    "/workflows/{workflow_id}/annotations",
    status_code=status.HTTP_201_CREATED,
)
def create_workflow_annotation(
    workflow_id: str,
    payload: WorkflowAnnotationCreateRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    record = create_annotation(db, _workflow_or_404(db, workflow_id), payload)
    return workflow_annotation_payload(record)


@router.get("/workflows/{workflow_id}/versions/{version_number}/annotations")
def list_workflow_version_annotations(
    workflow_id: str,
    version_number: int,
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    version = _workflow_version_or_404(db, workflow_id, version_number)
    return _list_annotations(db, workflow_id, version.id)


@router.post(
    "/workflows/{workflow_id}/versions/{version_number}/annotations",
    status_code=status.HTTP_201_CREATED,
)
def create_workflow_version_annotation(
    workflow_id: str,
    version_number: int,
    payload: WorkflowAnnotationCreateRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    definition = _workflow_or_404(db, workflow_id)
    version = _workflow_version_or_404(db, workflow_id, version_number)
    try:
        record = create_annotation(db, definition, payload, version=version)
    except WorkflowContractError as exc:
        raise _workflow_contract_http_error(exc) from exc
    return workflow_annotation_payload(record)


@router.patch("/workflow-annotations/{annotation_id}")
def patch_workflow_annotation(
    annotation_id: str,
    payload: WorkflowAnnotationUpdateRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    record = db.get(WorkflowAnnotationRecord, annotation_id)
    if not record or record.deleted_at:
        raise HTTPException(404, "Workflow Annotation not found")
    try:
        record = update_annotation(db, record, payload)
    except WorkflowContractError as exc:
        raise _workflow_contract_http_error(exc) from exc
    return workflow_annotation_payload(record)


@router.delete(
    "/workflow-annotations/{annotation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_workflow_annotation(
    annotation_id: str,
    actor_id: str = Query(default="local-user", max_length=128),
    db: Session = Depends(get_db),
) -> Response:
    record = db.get(WorkflowAnnotationRecord, annotation_id)
    if not record or record.deleted_at:
        raise HTTPException(404, "Workflow Annotation not found")
    delete_annotation(db, record, actor_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/workflows/{workflow_id}/archive")
def archive_workflow(
    workflow_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    record = _workflow_or_404(db, workflow_id)
    record.status = "ARCHIVED"
    record.updated_at = utc_now()
    audit(db, "workflow.archived", record.id)
    db.commit()
    db.refresh(record)
    return workflow_definition_payload(record, db)


@router.post("/workflows/{workflow_id}/activate")
def activate_workflow(
    workflow_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    record = _workflow_or_404(db, workflow_id)
    record.status = "ACTIVE"
    record.updated_at = utc_now()
    audit(db, "workflow.activated", record.id)
    db.commit()
    db.refresh(record)
    return workflow_definition_payload(record, db)


@router.get("/workflow-runs")
def list_workflow_runs(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    regular_runs = db.scalars(
        select(RunRecord).order_by(RunRecord.created_at.desc())
    ).unique().all()
    for run in regular_runs:
        rows.append(
            {
                "id": run.id,
                "created_at": run.created_at,
                "run_type": "generation",
                "name": run.name,
                "status": run.status,
                "progress": run.progress,
                "cost_usd": run.actual_cost_usd,
                "estimated_cost_usd": run.estimated_cost_usd,
                "nodes_done": sum(
                    node.status == NodeStatus.SUCCEEDED for node in run.node_runs
                ),
                "nodes_total": len(run.node_runs),
                "attempt_count": sum(node.attempt_count for node in run.node_runs),
                "duration_ms": None,
            }
        )
    canvas_runs = db.scalars(
        select(CanvasRunRecord).order_by(CanvasRunRecord.created_at.desc())
    ).unique().all()
    for run in canvas_runs:
        rows.append(
            {
                "id": run.id,
                "created_at": run.created_at,
                "run_type": (
                    "workflow" if run.source_type == "WORKFLOW_VERSION" else "canvas"
                ),
                "name": run.name,
                "status": run.status,
                "progress": run.progress,
                "cost_usd": sum(node.cost_usd for node in run.node_runs),
                "estimated_cost_usd": None,
                "nodes_done": sum(
                    node.status == NodeStatus.SUCCEEDED for node in run.node_runs
                ),
                "nodes_total": len(run.node_runs),
                "attempt_count": sum(node.attempt_count for node in run.node_runs),
                "duration_ms": sum(node.duration_ms for node in run.node_runs) or None,
                "workflow_definition_id": run.workflow_definition_id,
                "workflow_version_id": run.workflow_version_id,
            }
        )
    return sorted(rows, key=lambda row: row["created_at"], reverse=True)
