from copy import deepcopy
from datetime import datetime, timezone
from types import TracebackType
from typing import Any

import pytest

from app.contexts.canvases.application import (
    CanvasApplication,
    CreateCanvasCommand,
    SaveCanvasCommand,
)
from app.contexts.canvases.domain import (
    Canvas,
    CanvasDeleteConflictError,
    CanvasRevisionConflictError,
    CanvasRunSummary,
)


NOW = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)
DEFAULT_CONTRACT = {
    "schema_version": "workflow.contract.draft.v1",
    "inputs": [],
    "bindings": [],
    "outputs": [],
}


class FakeCanvasRepository:
    def __init__(self) -> None:
        self.items: dict[str, Canvas] = {}
        self.run_summaries: dict[str, CanvasRunSummary] = {}

    def list_all(self) -> list[Canvas]:
        return [deepcopy(item) for item in self.items.values()]

    def get(self, canvas_id: str) -> Canvas | None:
        item = self.items.get(canvas_id)
        return deepcopy(item) if item else None

    def add(self, canvas: Canvas) -> None:
        self.items[canvas.id] = deepcopy(canvas)

    def save(self, canvas: Canvas) -> None:
        self.items[canvas.id] = deepcopy(canvas)

    def delete(self, canvas_id: str) -> bool:
        return self.items.pop(canvas_id, None) is not None

    def latest_run(self, canvas_id: str) -> CanvasRunSummary | None:
        return self.run_summaries.get(canvas_id)

    def latest_runs(self, canvas_ids: list[str]) -> dict[str, CanvasRunSummary]:
        return {
            canvas_id: self.run_summaries[canvas_id]
            for canvas_id in canvas_ids
            if canvas_id in self.run_summaries
        }


class FakeAuditLog:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict[str, Any]]] = []

    def record(
        self,
        action: str,
        subject_id: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        self.events.append((action, subject_id, payload or {}))


class FakeCanvasUnitOfWork:
    def __init__(
        self,
        canvases: FakeCanvasRepository,
        audit: FakeAuditLog,
    ) -> None:
        self.canvases = canvases
        self.audit = audit
        self.committed = False

    def __enter__(self) -> "FakeCanvasUnitOfWork":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        return None


def _application() -> tuple[CanvasApplication, FakeCanvasRepository, FakeAuditLog]:
    canvases = FakeCanvasRepository()
    audit = FakeAuditLog()
    application = CanvasApplication(
        uow_factory=lambda: FakeCanvasUnitOfWork(canvases, audit),
        id_generator=lambda prefix: f"{prefix}_generated",
        clock=lambda: NOW,
    )
    return application, canvases, audit


def test_create_canvas_uses_ports_without_database() -> None:
    application, canvases, audit = _application()

    created = application.create_canvas(
        CreateCanvasCommand(
            name="Clean Canvas",
            document=None,
            nodes=[],
            edges=[],
            draft_contract=DEFAULT_CONTRACT,
        )
    ).canvas

    assert created.id == "canvas_generated"
    assert created.graph_document["schema_version"] == "canvas.document.v1"
    assert canvases.get(created.id) == created
    assert audit.events == [
        ("canvas.created", created.id, {"name": "Clean Canvas"})
    ]


def test_save_canvas_preserves_revision_for_runtime_only_changes() -> None:
    application, canvases, _ = _application()
    created = application.create_canvas(
        CreateCanvasCommand(
            name="Draft",
            document=None,
            nodes=[],
            edges=[],
            draft_contract=DEFAULT_CONTRACT,
        )
    ).canvas

    runtime_update = application.save_canvas(
        SaveCanvasCommand(
            canvas_id=created.id,
            name=created.name,
            document=created.graph_document,
            active_run_id="run_1",
            expected_revision=1,
            default_draft_contract=DEFAULT_CONTRACT,
        )
    ).canvas
    definition_update = application.save_canvas(
        SaveCanvasCommand(
            canvas_id=created.id,
            name="Renamed",
            document=runtime_update.graph_document,
            active_run_id=runtime_update.active_run_id,
            expected_revision=1,
            default_draft_contract=DEFAULT_CONTRACT,
        )
    ).canvas

    assert runtime_update.revision == 1
    assert definition_update.revision == 2
    assert canvases.get(created.id) == definition_update


def test_save_canvas_rejects_stale_revision() -> None:
    application, _, _ = _application()
    created = application.create_canvas(
        CreateCanvasCommand(
            name="Draft",
            document=None,
            nodes=[],
            edges=[],
            draft_contract=DEFAULT_CONTRACT,
        )
    ).canvas

    with pytest.raises(CanvasRevisionConflictError, match="expected 9, current 1"):
        application.save_canvas(
            SaveCanvasCommand(
                canvas_id=created.id,
                name=created.name,
                document=created.graph_document,
                expected_revision=9,
                default_draft_contract=DEFAULT_CONTRACT,
            )
        )


def test_delete_canvas_rejects_workflow_draft() -> None:
    application, canvases, _ = _application()
    canvas = Canvas(
        id="canvas_workflow",
        created_at=NOW,
        updated_at=NOW,
        name="Workflow Draft",
        workflow_definition_id="workflow_1",
    )
    canvases.add(canvas)

    with pytest.raises(CanvasDeleteConflictError, match="archive the Workflow"):
        application.delete_canvas(canvas.id)

    assert canvases.get(canvas.id) == canvas
