from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ....domain import CanvasRunResponse, EventResponse, ExperimentRunResponse, RunResponse

if TYPE_CHECKING:
    from .ports import RunOperations


@dataclass(frozen=True)
class CreateExperimentCommand:
    values: dict[str, Any]


@dataclass(frozen=True)
class StartCanvasRunCommand:
    values: dict[str, Any]


@dataclass(frozen=True)
class SelectCanvasCandidateCommand:
    run_id: str
    canvas_node_id: str
    artifact_id: str


@dataclass(frozen=True)
class ApproveCanvasNodeCommand:
    run_id: str
    canvas_node_id: str
    parameters: dict[str, Any]


@dataclass(frozen=True)
class CreateGenerationRunCommand:
    values: dict[str, Any]


@dataclass(frozen=True)
class RegenerateNodeCommand:
    node_run_id: str
    values: dict[str, Any]


@dataclass(frozen=True)
class SelectGenerationCandidateCommand:
    node_run_id: str
    artifact_id: str


class RunApplication:
    def __init__(self, operations: "RunOperations") -> None:
        self._operations = operations

    def create_experiment(self, command: CreateExperimentCommand) -> ExperimentRunResponse:
        return self._operations.create_experiment(command)

    async def start_canvas_run(self, command: StartCanvasRunCommand) -> CanvasRunResponse:
        return await self._operations.start_canvas_run(command)

    def get_canvas_run(self, run_id: str) -> CanvasRunResponse:
        return self._operations.get_canvas_run(run_id)

    async def cancel_canvas_run(self, run_id: str) -> CanvasRunResponse:
        return await self._operations.cancel_canvas_run(run_id)

    async def select_canvas_candidate(
        self,
        command: SelectCanvasCandidateCommand,
    ) -> CanvasRunResponse:
        return await self._operations.select_canvas_candidate(command)

    async def approve_canvas_node(self, command: ApproveCanvasNodeCommand) -> CanvasRunResponse:
        return await self._operations.approve_canvas_node(command)

    def list_experiments(
        self,
        canvas_id: str,
        node_id: str | None,
        limit: int,
    ) -> list[ExperimentRunResponse]:
        return self._operations.list_experiments(canvas_id, node_id, limit)

    def set_experiment_baseline(self, experiment_id: str) -> ExperimentRunResponse:
        return self._operations.set_experiment_baseline(experiment_id)

    async def create_generation_run(
        self,
        command: CreateGenerationRunCommand,
    ) -> RunResponse:
        return await self._operations.create_generation_run(command)

    def get_run(self, run_id: str) -> RunResponse:
        return self._operations.get_run(run_id)

    def list_runs(self) -> list[RunResponse]:
        return self._operations.list_runs()

    async def cancel_run(self, run_id: str) -> RunResponse:
        return await self._operations.cancel_run(run_id)

    def event_snapshot(self, run_id: str, offset: int) -> list[EventResponse]:
        return self._operations.event_snapshot(run_id, offset)

    async def wait_for_event(self, run_id: str) -> None:
        await self._operations.wait_for_event(run_id)

    async def retry_node(self, node_run_id: str) -> dict[str, Any]:
        return await self._operations.retry_node(node_run_id)

    def regenerate_node(self, command: RegenerateNodeCommand) -> dict[str, Any]:
        return self._operations.regenerate_node(command)

    def fork_node(self, node_run_id: str) -> dict[str, Any]:
        return self._operations.fork_node(node_run_id)

    async def select_generation_candidate(
        self,
        command: SelectGenerationCandidateCommand,
    ) -> dict[str, Any]:
        return await self._operations.select_generation_candidate(command)
