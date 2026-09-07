from __future__ import annotations

from typing import Any, NoReturn

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status

from ...contexts.administration.application import (
    AdministrationApplication,
    FontRegistrationCommand,
    FontUpdateCommand,
)
from ...contexts.administration.domain import (
    AdministrationNotFoundError,
    AdministrationPayloadTooLargeError,
    AdministrationUnsupportedMediaError,
    AdministrationValidationError,
)
from ...domain import FontProfileUpdateRequest
from ...font_registry import FONT_MAX_BYTES
from ..dependencies import get_administration_application


router = APIRouter(tags=["fonts"])


def _raise_font_error(exc: Exception) -> NoReturn:
    if isinstance(exc, AdministrationNotFoundError):
        raise HTTPException(404, str(exc)) from exc
    if isinstance(exc, AdministrationUnsupportedMediaError):
        raise HTTPException(415, str(exc)) from exc
    if isinstance(exc, AdministrationPayloadTooLargeError):
        raise HTTPException(413, str(exc)) from exc
    if isinstance(exc, AdministrationValidationError):
        raise HTTPException(422, str(exc)) from exc
    raise exc


@router.get("/fonts")
def registered_fonts(
    include_retired: bool = Query(default=False),
    application: AdministrationApplication = Depends(get_administration_application),
) -> list[dict[str, Any]]:
    return application.list_fonts(include_retired)


@router.post("/fonts", status_code=status.HTTP_201_CREATED)
async def register_caption_font(
    file: UploadFile = File(...),
    display_name: str | None = Form(default=None, max_length=160),
    license_name: str = Form(default="User provided", max_length=160),
    created_by: str = Form(default="local-user", max_length=128),
    application: AdministrationApplication = Depends(get_administration_application),
) -> dict[str, Any]:
    content = await file.read(FONT_MAX_BYTES + 1)
    try:
        return application.register_font(FontRegistrationCommand(
            filename=file.filename or "font.ttf",
            content_type=(file.content_type or "application/octet-stream").split(";", 1)[0].lower(),
            content=content,
            display_name=display_name,
            license_name=license_name,
            created_by=created_by,
        ))
    except Exception as exc:
        _raise_font_error(exc)


@router.patch("/fonts/{font_id}")
def update_caption_font(
    font_id: str,
    payload: FontProfileUpdateRequest,
    application: AdministrationApplication = Depends(get_administration_application),
) -> dict[str, Any]:
    try:
        return application.update_font(FontUpdateCommand(
            font_id=font_id,
            values=payload.model_dump(exclude_none=True),
        ))
    except Exception as exc:
        _raise_font_error(exc)
