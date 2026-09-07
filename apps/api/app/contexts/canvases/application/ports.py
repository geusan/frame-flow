from __future__ import annotations

from types import TracebackType
from typing import Any, Protocol, Self

from ..domain import Canvas, CanvasRunSummary


class CanvasRepository(Protocol):
    def list_all(self) -> list[Canvas]: ...

    def get(self, canvas_id: str) -> Canvas | None: ...

    def add(self, canvas: Canvas) -> None: ...

    def save(self, canvas: Canvas) -> None: ...

    def delete(self, canvas_id: str) -> bool: ...

    def latest_run(self, canvas_id: str) -> CanvasRunSummary | None: ...

    def latest_runs(self, canvas_ids: list[str]) -> dict[str, CanvasRunSummary]: ...


class AuditLog(Protocol):
    def record(
        self,
        action: str,
        subject_id: str,
        payload: dict[str, Any] | None = None,
    ) -> None: ...


class CanvasUnitOfWork(Protocol):
    canvases: CanvasRepository
    audit: AuditLog

    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...
