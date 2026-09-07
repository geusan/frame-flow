from __future__ import annotations

from typing import Any, Protocol

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

    def create_experiment(self, command: CreateExperimentCommand) -> Any: ...

    async def start_canvas_run(self, command: StartCanvasRunCommand) -> Any: ...

    def get_canvas_run(self, run_id: str) -> Any: ...

    async def cancel_canvas_run(self, run_id: str) -> Any: ...

    async def select_canvas_candidate(
        self,
        command: SelectCanvasCandidateCommand,
    ) -> Any: ...

    async def approve_canvas_node(self, command: ApproveCanvasNodeCommand) -> Any: ...

    def list_experiments(
        self,
        canvas_id: str,
        node_id: str | None,
        limit: int,
    ) -> list[Any]: ...

    def set_experiment_baseline(self, experiment_id: str) -> Any: ...

    async def create_generation_run(self, command: CreateGenerationRunCommand) -> Any: ...

    def get_run(self, run_id: str) -> Any: ...

    def list_runs(self) -> list[Any]: ...

    async def cancel_run(self, run_id: str) -> Any: ...

    def event_snapshot(self, run_id: str, offset: int) -> list[Any]: ...

    async def wait_for_event(self, run_id: str) -> None: ...

    async def retry_node(self, node_run_id: str) -> dict[str, Any]: ...

    def regenerate_node(self, command: RegenerateNodeCommand) -> dict[str, Any]: ...

    def fork_node(self, node_run_id: str) -> dict[str, Any]: ...

    async def select_generation_candidate(
        self,
        command: SelectGenerationCandidateCommand,
    ) -> dict[str, Any]: ...
