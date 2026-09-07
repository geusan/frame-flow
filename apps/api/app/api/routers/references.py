from __future__ import annotations

from typing import Any, NoReturn

from fastapi import APIRouter, Depends, HTTPException, status

from ...contexts.references.application import (
    CreateReferenceSetCommand,
    ImportReferenceCommand,
    InspectReferencesCommand,
    ReferenceApplication,
)
from ...contexts.references.domain import ReferenceNotFoundError, ReferenceValidationError
from ...domain import (
    ReferenceImportRequest,
    ReferenceInspectRequest,
    ReferenceMetadata,
    ReferenceSetRequest,
)
from ..dependencies import get_reference_application


router = APIRouter(tags=["references"])


def _raise_reference_http_error(exc: Exception) -> NoReturn:
    if isinstance(exc, ReferenceNotFoundError):
        raise HTTPException(404, str(exc)) from exc
    if isinstance(exc, ReferenceValidationError):
        raise HTTPException(422, str(exc)) from exc
    raise exc


@router.post("/references/inspect", response_model=list[ReferenceMetadata])
def inspect_references(
    payload: ReferenceInspectRequest,
    application: ReferenceApplication = Depends(get_reference_application),
) -> list[ReferenceMetadata]:
    try:
        return application.inspect(
            InspectReferencesCommand(urls=[str(url) for url in payload.urls])
        )
    except ReferenceValidationError as exc:
        _raise_reference_http_error(exc)


@router.post("/references/import", status_code=status.HTTP_201_CREATED)
def import_reference(
    payload: ReferenceImportRequest,
    application: ReferenceApplication = Depends(get_reference_application),
) -> dict[str, Any]:
    try:
        return application.import_reference(
            ImportReferenceCommand(payload.model_dump(mode="python"))
        )
    except ReferenceValidationError as exc:
        _raise_reference_http_error(exc)


@router.get("/references")
def list_references(
    application: ReferenceApplication = Depends(get_reference_application),
) -> list[dict[str, Any]]:
    return application.list_references()


@router.post("/reference-sets", status_code=201)
def create_reference_set(
    payload: ReferenceSetRequest,
    application: ReferenceApplication = Depends(get_reference_application),
) -> dict[str, Any]:
    try:
        return application.create_set(
            CreateReferenceSetCommand(
                name=payload.name,
                reference_ids=payload.reference_ids,
            )
        )
    except ReferenceNotFoundError as exc:
        _raise_reference_http_error(exc)
