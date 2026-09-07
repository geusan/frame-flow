from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ...contexts.generation.application import (
    CreateGenerationBriefCommand,
    GenerationApplication,
)
from ...contexts.generation.domain import GenerationNotFoundError
from ...domain import GenerationBriefRequest
from ..dependencies import get_generation_application


router = APIRouter(tags=["generation"])


@router.post("/generation-briefs", status_code=201)
def create_generation_brief(
    payload: GenerationBriefRequest,
    application: GenerationApplication = Depends(get_generation_application),
) -> dict[str, Any]:
    try:
        return application.create_brief(
            CreateGenerationBriefCommand(payload.model_dump(mode="python"))
        )
    except GenerationNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
