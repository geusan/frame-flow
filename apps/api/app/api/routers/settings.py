from __future__ import annotations

from typing import Any, NoReturn

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

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


class StorageProfileRequest(BaseModel):
    values: dict[str, Any]
    base_profile_id: str | None = None


class StorageMigrationRequest(BaseModel):
    target_profile_id: str
    artifact_ids: list[str] = Field(min_length=1, max_length=10)


def _storage(application: AdministrationApplication, action: str, values: dict[str, Any]) -> dict[str, Any]:
    try:
        return application.storage_operation(action, values)
    except Exception as exc:
        _raise_settings_error(exc)


@router.get("/settings/storage")
def list_storage(application: AdministrationApplication = Depends(get_administration_application)) -> dict[str, Any]:
    return _storage(application, "list", {})


@router.post("/settings/storage/profiles", status_code=201)
def save_storage(payload: StorageProfileRequest, application: AdministrationApplication = Depends(get_administration_application)) -> dict[str, Any]:
    return _storage(application, "save", payload.model_dump())


@router.post("/settings/storage/profiles/{profile_id}/test")
def test_storage(profile_id: str, application: AdministrationApplication = Depends(get_administration_application)) -> dict[str, Any]:
    return _storage(application, "test", {"profile_id": profile_id})


@router.post("/settings/storage/profiles/{profile_id}/activate")
def activate_storage(profile_id: str, application: AdministrationApplication = Depends(get_administration_application)) -> dict[str, Any]:
    return _storage(application, "activate", {"profile_id": profile_id})


@router.get("/settings/storage/profiles/{profile_id}/migration-plan")
def plan_storage_migration(profile_id: str, application: AdministrationApplication = Depends(get_administration_application)) -> dict[str, Any]:
    return _storage(application, "plan", {"target_profile_id": profile_id})


@router.post("/settings/storage/migrate")
def migrate_storage(payload: StorageMigrationRequest, application: AdministrationApplication = Depends(get_administration_application)) -> dict[str, Any]:
    return _storage(application, "migrate", payload.model_dump())


@router.put("/settings/storage/profiles/{profile_id}/credentials")
def rotate_storage_credentials(profile_id: str, payload: StorageProfileRequest, application: AdministrationApplication = Depends(get_administration_application)) -> dict[str, Any]:
    return _storage(application, "rotate", {"profile_id":profile_id,"values":payload.values})
