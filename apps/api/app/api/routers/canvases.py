from __future__ import annotations

import hashlib
import re
from copy import deepcopy
from typing import Any, NoReturn

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status

from ...canvas_packages import (
    PACKAGE_MAX_BYTES,
    PACKAGE_MEDIA_TYPE,
    CanvasPackageError,
    export_canvas_template,
    import_canvas_template,
)
from ...canvas_documents import legacy_canvas_graph
from ...contexts.canvases.application import (
    CanvasApplication,
    CanvasDetails,
    CreateCanvasCommand,
    ImportCanvasCommand,
    SaveCanvasCommand,
)
from ...contexts.canvases.domain import (
    CanvasDeleteConflictError,
    CanvasNotFoundError,
    CanvasRevisionConflictError,
    CanvasValidationError,
)
from ...domain import CanvasDocumentRequest
from ...workflow_definitions import DEFAULT_DRAFT_CONTRACT
from ..dependencies import get_canvas_application


router = APIRouter(tags=["canvases"])


def canvas_document_payload(details: CanvasDetails) -> dict[str, Any]:
    canvas = details.canvas
    graph = canvas.graph_document
    legacy_graph = legacy_canvas_graph(graph)
    last_run = details.last_run
    return {
        "id": canvas.id,
        "created_at": canvas.created_at,
        "updated_at": canvas.updated_at,
        "name": canvas.name,
        "nodes": legacy_graph["nodes"],
        "edges": legacy_graph["edges"],
        "node_count": len(legacy_graph["nodes"]),
        "edge_count": len(legacy_graph["edges"]),
        "active_run_id": canvas.active_run_id,
        "workflow_definition_id": canvas.workflow_definition_id,
        "base_version_id": canvas.base_version_id,
        "revision": canvas.revision,
        "draft_contract": canvas.draft_contract or DEFAULT_DRAFT_CONTRACT,
        "storage_schema_version": str(
            graph.get("schema_version") or "canvas.legacy.v1"
        ),
        "last_run": (
            {
                "id": last_run.id,
                "status": last_run.status,
                "progress": last_run.progress,
                "created_at": last_run.created_at,
            }
            if last_run
            else None
        ),
    }


def _raise_canvas_http_error(exc: Exception) -> NoReturn:
    if isinstance(exc, CanvasNotFoundError):
        raise HTTPException(404, str(exc)) from exc
    if isinstance(exc, (CanvasRevisionConflictError, CanvasDeleteConflictError)):
        raise HTTPException(409, str(exc)) from exc
    if isinstance(exc, CanvasValidationError):
        raise HTTPException(422, str(exc)) from exc
    raise exc


@router.get("/canvases")
def list_canvases(
    application: CanvasApplication = Depends(get_canvas_application),
) -> list[dict[str, Any]]:
    return [
        canvas_document_payload(details)
        for details in application.list_canvases()
    ]


@router.post("/canvases", status_code=status.HTTP_201_CREATED)
def create_canvas_document(
    payload: CanvasDocumentRequest,
    application: CanvasApplication = Depends(get_canvas_application),
) -> dict[str, Any]:
    try:
        details = application.create_canvas(
            CreateCanvasCommand(
                name=payload.name,
                document=payload.document,
                nodes=payload.nodes,
                edges=payload.edges,
                active_run_id=payload.active_run_id,
                draft_contract=deepcopy(
                    payload.draft_contract or DEFAULT_DRAFT_CONTRACT
                ),
            )
        )
    except CanvasValidationError as exc:
        _raise_canvas_http_error(exc)
    return canvas_document_payload(details)


@router.post("/canvases/import", status_code=status.HTTP_201_CREATED)
async def import_canvas_document_package(
    file: UploadFile = File(...),
    name: str | None = Form(default=None),
    application: CanvasApplication = Depends(get_canvas_application),
) -> dict[str, Any]:
    content = await file.read(PACKAGE_MAX_BYTES + 1)
    if len(content) > PACKAGE_MAX_BYTES:
        raise HTTPException(413, "Canvas package exceeds the 20 MB template limit")
    try:
        imported = import_canvas_template(content)
    except CanvasPackageError as exc:
        raise HTTPException(422, str(exc)) from exc
    imported_name = (name.strip() if name is not None else imported.name) or imported.name
    if len(imported_name) > 255:
        raise HTTPException(422, "Canvas name is too long")
    details = application.import_canvas(
        ImportCanvasCommand(
            name=imported_name,
            graph_document=imported.document,
            draft_contract=imported.draft_contract,
            filename=file.filename or "canvas.frameflow",
            package_sha256=hashlib.sha256(content).hexdigest(),
            package_source=imported.source,
            warnings=imported.warnings,
        )
    )
    return {
        **canvas_document_payload(details),
        "import_warnings": imported.warnings,
        "package_source": imported.source,
    }


@router.get("/canvases/{canvas_id}")
def get_canvas_document(
    canvas_id: str,
    application: CanvasApplication = Depends(get_canvas_application),
) -> dict[str, Any]:
    try:
        details = application.get_canvas(canvas_id)
    except CanvasNotFoundError as exc:
        _raise_canvas_http_error(exc)
    return canvas_document_payload(details)


@router.get("/canvases/{canvas_id}/export")
def export_canvas_document_package(
    canvas_id: str,
    application: CanvasApplication = Depends(get_canvas_application),
) -> Response:
    try:
        canvas = application.get_canvas(canvas_id).canvas
    except CanvasNotFoundError as exc:
        _raise_canvas_http_error(exc)
    try:
        content = export_canvas_template(
            canvas_id=canvas.id,
            name=canvas.name,
            revision=canvas.revision,
            graph_document=canvas.graph_document,
            draft_contract=canvas.draft_contract,
        )
    except CanvasPackageError as exc:
        raise HTTPException(422, str(exc)) from exc
    safe_id = re.sub(r"[^A-Za-z0-9_-]+", "-", canvas.id).strip("-") or "canvas"
    return Response(
        content=content,
        media_type=PACKAGE_MEDIA_TYPE,
        headers={
            "Content-Disposition": f'attachment; filename="{safe_id}.frameflow"',
            "Content-Length": str(len(content)),
        },
    )


@router.put("/canvases/{canvas_id}")
def save_canvas_document(
    canvas_id: str,
    payload: CanvasDocumentRequest,
    application: CanvasApplication = Depends(get_canvas_application),
) -> dict[str, Any]:
    try:
        details = application.save_canvas(
            SaveCanvasCommand(
                canvas_id=canvas_id,
                name=payload.name,
                document=payload.document,
                nodes=payload.nodes,
                edges=payload.edges,
                active_run_id=payload.active_run_id,
                expected_revision=payload.expected_revision,
                draft_contract=payload.draft_contract,
                default_draft_contract=deepcopy(DEFAULT_DRAFT_CONTRACT),
            )
        )
    except (
        CanvasRevisionConflictError,
        CanvasValidationError,
    ) as exc:
        _raise_canvas_http_error(exc)
    return canvas_document_payload(details)


@router.delete("/canvases/{canvas_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_canvas_document(
    canvas_id: str,
    application: CanvasApplication = Depends(get_canvas_application),
) -> Response:
    try:
        application.delete_canvas(canvas_id)
    except (CanvasNotFoundError, CanvasDeleteConflictError) as exc:
        _raise_canvas_http_error(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
