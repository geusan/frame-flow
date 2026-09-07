from __future__ import annotations

from typing import Any, NoReturn

from fastapi import APIRouter, Depends, HTTPException

from ...contexts.formats.application import (
    CreateExtractionRecipeCommand,
    CreateFormatRunCommand,
    CreateVariantsCommand,
    FormatApplication,
    MergeFormatsCommand,
)
from ...contexts.formats.domain import FormatNotFoundError, FormatValidationError
from ...domain import ExtractionRecipeRequest, FormatRunRequest, MergeRequest, VariationRequest
from ..dependencies import get_format_application


router = APIRouter(tags=["formats"])


def _raise_format_http_error(exc: Exception) -> NoReturn:
    if isinstance(exc, FormatNotFoundError):
        raise HTTPException(404, str(exc)) from exc
    if isinstance(exc, FormatValidationError):
        raise HTTPException(422, str(exc)) from exc
    raise exc


@router.post("/extraction-recipes", status_code=201)
def create_extraction_recipe(
    payload: ExtractionRecipeRequest,
    application: FormatApplication = Depends(get_format_application),
) -> dict[str, Any]:
    return application.create_recipe(
        CreateExtractionRecipeCommand(payload.model_dump(mode="python"))
    )


@router.post("/format-runs", status_code=201)
def create_format_run(
    payload: FormatRunRequest,
    application: FormatApplication = Depends(get_format_application),
) -> dict[str, Any]:
    try:
        return application.create_run(
            CreateFormatRunCommand(payload.model_dump(mode="python"))
        )
    except (FormatNotFoundError, FormatValidationError) as exc:
        _raise_format_http_error(exc)


@router.get("/formats/{format_id}")
def get_format(
    format_id: str,
    application: FormatApplication = Depends(get_format_application),
) -> dict[str, Any]:
    try:
        return application.get(format_id)
    except FormatNotFoundError as exc:
        _raise_format_http_error(exc)


@router.get("/formats")
def list_formats(
    application: FormatApplication = Depends(get_format_application),
) -> list[dict[str, Any]]:
    return application.list()


@router.post("/formats/{format_id}/variants", status_code=201)
def create_variants(
    format_id: str,
    payload: VariationRequest,
    application: FormatApplication = Depends(get_format_application),
) -> list[dict[str, Any]]:
    try:
        return application.create_variants(
            CreateVariantsCommand(
                format_id=format_id,
                values=payload.model_dump(mode="python"),
            )
        )
    except FormatNotFoundError as exc:
        _raise_format_http_error(exc)


@router.post("/formats/merge", status_code=201)
def merge_formats(
    payload: MergeRequest,
    application: FormatApplication = Depends(get_format_application),
) -> dict[str, Any]:
    try:
        return application.merge(
            MergeFormatsCommand(payload.model_dump(mode="python"))
        )
    except FormatNotFoundError as exc:
        _raise_format_http_error(exc)
