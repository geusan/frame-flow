from __future__ import annotations

from typing import Any, Callable

from sqlalchemy.orm import Session

from ...contexts.generation.application import CreateGenerationBriefCommand
from ...contexts.generation.domain import GenerationNotFoundError
from ...database import FormatRecord, GenerationBriefRecord, SessionLocal
from ...domain import GenerationBriefRequest
from ...service import new_id


class LegacySqlAlchemyGenerationOperations:
    """Strangler adapter around Generation Brief persistence."""

    def __init__(
        self,
        session_factory: Callable[[], Session] = SessionLocal,
    ) -> None:
        self._session_factory = session_factory

    def create_brief(
        self,
        command: CreateGenerationBriefCommand,
    ) -> dict[str, Any]:
        payload = GenerationBriefRequest.model_validate(command.values)
        with self._session_factory() as db:
            if db.get(FormatRecord, payload.format_id) is None:
                raise GenerationNotFoundError("format not found")
            record = GenerationBriefRecord(
                id=new_id("brief"),
                topic=payload.topic,
                format_id=payload.format_id,
                payload=payload.model_dump(mode="json"),
            )
            db.add(record)
            db.commit()
            return {"id": record.id, **record.payload}
