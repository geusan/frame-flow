from __future__ import annotations

from typing import Any, Protocol

from ....domain import CanvasRunResponse, EventResponse, ExperimentRunResponse, RunResponse

from .use_cases import (
    ApproveCanvasNodeCommand,
    CreateExperimentCommand,
    CreateGenerationRunCommand,
    RegenerateNodeCommand,
    SelectCanvasCandidateCommand,
    SelectGenerationCandidateCommand,
    StartCanvasRunCommand,
)


class RunOperations(Protocol):
    """Outbound boundary for persisted Run state and execution runtimes."""

    def create_experiment(self, command: CreateExperimentCommand) -> ExperimentRunResponse: ...

    def list_costs(self, owner_id: str | None, limit: int, offset: int) -> list[dict[str, Any]]: ...

    async def start_canvas_run(self, command: StartCanvasRunCommand) -> CanvasRunResponse: ...

    def get_canvas_run(self, run_id: str) -> CanvasRunResponse: ...

    async def cancel_canvas_run(self, run_id: str) -> CanvasRunResponse: ...

    async def select_canvas_candidate(
        self,
        command: SelectCanvasCandidateCommand,
    ) -> CanvasRunResponse: ...

    async def approve_canvas_node(self, command: ApproveCanvasNodeCommand) -> CanvasRunResponse: ...

    def list_experiments(
        self,
        canvas_id: str,
        node_id: str | None,
        limit: int,
    ) -> list[ExperimentRunResponse]: ...

    def set_experiment_baseline(self, experiment_id: str) -> ExperimentRunResponse: ...

    async def create_generation_run(self, command: CreateGenerationRunCommand) -> RunResponse: ...

    def get_run(self, run_id: str) -> RunResponse: ...

    def list_runs(self) -> list[RunResponse]: ...

    async def cancel_run(self, run_id: str) -> RunResponse: ...

    def event_snapshot(self, run_id: str, offset: int) -> list[EventResponse]: ...

    async def wait_for_event(self, run_id: str) -> None: ...

    async def retry_node(self, node_run_id: str) -> dict[str, Any]: ...

    def regenerate_node(self, command: RegenerateNodeCommand) -> dict[str, Any]: ...

    def fork_node(self, node_run_id: str) -> dict[str, Any]: ...

    async def select_generation_candidate(
        self,
        command: SelectGenerationCandidateCommand,
    ) -> dict[str, Any]: ...
