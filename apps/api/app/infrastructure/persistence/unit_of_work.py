from __future__ import annotations

from types import TracebackType
from typing import Callable

from sqlalchemy.orm import Session

from ...contexts.canvases.application.ports import AuditLog, CanvasRepository
from ...database import SessionLocal
from .audit_log import SqlAlchemyAuditLog
from .canvas_repository import SqlAlchemyCanvasRepository


class SqlAlchemyCanvasUnitOfWork:
    def __init__(
        self,
        session_factory: Callable[[], Session] = SessionLocal,
    ) -> None:
        self._session_factory = session_factory
        self._session: Session | None = None
        self.canvases: CanvasRepository
        self.audit: AuditLog

    def __enter__(self) -> "SqlAlchemyCanvasUnitOfWork":
        if self._session is not None:
            raise RuntimeError("Canvas UnitOfWork is already active")
        self._session = self._session_factory()
        self.canvases = SqlAlchemyCanvasRepository(self._session)
        self.audit = SqlAlchemyAuditLog(self._session)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback
        try:
            self.rollback()
        finally:
            if self._session is not None:
                self._session.close()
                self._session = None

    def commit(self) -> None:
        self._require_session().commit()

    def rollback(self) -> None:
        if self._session is not None:
            self._session.rollback()

    def _require_session(self) -> Session:
        if self._session is None:
            raise RuntimeError("Canvas UnitOfWork is not active")
        return self._session
