from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...contexts.canvases.domain import Canvas, CanvasRunSummary
from ...database import CanvasRecord, CanvasRunRecord


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class SqlAlchemyCanvasRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list_all(self) -> list[Canvas]:
        records = self._session.scalars(
            select(CanvasRecord).order_by(CanvasRecord.updated_at.desc())
        ).all()
        return [self._to_domain(record) for record in records]

    def get(self, canvas_id: str) -> Canvas | None:
        record = self._session.get(CanvasRecord, canvas_id)
        return self._to_domain(record) if record else None

    def add(self, canvas: Canvas) -> None:
        if self._session.get(CanvasRecord, canvas.id) is not None:
            raise ValueError(f"Canvas already exists: {canvas.id}")
        self._session.add(self._to_record(canvas))

    def save(self, canvas: Canvas) -> None:
        record = self._session.get(CanvasRecord, canvas.id)
        if record is None:
            raise ValueError(f"Canvas was not found: {canvas.id}")
        self._apply(record, canvas)

    def delete(self, canvas_id: str) -> bool:
        record = self._session.get(CanvasRecord, canvas_id)
        if record is None:
            return False
        self._session.delete(record)
        return True

    def latest_run(self, canvas_id: str) -> CanvasRunSummary | None:
        return self.latest_runs([canvas_id]).get(canvas_id)

    def latest_runs(self, canvas_ids: list[str]) -> dict[str, CanvasRunSummary]:
        if not canvas_ids:
            return {}
        records = self._session.scalars(
            select(CanvasRunRecord)
            .where(CanvasRunRecord.canvas_id.in_(canvas_ids))
            .order_by(CanvasRunRecord.created_at.desc())
        ).all()
        latest: dict[str, CanvasRunSummary] = {}
        for record in records:
            latest.setdefault(
                record.canvas_id,
                CanvasRunSummary(
                    id=record.id,
                    status=str(record.status),
                    progress=record.progress,
                    created_at=_as_utc(record.created_at),
                ),
            )
        return latest

    @staticmethod
    def _to_domain(record: CanvasRecord) -> Canvas:
        return Canvas(
            id=record.id,
            created_at=_as_utc(record.created_at),
            updated_at=_as_utc(record.updated_at),
            name=record.name,
            graph_document=dict(record.graph_json or {}),
            active_run_id=record.active_run_id,
            workflow_definition_id=record.workflow_definition_id,
            base_version_id=record.base_version_id,
            revision=record.revision,
            draft_contract=dict(record.draft_contract_json or {}),
        )

    @staticmethod
    def _to_record(canvas: Canvas) -> CanvasRecord:
        return CanvasRecord(
            id=canvas.id,
            created_at=canvas.created_at,
            updated_at=canvas.updated_at,
            name=canvas.name,
            graph_json=canvas.graph_document,
            active_run_id=canvas.active_run_id,
            workflow_definition_id=canvas.workflow_definition_id,
            base_version_id=canvas.base_version_id,
            revision=canvas.revision,
            draft_contract_json=canvas.draft_contract,
        )

    @staticmethod
    def _apply(record: CanvasRecord, canvas: Canvas) -> None:
        record.created_at = canvas.created_at
        record.updated_at = canvas.updated_at
        record.name = canvas.name
        record.graph_json = canvas.graph_document
        record.active_run_id = canvas.active_run_id
        record.workflow_definition_id = canvas.workflow_definition_id
        record.base_version_id = canvas.base_version_id
        record.revision = canvas.revision
        record.draft_contract_json = canvas.draft_contract
