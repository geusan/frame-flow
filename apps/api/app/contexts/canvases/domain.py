from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


class CanvasError(Exception):
    pass


class CanvasNotFoundError(CanvasError):
    pass


class CanvasRevisionConflictError(CanvasError):
    pass


class CanvasDeleteConflictError(CanvasError):
    pass


class CanvasValidationError(CanvasError):
    pass


@dataclass
class Canvas:
    id: str
    created_at: datetime
    updated_at: datetime
    name: str
    graph_document: dict[str, Any] = field(default_factory=dict)
    active_run_id: str | None = None
    workflow_definition_id: str | None = None
    base_version_id: str | None = None
    revision: int = 1
    draft_contract: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CanvasRunSummary:
    id: str
    status: str
    progress: int
    created_at: datetime
