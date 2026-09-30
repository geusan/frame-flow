from __future__ import annotations

from typing import Any, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from ...contexts.workflows.application import (
    CreateAnnotationCommand,
    CreateWorkflowCommand,
    PublishWorkflowCommand,
    RestoreWorkflowDraftCommand,
    StartWorkflowRunCommand,
    UpdateAnnotationCommand,
    UpdateWorkflowCommand,
    WorkflowApplication,
)
from ...contexts.workflows.domain import (
    WorkflowConflictError,
    WorkflowNotFoundError,
    WorkflowValidationError,
)
from ...domain import (
    CanvasRunResponse,
    WorkflowAnnotationCreateRequest,
    WorkflowAnnotationUpdateRequest,
    WorkflowCreateRequest,
    WorkflowPublishRequest,
    WorkflowRestoreDraftRequest,
    WorkflowUpdateRequest,
    WorkflowVersionRunRequest,
)
from ..dependencies import get_workflow_application


router = APIRouter(tags=["workflows"])


def _raise_workflow_http_error(exc: Exception) -> NoReturn:
    if isinstance(exc, WorkflowNotFoundError):
        raise HTTPException(404, str(exc)) from exc
    if isinstance(exc, WorkflowConflictError):
        raise HTTPException(409, str(exc)) from exc
    if isinstance(exc, WorkflowValidationError):
        raise HTTPException(422, str(exc)) from exc
    raise exc


@router.post("/workflows", status_code=status.HTTP_201_CREATED)
def create_workflow(
    payload: WorkflowCreateRequest,
    application: WorkflowApplication = Depends(get_workflow_application),
) -> dict[str, Any]:
    try:
        return application.create(
            CreateWorkflowCommand(
                name=payload.name,
                description=payload.description,
                tags=payload.tags,
                source_canvas_id=payload.source_canvas_id,
            )
        )
    except (
        WorkflowConflictError,
        WorkflowNotFoundError,
        WorkflowValidationError,
    ) as exc:
        _raise_workflow_http_error(exc)


@router.get("/workflows")
def list_workflows(
    status_filter: str | None = Query(default=None, alias="status"),
    application: WorkflowApplication = Depends(get_workflow_application),
) -> list[dict[str, Any]]:
    return application.list(status_filter)


@router.get("/workflows/{workflow_id}")
def get_workflow(
    workflow_id: str,
    application: WorkflowApplication = Depends(get_workflow_application),
) -> dict[str, Any]:
    try:
        return application.get(workflow_id)
    except WorkflowNotFoundError as exc:
        _raise_workflow_http_error(exc)


@router.patch("/workflows/{workflow_id}")
def update_workflow(
    workflow_id: str,
    payload: WorkflowUpdateRequest,
    application: WorkflowApplication = Depends(get_workflow_application),
) -> dict[str, Any]:
    try:
        return application.update(
            UpdateWorkflowCommand(
                workflow_id=workflow_id,
                values=payload.model_dump(exclude_unset=True),
            )
        )
    except WorkflowNotFoundError as exc:
        _raise_workflow_http_error(exc)


@router.post("/workflows/{workflow_id}/publish", status_code=status.HTTP_201_CREATED)
def publish_workflow(
    workflow_id: str,
    payload: WorkflowPublishRequest,
    application: WorkflowApplication = Depends(get_workflow_application),
) -> dict[str, Any]:
    try:
        return application.publish(
            PublishWorkflowCommand(
                workflow_id=workflow_id,
                expected_canvas_revision=payload.expected_canvas_revision,
                release_notes=payload.release_notes,
                published_by=payload.published_by,
            )
        )
    except (
        WorkflowConflictError,
        WorkflowNotFoundError,
        WorkflowValidationError,
    ) as exc:
        _raise_workflow_http_error(exc)


@router.post(
    "/workflows/{workflow_id}/runs",
    response_model=CanvasRunResponse,
    status_code=status.HTTP_201_CREATED,
)
async def start_workflow_version_run(
    workflow_id: str,
    payload: WorkflowVersionRunRequest,
    application: WorkflowApplication = Depends(get_workflow_application),
) -> CanvasRunResponse:
    try:
        return await application.start_run(
            StartWorkflowRunCommand(
                workflow_id=workflow_id,
                version=payload.version,
                inputs=payload.inputs,
            )
        )
    except (
        WorkflowConflictError,
        WorkflowNotFoundError,
        WorkflowValidationError,
    ) as exc:
        _raise_workflow_http_error(exc)


@router.get("/workflows/{workflow_id}/versions")
def list_workflow_versions(
    workflow_id: str,
    application: WorkflowApplication = Depends(get_workflow_application),
) -> list[dict[str, Any]]:
    try:
        return application.list_versions(workflow_id)
    except WorkflowNotFoundError as exc:
        _raise_workflow_http_error(exc)


