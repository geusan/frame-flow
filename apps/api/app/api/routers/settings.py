from __future__ import annotations

from typing import Any, NoReturn

from fastapi import APIRouter, Depends, HTTPException

from ...contexts.administration.application import AdministrationApplication, ProviderSettingsCommand
from ...contexts.administration.domain import AdministrationNotFoundError, AdministrationValidationError
from ...domain import ProviderSettingsUpdateRequest
from ..dependencies import get_administration_application


router = APIRouter(tags=["settings"])


def _raise_settings_error(exc: Exception) -> NoReturn:
    if isinstance(exc, AdministrationNotFoundError):
        raise HTTPException(404, str(exc)) from exc
    if isinstance(exc, AdministrationValidationError):
        raise HTTPException(422, str(exc)) from exc
    raise exc


@router.get("/settings/providers")
def list_provider_settings(
    application: AdministrationApplication = Depends(get_administration_application),
) -> list[dict[str, Any]]:
    return application.list_provider_settings()


@router.put("/settings/providers/{provider}")
def save_provider_settings(
    provider: str,
    payload: ProviderSettingsUpdateRequest,
    application: AdministrationApplication = Depends(get_administration_application),
) -> dict[str, Any]:
    try:
        return application.update_provider_settings(ProviderSettingsCommand(
            provider=provider,
            enabled=payload.enabled,
            auth_method=payload.auth_method,
            values=payload.values,
            clear_fields=payload.clear_fields,
        ))
    except Exception as exc:
        _raise_settings_error(exc)


@router.get("/models")
def list_models(
    application: AdministrationApplication = Depends(get_administration_application),
) -> list[dict[str, Any]]:
    return application.list_models()
