from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ...database import FormatRecord, GenerationBriefRecord, get_db
from ...domain import GenerationBriefRequest
from ...service import new_id


router = APIRouter(tags=["generation"])


@router.post("/generation-briefs", status_code=201)
def create_generation_brief(
    payload: GenerationBriefRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    if not db.get(FormatRecord, payload.format_id):
        raise HTTPException(404, "format not found")
    record = GenerationBriefRecord(
        id=new_id("brief"),
        topic=payload.topic,
        format_id=payload.format_id,
        payload=payload.model_dump(mode="json"),
    )
    db.add(record)
    db.commit()
    return {"id": record.id, **record.payload}