@router.get("/workflows/{workflow_id}/versions/{version_number}")
def get_workflow_version(
    workflow_id: str,
    version_number: int,
    application: WorkflowApplication = Depends(get_workflow_application),
) -> dict[str, Any]:
    try:
        return application.get_version(workflow_id, version_number)
    except WorkflowNotFoundError as exc:
        _raise_workflow_http_error(exc)


@router.get("/workflows/{workflow_id}/annotations")
def list_workflow_annotations(
    workflow_id: str,
    application: WorkflowApplication = Depends(get_workflow_application),
) -> list[dict[str, Any]]:
    try:
        return application.list_annotations(workflow_id)
    except WorkflowNotFoundError as exc:
        _raise_workflow_http_error(exc)


@router.post(
    "/workflows/{workflow_id}/annotations",
    status_code=status.HTTP_201_CREATED,
)
def create_workflow_annotation(
    workflow_id: str,
    payload: WorkflowAnnotationCreateRequest,
    application: WorkflowApplication = Depends(get_workflow_application),
) -> dict[str, Any]:
    try:
        return application.create_annotation(
            CreateAnnotationCommand(
                workflow_id=workflow_id,
                version_number=None,
                values=payload.model_dump(mode="python"),
            )
        )
    except (
        WorkflowConflictError,
        WorkflowNotFoundError,
        WorkflowValidationError,
    ) as exc:
        _raise_workflow_http_error(exc)


@router.get("/workflows/{workflow_id}/versions/{version_number}/annotations")
def list_workflow_version_annotations(
    workflow_id: str,
    version_number: int,
    application: WorkflowApplication = Depends(get_workflow_application),
) -> list[dict[str, Any]]:
    try:
        return application.list_annotations(workflow_id, version_number)
    except WorkflowNotFoundError as exc:
        _raise_workflow_http_error(exc)


@router.post(
    "/workflows/{workflow_id}/versions/{version_number}/annotations",
    status_code=status.HTTP_201_CREATED,
)
def create_workflow_version_annotation(
    workflow_id: str,
    version_number: int,
    payload: WorkflowAnnotationCreateRequest,
    application: WorkflowApplication = Depends(get_workflow_application),
) -> dict[str, Any]:
    try:
        return application.create_annotation(
            CreateAnnotationCommand(
                workflow_id=workflow_id,
                version_number=version_number,
                values=payload.model_dump(mode="python"),
            )
        )
    except (
        WorkflowConflictError,
        WorkflowNotFoundError,
        WorkflowValidationError,
    ) as exc:
        _raise_workflow_http_error(exc)


@router.patch("/workflow-annotations/{annotation_id}")
def patch_workflow_annotation(
    annotation_id: str,
    payload: WorkflowAnnotationUpdateRequest,
    application: WorkflowApplication = Depends(get_workflow_application),
) -> dict[str, Any]:
    try:
        return application.update_annotation(
            UpdateAnnotationCommand(
                annotation_id=annotation_id,
                values=payload.model_dump(exclude_unset=True),
            )
        )
    except (
        WorkflowConflictError,
        WorkflowNotFoundError,
        WorkflowValidationError,
    ) as exc:
        _raise_workflow_http_error(exc)


@router.delete(
    "/workflow-annotations/{annotation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_workflow_annotation(
    annotation_id: str,
    actor_id: str = Query(default="local-user", max_length=128),
    application: WorkflowApplication = Depends(get_workflow_application),
) -> Response:
    try:
        application.delete_annotation(annotation_id, actor_id)
    except WorkflowNotFoundError as exc:
        _raise_workflow_http_error(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/workflows/{workflow_id}/archive")
def archive_workflow(
    workflow_id: str,
    application: WorkflowApplication = Depends(get_workflow_application),
) -> dict[str, Any]:
    try:
        return application.archive(workflow_id)
    except WorkflowNotFoundError as exc:
        _raise_workflow_http_error(exc)


@router.post("/workflows/{workflow_id}/activate")
def activate_workflow(
    workflow_id: str,
    application: WorkflowApplication = Depends(get_workflow_application),
) -> dict[str, Any]:
    try:
        return application.activate(workflow_id)
    except WorkflowNotFoundError as exc:
        _raise_workflow_http_error(exc)


@router.get("/workflow-runs")
def list_workflow_runs(
    application: WorkflowApplication = Depends(get_workflow_application),
) -> list[dict[str, Any]]:
    return application.list_runs()


@router.post("/workflows/{workflow_id}/versions/{version_number}/restore-draft", status_code=status.HTTP_201_CREATED)
def restore_workflow_draft(workflow_id: str, version_number: int, payload: WorkflowRestoreDraftRequest, application: WorkflowApplication = Depends(get_workflow_application)) -> dict[str, Any]:
    try:
        return application.restore_draft(RestoreWorkflowDraftCommand(workflow_id, version_number, payload.expected_canvas_id, payload.expected_canvas_revision))
    except (WorkflowConflictError, WorkflowNotFoundError, WorkflowValidationError) as exc:
        _raise_workflow_http_error(exc)
