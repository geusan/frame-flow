from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session

from ...database import get_db
from ...project_skills import (
    SKILL_MAX_BYTES,
    activate_project_skill_version,
    list_project_skill_versions,
    list_project_skills,
    parse_project_skill_content,
    register_project_skill,
    set_project_skill_enabled,
)
from ...service import audit


router = APIRouter(tags=["skills"])


@router.get("/skills")
def project_skills(
    include_disabled: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    return [
        skill.public_payload()
        for skill in list_project_skills(db, include_disabled=include_disabled)
    ]


async def _register_uploaded_project_skill(
    file: UploadFile,
    db: Session,
    *,
    expected_id: str | None = None,
    created_by: str = "local-user",
) -> tuple[dict[str, Any], bool]:
    content = await file.read(SKILL_MAX_BYTES + 1)
    if len(content) > SKILL_MAX_BYTES:
        raise HTTPException(413, "Project Skill exceeds the 256 KB limit")
    try:
        text = content.decode("utf-8")
        parsed = parse_project_skill_content(
            text,
            expected_id=expected_id,
            source="upload",
        )
        stored, created = register_project_skill(db, parsed, created_by=created_by)
    except (UnicodeDecodeError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc
    audit(
        db,
        "skill.version_registered",
        stored.version_id or stored.id,
        {
            "skill_id": stored.id,
            "version": stored.version,
            "version_number": stored.version_number,
            "filename": file.filename or "SKILL.md",
            "created": created,
        },
    )
    db.commit()
    return stored.public_payload(), created


@router.post("/skills", status_code=status.HTTP_201_CREATED)
async def register_project_skill_file(
    file: UploadFile = File(...),
    created_by: str = Form(default="local-user", max_length=128),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    payload, created = await _register_uploaded_project_skill(
        file,
        db,
        created_by=created_by,
    )
    return {**payload, "created": created}


@router.post("/skills/{skill_id}/versions", status_code=status.HTTP_201_CREATED)
async def register_project_skill_version(
    skill_id: str,
    file: UploadFile = File(...),
    created_by: str = Form(default="local-user", max_length=128),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    payload, created = await _register_uploaded_project_skill(
        file,
        db,
        expected_id=skill_id,
        created_by=created_by,
    )
    return {**payload, "created": created}


@router.get("/skills/{skill_id}/versions")
def project_skill_versions(
    skill_id: str,
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    try:
        return [
            skill.public_payload()
            for skill in list_project_skill_versions(db, skill_id)
        ]
    except ValueError as exc:
        raise HTTPException(
            404 if "not registered" in str(exc) else 422,
            str(exc),
        ) from exc


@router.post("/skills/{skill_id}/versions/{version_number}/activate")
def activate_project_skill(
    skill_id: str,
    version_number: int,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        skill = activate_project_skill_version(db, skill_id, version_number)
    except ValueError as exc:
        raise HTTPException(
            404 if "not registered" in str(exc) else 422,
            str(exc),
        ) from exc
    audit(
        db,
        "skill.version_activated",
        skill.version_id or skill.id,
        {
            "skill_id": skill.id,
            "version": skill.version,
            "version_number": skill.version_number,
        },
    )
    db.commit()
    return skill.public_payload()


@router.put("/skills/{skill_id}/installation")
def update_project_skill_installation(
    skill_id: str,
    enabled: bool,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        skill = set_project_skill_enabled(db, skill_id, enabled)
    except ValueError as exc:
        raise HTTPException(
            404 if "not registered" in str(exc) else 422,
            str(exc),
        ) from exc
    audit(
        db,
        "skill.installation_updated",
        skill.definition_id or skill.id,
        {"skill_id": skill.id, "enabled": enabled},
    )
    db.commit()
    return skill.public_payload()
