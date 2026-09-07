from __future__ import annotations

from typing import Any, NoReturn

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status

from ...contexts.administration.application import AdministrationApplication, SkillRegistrationCommand
from ...contexts.administration.domain import AdministrationNotFoundError, AdministrationPayloadTooLargeError, AdministrationValidationError
from ...project_skills import SKILL_MAX_BYTES
from ..dependencies import get_administration_application


router = APIRouter(tags=["skills"])


def _raise_skill_error(exc: Exception) -> NoReturn:
    if isinstance(exc, AdministrationNotFoundError):
        raise HTTPException(404, str(exc)) from exc
    if isinstance(exc, AdministrationPayloadTooLargeError):
        raise HTTPException(413, str(exc)) from exc
    if isinstance(exc, AdministrationValidationError):
        raise HTTPException(422, str(exc)) from exc
    raise exc


@router.get("/skills")
def project_skills(
    include_disabled: bool = Query(default=False),
    application: AdministrationApplication = Depends(get_administration_application),
) -> list[dict[str, Any]]:
    return application.list_skills(include_disabled)


async def _register_uploaded_project_skill(
    file: UploadFile,
    application: AdministrationApplication,
    *,
    expected_id: str | None = None,
    created_by: str = "local-user",
) -> dict[str, Any]:
    content = await file.read(SKILL_MAX_BYTES + 1)
    try:
        return application.register_skill(SkillRegistrationCommand(
            filename=file.filename or "SKILL.md",
            content=content,
            created_by=created_by,
            expected_id=expected_id,
        ))
    except Exception as exc:
        _raise_skill_error(exc)


@router.post("/skills", status_code=status.HTTP_201_CREATED)
async def register_project_skill_file(
    file: UploadFile = File(...),
    created_by: str = Form(default="local-user", max_length=128),
    application: AdministrationApplication = Depends(get_administration_application),
) -> dict[str, Any]:
    return await _register_uploaded_project_skill(file, application, created_by=created_by)


@router.post("/skills/{skill_id}/versions", status_code=status.HTTP_201_CREATED)
async def register_project_skill_version(
    skill_id: str,
    file: UploadFile = File(...),
    created_by: str = Form(default="local-user", max_length=128),
    application: AdministrationApplication = Depends(get_administration_application),
) -> dict[str, Any]:
    return await _register_uploaded_project_skill(file, application, expected_id=skill_id, created_by=created_by)


@router.get("/skills/{skill_id}/versions")
def project_skill_versions(
    skill_id: str,
    application: AdministrationApplication = Depends(get_administration_application),
) -> list[dict[str, Any]]:
    try:
        return application.list_skill_versions(skill_id)
    except Exception as exc:
        _raise_skill_error(exc)


@router.post("/skills/{skill_id}/versions/{version_number}/activate")
def activate_project_skill(
    skill_id: str,
    version_number: int,
    application: AdministrationApplication = Depends(get_administration_application),
) -> dict[str, Any]:
    try:
        return application.activate_skill_version(skill_id, version_number)
    except Exception as exc:
        _raise_skill_error(exc)


@router.put("/skills/{skill_id}/installation")
def update_project_skill_installation(
    skill_id: str,
    enabled: bool,
    application: AdministrationApplication = Depends(get_administration_application),
) -> dict[str, Any]:
    try:
        return application.set_skill_enabled(skill_id, enabled)
    except Exception as exc:
        _raise_skill_error(exc)
