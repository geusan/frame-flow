from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from ...database import AuditEventRecord


class SqlAlchemyAuditLog:
    def __init__(self, session: Session) -> None:
        self._session = session

    def record(
        self,
        action: str,
        subject_id: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        self._session.add(
            AuditEventRecord(
                id=f"audit_{uuid.uuid4().hex[:18]}",
                action=action,
                subject_id=subject_id,
                payload=payload or {},
            )
        )
