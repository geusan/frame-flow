from __future__ import annotations

import hashlib
import re
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...canvas_documents import (
    canonical_canvas_graph,
    canonicalize_canvas_document,
    legacy_canvas_graph,
    normalize_canvas_document,
)
from ...canvas_packages import (
    PACKAGE_MAX_BYTES,
    PACKAGE_MEDIA_TYPE,
    CanvasPackageError,
    export_canvas_template,
    import_canvas_template,
)
from ...database import CanvasRecord, CanvasRunRecord, get_db
from ...domain import CanvasDocumentRequest, utc_now
from ...service import audit, new_id
from ...workflow_definitions import DEFAULT_DRAFT_CONTRACT


router = APIRouter(tags=["canvases"])


def canvas_document_payload(
    record: CanvasRecord,
    last_run: CanvasRunRecord | None = None,
) -> dict[str, Any]:
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


def _canvas_request_document(payload: CanvasDocumentRequest) -> dict[str, Any]:
    try:
        if payload.document is not None:
            return normalize_canvas_document(payload.document)
        return canonicalize_canvas_document(payload.nodes, payload.edges)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/canvases")
def list_canvases(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    records = db.scalars(select(CanvasRecord).order_by(CanvasRecord.updated_at.desc())).all()
    run_rows = db.scalars(
        select(CanvasRunRecord).order_by(CanvasRunRecord.created_at.desc())
    ).all()
    last_run_by_canvas: dict[str, CanvasRunRecord] = {}
    for run in run_rows:
        last_run_by_canvas.setdefault(run.canvas_id, run)
    return [
        canvas_document_payload(record, last_run_by_canvas.get(record.id))
        for record in records
    ]


@router.post("/canvases", status_code=status.HTTP_201_CREATED)
def create_canvas_document(
    payload: CanvasDocumentRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    document = _canvas_request_document(payload)
    record = CanvasRecord(
        id=new_id("canvas"),
        name=payload.name,
        graph_json=document,
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


@router.post("/canvases/import", status_code=status.HTTP_201_CREATED)
async def import_canvas_document_package(
    file: UploadFile = File(...),
    name: str | None = Form(default=None),
    db: Session = Depends(get_db),
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
    record = CanvasRecord(
        id=new_id("canvas"),
        name=imported_name,
        graph_json=imported.document,
        active_run_id=None,
        revision=1,
        draft_contract_json=imported.draft_contract,
        updated_at=utc_now(),
    )
    db.add(record)
    audit(
        db,
        "canvas.package_imported",
        record.id,
        {
            "filename": file.filename or "canvas.frameflow",
            "package_sha256": hashlib.sha256(content).hexdigest(),
            "source": imported.source,
            "warnings": imported.warnings,
        },
    )
    db.commit()
    db.refresh(record)
    return {
        **canvas_document_payload(record),
        "import_warnings": imported.warnings,
        "package_source": imported.source,
    }


@router.get("/canvases/{canvas_id}")
def get_canvas_document(
    canvas_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    record = db.get(CanvasRecord, canvas_id)
    if not record:
        raise HTTPException(404, "canvas not found")
    last_run = db.scalar(
        select(CanvasRunRecord)
        .where(CanvasRunRecord.canvas_id == canvas_id)
        .order_by(CanvasRunRecord.created_at.desc())
    )
    return canvas_document_payload(record, last_run)


@router.get("/canvases/{canvas_id}/export")
def export_canvas_document_package(
    canvas_id: str,
    db: Session = Depends(get_db),
) -> Response:
    record = db.get(CanvasRecord, canvas_id)
    if not record:
        raise HTTPException(404, "canvas not found")
    try:
        content = export_canvas_template(
            canvas_id=record.id,
            name=record.name,
            revision=record.revision,
            graph_document=record.graph_json or {},
            draft_contract=record.draft_contract_json,
        )
    except CanvasPackageError as exc:
        raise HTTPException(422, str(exc)) from exc
    safe_id = re.sub(r"[^A-Za-z0-9_-]+", "-", record.id).strip("-") or "canvas"
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
    db: Session = Depends(get_db),
) -> dict[str, Any]:
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
        raise HTTPException(
            409,
            f"Canvas revision conflict: expected {payload.expected_revision}, current {record.revision}",
        )
    next_graph = _canvas_request_document(payload)
    next_contract = (
        payload.draft_contract
        if payload.draft_contract is not None
        else (record.draft_contract_json or DEFAULT_DRAFT_CONTRACT)
    )
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
    saved_graph = legacy_canvas_graph(next_graph)
    audit(
        db,
        "canvas.imported" if created else "canvas.saved",
        record.id,
        {
            "node_count": len(saved_graph["nodes"]),
            "edge_count": len(saved_graph["edges"]),
            "write_schema_version": str(
                next_graph.get("schema_version") or "canvas.legacy.v1"
            ),
        },
    )
    db.commit()
    db.refresh(record)
    return canvas_document_payload(record)


@router.delete("/canvases/{canvas_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_canvas_document(
    canvas_id: str,
    db: Session = Depends(get_db),
) -> Response:
    record = db.get(CanvasRecord, canvas_id)
    if not record:
        raise HTTPException(404, "canvas not found")
    if record.workflow_definition_id:
        raise HTTPException(
            409,
            "Workflow Draft Canvas cannot be deleted directly; archive the Workflow instead",
        )
    db.delete(record)
    audit(db, "canvas.deleted", canvas_id)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
