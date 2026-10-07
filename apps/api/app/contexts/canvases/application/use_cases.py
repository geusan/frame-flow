from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from ....canvas_documents import (
    canonical_canvas_graph,
    canonicalize_canvas_document,
    legacy_canvas_graph,
    normalize_canvas_document,
)
from ..domain import (
    Canvas,
    CanvasDeleteConflictError,
    CanvasNotFoundError,
    CanvasRevisionConflictError,
    CanvasRunSummary,
    CanvasValidationError,
)
from .ports import CanvasUnitOfWork


UnitOfWorkFactory = Callable[[], CanvasUnitOfWork]
IdGenerator = Callable[[str], str]
Clock = Callable[[], datetime]


@dataclass(frozen=True)
class CanvasDetails:
    canvas: Canvas
    last_run: CanvasRunSummary | None = None


@dataclass(frozen=True)
class CreateCanvasCommand:
    name: str
    document: dict[str, Any] | None
    nodes: list[dict[str, Any]] = field(default_factory=list)
    edges: list[dict[str, Any]] = field(default_factory=list)
    active_run_id: str | None = None
    draft_contract: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SaveCanvasCommand:
    canvas_id: str
    name: str
    document: dict[str, Any] | None
    nodes: list[dict[str, Any]] = field(default_factory=list)
    edges: list[dict[str, Any]] = field(default_factory=list)
    active_run_id: str | None = None
    expected_revision: int | None = None
    draft_contract: dict[str, Any] | None = None
    default_draft_contract: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ImportCanvasCommand:
    name: str
    graph_document: dict[str, Any]
    draft_contract: dict[str, Any]
    filename: str
    package_sha256: str
    package_source: str
    warnings: list[str] = field(default_factory=list)


def _request_document(
    document: dict[str, Any] | None,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> dict[str, Any]:
    try:
        if document is not None:
            return normalize_canvas_document(document)
        return canonicalize_canvas_document(nodes, edges)
    except ValueError as exc:
        raise CanvasValidationError(str(exc)) from exc


class CanvasApplication:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        id_generator: IdGenerator,
        clock: Clock,
    ) -> None:
        self._uow_factory = uow_factory
        self._id_generator = id_generator
        self._clock = clock

    def list_canvases(self) -> list[CanvasDetails]:
        with self._uow_factory() as uow:
            canvases = uow.canvases.list_all()
            latest_runs = uow.canvases.latest_runs(
                [canvas.id for canvas in canvases]
            )
            return [
                CanvasDetails(canvas, latest_runs.get(canvas.id))
                for canvas in canvases
            ]

    def get_canvas(self, canvas_id: str) -> CanvasDetails:
        with self._uow_factory() as uow:
            canvas = uow.canvases.get(canvas_id)
            if canvas is None:
                raise CanvasNotFoundError("canvas not found")
            return CanvasDetails(canvas, uow.canvases.latest_run(canvas_id))

    def create_canvas(self, command: CreateCanvasCommand) -> CanvasDetails:
        graph_document = _request_document(
            command.document,
            command.nodes,
            command.edges,
        )
        now = self._clock()
        canvas = Canvas(
            id=self._id_generator("canvas"),
            created_at=now,
            updated_at=now,
            name=command.name,
            graph_document=graph_document,
            active_run_id=command.active_run_id,
            revision=1,
            draft_contract=deepcopy(command.draft_contract),
        )
        with self._uow_factory() as uow:
            uow.canvases.add(canvas)
            uow.audit.record("canvas.created", canvas.id, {"name": canvas.name})
            uow.commit()
        return CanvasDetails(canvas)

    def import_canvas(self, command: ImportCanvasCommand) -> CanvasDetails:
        now = self._clock()
        canvas = Canvas(
            id=self._id_generator("canvas"),
            created_at=now,
            updated_at=now,
            name=command.name,
            graph_document=deepcopy(command.graph_document),
            revision=1,
            draft_contract=deepcopy(command.draft_contract),
        )
        with self._uow_factory() as uow:
            uow.canvases.add(canvas)
            uow.audit.record(
                "canvas.package_imported",
                canvas.id,
                {
                    "filename": command.filename,
                    "package_sha256": command.package_sha256,
                    "source": command.package_source,
                    "warnings": command.warnings,
                },
            )
            uow.commit()
        return CanvasDetails(canvas)

    def save_canvas(self, command: SaveCanvasCommand) -> CanvasDetails:
        next_graph = _request_document(
            command.document,
            command.nodes,
            command.edges,
        )
        now = self._clock()
        with self._uow_factory() as uow:
            canvas = uow.canvases.get(command.canvas_id)
            created = canvas is None
            if canvas is None:
                from ....access import current_scope
                if current_scope():
                    raise CanvasNotFoundError("canvas not found")
                canvas = Canvas(
                    id=command.canvas_id,
                    created_at=now,
                    updated_at=now,
                    name=command.name,
                    graph_document=canonicalize_canvas_document([], []),
                    revision=1,
                    draft_contract=deepcopy(command.default_draft_contract),
                )
            elif (
                command.expected_revision is not None
                and canvas.revision != command.expected_revision
            ):
                raise CanvasRevisionConflictError(
                    "Canvas revision conflict: "
                    f"expected {command.expected_revision}, current {canvas.revision}"
                )

            next_contract = (
                deepcopy(command.draft_contract)
                if command.draft_contract is not None
                else deepcopy(canvas.draft_contract or command.default_draft_contract)
            )
            definition_changed = (
                canvas.name != command.name
                or canonical_canvas_graph(canvas.graph_document)
                != canonical_canvas_graph(next_graph)
                or canvas.draft_contract != next_contract
            )
            canvas.name = command.name
            canvas.graph_document = next_graph
            canvas.draft_contract = next_contract
            canvas.active_run_id = command.active_run_id
            if not created and definition_changed:
                canvas.revision += 1
            canvas.updated_at = now

            if created:
                uow.canvases.add(canvas)
            else:
                uow.canvases.save(canvas)
            saved_graph = legacy_canvas_graph(next_graph)
            uow.audit.record(
                "canvas.imported" if created else "canvas.saved",
                canvas.id,
                {
                    "node_count": len(saved_graph["nodes"]),
                    "edge_count": len(saved_graph["edges"]),
                    "write_schema_version": str(
                        next_graph.get("schema_version") or "canvas.legacy.v1"
                    ),
                },
            )
            uow.commit()
            return CanvasDetails(canvas)

    def delete_canvas(self, canvas_id: str) -> None:
        with self._uow_factory() as uow:
            canvas = uow.canvases.get(canvas_id)
            if canvas is None:
                raise CanvasNotFoundError("canvas not found")
            if canvas.workflow_definition_id:
                raise CanvasDeleteConflictError(
                    "Workflow Draft Canvas cannot be deleted directly; "
                    "archive the Workflow instead"
                )
            uow.canvases.delete(canvas_id)
            uow.audit.record("canvas.deleted", canvas_id)
            uow.commit()
