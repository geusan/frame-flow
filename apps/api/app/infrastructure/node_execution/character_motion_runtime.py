from __future__ import annotations

import threading

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ...character_motion.tripo import (
    TRIPO_TASK_ID_PATTERN,
    TripoProviderError,
)
from ...database import ExperimentRunRecord


_TRIPO_SUBMISSION_GUARD = threading.Lock()


class SqlAlchemyNodeCharacterMotionRuntime:
    def __init__(self, session: Session) -> None:
        self._session = session

    def remember_task(
        self,
        request_hash: str,
        experiment_id: str,
        stage: str,
        task_id: str,
    ) -> None:
        if task_id == "pending":
            with _TRIPO_SUBMISSION_GUARD:
                bind = self._session.get_bind()
                if bind.dialect.name == "postgresql":
                    lock_key = int(request_hash[:16], 16)
                    if lock_key >= 2**63:
                        lock_key -= 2**64
                    self._session.execute(
                        text("SELECT pg_advisory_xact_lock(:key)"),
                        {"key": lock_key},
                    )
                existing_values = self._session.scalars(
                    select(ExperimentRunRecord.provider_request_id)
                    .where(
                        ExperimentRunRecord.request_hash == request_hash,
                        ExperimentRunRecord.id != experiment_id,
                        ExperimentRunRecord.provider_request_id.is_not(None),
                    )
                    .order_by(ExperimentRunRecord.created_at.desc())
                ).all()
                conflicts = [
                    str(value)
                    for value in existing_values
                    if str(value).startswith(f"tripo:{stage}:")
                ]
                if conflicts:
                    raise TripoProviderError(
                        f"An identical Tripo {stage} submission already exists. "
                        "A second billable request was blocked; wait for the existing "
                        "task or resume it from Task History.",
                        retryable=False,
                    )
                record = self._session.get(ExperimentRunRecord, experiment_id)
                if record is None:
                    raise RuntimeError(
                        "Tripo task could not be attached to the active Experiment"
                    )
                record.provider_request_id = f"tripo:{stage}:pending"
                self._session.commit()
            return
        record = self._session.get(ExperimentRunRecord, experiment_id)
        if record is None:
            raise RuntimeError("Tripo task could not be attached to the active Experiment")
        record.provider_request_id = f"tripo:{stage}:{task_id}"
        self._session.commit()

    def resume_task(
        self,
        request_hash: str,
        experiment_id: str,
        allowed_stages: set[str],
    ) -> tuple[str | None, str | None]:
        previous = self._session.scalar(
            select(ExperimentRunRecord)
            .where(
                ExperimentRunRecord.request_hash == request_hash,
                ExperimentRunRecord.id != experiment_id,
                ExperimentRunRecord.provider_request_id.is_not(None),
            )
            .order_by(ExperimentRunRecord.created_at.desc())
        )
        if previous is None:
            return None, None
        value = str(previous.provider_request_id or "")
        parts = value.split(":", 2)
        if (
            len(parts) == 3
            and parts[0] == "tripo"
            and parts[1] in allowed_stages
            and parts[2] == "pending"
        ):
            raise TripoProviderError(
                f"A previous Tripo {parts[1]} submission has an unknown outcome. "
                "Automatic resubmission is blocked; inspect Tripo Task History and "
                "attach the returned task ID before retrying.",
                retryable=False,
            )
        if (
            len(parts) != 3
            or parts[0] != "tripo"
            or parts[1] not in allowed_stages
            or not TRIPO_TASK_ID_PATTERN.fullmatch(parts[2])
        ):
            return None, None
        return parts[1], parts[2]
