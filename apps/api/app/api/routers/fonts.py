from __future__ import annotations

from typing import Any, NoReturn

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field

from ...contexts.administration.application import (
    AdministrationApplication,
    FontRegistrationCommand,
    FontUpdateCommand,
)
from ...contexts.administration.domain import (
    AdministrationNotFoundError,
    AdministrationPayloadTooLargeError,
    AdministrationUnsupportedMediaError,
    AdministrationUpstreamError,
    AdministrationValidationError,
)
from ...domain import FontProfileUpdateRequest
from ...font_registry import FONT_MAX_BYTES
from ..dependencies import get_administration_application


router = APIRouter(tags=["fonts"])


def _raise_font_error(exc: Exception) -> NoReturn:
    if isinstance(exc, AdministrationUpstreamError):
        raise HTTPException(502, str(exc)) from exc
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


@router.get("/fonts/google")
def google_fonts_catalog(
    q: str = Query(default="", max_length=160),
    korean_only: bool = Query(default=False),
    offset: int = Query(default=0, ge=0, le=10000),
    limit: int = Query(default=12, ge=1, le=48),
    application: AdministrationApplication = Depends(get_administration_application),
) -> dict[str, Any]:
    try:
        return application.search_google_fonts(q.strip(), korean_only, offset, limit)
    except Exception as exc:
        _raise_font_error(exc)


class GoogleFontImportRequest(BaseModel):
    family: str = Field(min_length=1, max_length=160)
    variant: str = Field(default="400", pattern=r"^([1-9][0-9]{0,2}|1000)i?$")


@router.get("/fonts/noonnu")
def noonnu_fonts_catalog(
    q: str = Query(default="", max_length=40),
    page: int = Query(default=1, ge=1, le=1000),
    application: AdministrationApplication = Depends(get_administration_application),
) -> dict[str, Any]:
    try:
        return application.search_noonnu_fonts(q.strip(), page)
    except Exception as exc:
        _raise_font_error(exc)


@router.get("/fonts/noonnu/{font_id}")
def noonnu_font_detail(font_id: int, application: AdministrationApplication = Depends(get_administration_application)) -> dict[str, Any]:
    if font_id < 1:
        raise HTTPException(422, "유효한 눈누 폰트 ID가 필요합니다.")
    try:
        return application.get_noonnu_font(font_id)
    except Exception as exc:
        _raise_font_error(exc)


class NoonnuFontImportRequest(BaseModel):
    font_id: int = Field(ge=1)
    variant: str = Field(default="400", pattern=r"^([1-9][0-9]{0,2}|1000)i?(-[a-z0-9_-]{1,64})?$")


@router.post("/fonts/noonnu/import", status_code=status.HTTP_201_CREATED)
def import_noonnu_caption_font(
    payload: NoonnuFontImportRequest,
    application: AdministrationApplication = Depends(get_administration_application),
) -> dict[str, Any]:
    try:
        return application.import_noonnu_font(payload.font_id, payload.variant)
    except Exception as exc:
        _raise_font_error(exc)


@router.post("/fonts/google/import", status_code=status.HTTP_201_CREATED)
def import_google_caption_font(
    payload: GoogleFontImportRequest,
    application: AdministrationApplication = Depends(get_administration_application),
) -> dict[str, Any]:
    try:
        return application.import_google_font(payload.family, payload.variant)
    except Exception as exc:
        _raise_font_error(exc)


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
