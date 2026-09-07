from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session

from ...database import FontRecord, get_db
from ...domain import FontProfileUpdateRequest
from ...font_registry import (
    FONT_MAX_BYTES,
    inspect_font,
    list_fonts,
    register_font,
    update_font_profile,
)


router = APIRouter(tags=["fonts"])


@router.get("/fonts")
def registered_fonts(
    include_retired: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    return list_fonts(db, include_retired=include_retired)


@router.post("/fonts", status_code=status.HTTP_201_CREATED)
async def register_caption_font(
    file: UploadFile = File(...),
    display_name: str | None = Form(default=None, max_length=160),
    license_name: str = Form(default="User provided", max_length=160),
    created_by: str = Form(default="local-user", max_length=128),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    filename = file.filename or "font.ttf"
    if not filename.lower().endswith((".ttf", ".otf")):
        raise HTTPException(
            415,
            "only individual TTF and OTF font faces can be registered",
        )
    content = await file.read(FONT_MAX_BYTES + 1)
    if not content:
        raise HTTPException(422, "font file is empty")
    if len(content) > FONT_MAX_BYTES:
        raise HTTPException(413, "font file exceeds the 24 MB limit")
    content_type = (file.content_type or "application/octet-stream").split(";", 1)[0].lower()
    try:
        inspect_font(content)
        payload, created = register_font(
            db,
            content=content,
            filename=filename,
            content_type=content_type,
            display_name=display_name,
            license_name=license_name,
            created_by=created_by,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    db.commit()
    return {**payload, "created": created}


@router.patch("/fonts/{font_id}")
def update_caption_font(
    font_id: str,
    payload: FontProfileUpdateRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    font = db.get(FontRecord, font_id)
    if not font:
        raise HTTPException(404, "font is not registered")
    try:
        result = update_font_profile(
            db,
            font,
            **payload.model_dump(exclude_none=True),
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    db.commit()
    return result
