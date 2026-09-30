from __future__ import annotations

import re
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ...database import ExperimentRunRecord
from ...nodes.contracts import ProviderTaskStateError


class SqlAlchemyNodeProviderTasks:
    """Persist billable submission state before a network call; resume queues, never blind-submit twice."""

    def __init__(self, session: Session, experiment_id: str, request_hash: str) -> None:
        self.session, self.experiment_id, self.request_hash = session, experiment_id, request_hash

    def _prefix(self, provider: str, stage: str) -> str:
        if not all(re.fullmatch(r"[a-z][a-z0-9_-]{0,30}", value) for value in (provider, stage)):
            raise ValueError("invalid provider task scope")
        return f"{provider}:{stage}:"

    def claim(self, provider: str, stage: str, *, resumable: bool) -> str | None:
        prefix = self._prefix(provider, stage)
        if self.session.get_bind().dialect.name == "postgresql":
            lock = int(self.request_hash[:16], 16)
            self.session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock if lock < 2**63 else lock - 2**64})
        previous = self.session.scalar(select(ExperimentRunRecord).where(
            ExperimentRunRecord.request_hash == self.request_hash,
            ExperimentRunRecord.provider_request_id.startswith(prefix),
        ).order_by(ExperimentRunRecord.created_at.desc()))
        record = self.session.get(ExperimentRunRecord, self.experiment_id)
        if record is None:
            raise ProviderTaskStateError("Active experiment is missing")
        if previous:
            task_id = str(previous.provider_request_id)[len(prefix):]
            if task_id == "rejected":
                record.provider_request_id = prefix + "pending"
                self.session.commit()
                return None
            if task_id == "pending" or not resumable:
                raise ProviderTaskStateError(f"A {provider} submission already exists with an unresolved outcome. Inspect provider history before another billable request.")
            record.provider_request_id = prefix + task_id
            self.session.commit()
            return task_id
        record.provider_request_id = prefix + "pending"
        self.session.commit()
        return None

    def remember(self, provider: str, stage: str, task_id: str) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,180}", task_id):
            raise ProviderTaskStateError("Provider returned an invalid task identifier")
        record = self.session.get(ExperimentRunRecord, self.experiment_id)
        if record is None:
            raise ProviderTaskStateError("Active experiment is missing")
        record.provider_request_id = self._prefix(provider, stage) + task_id
        self.session.commit()
