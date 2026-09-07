from __future__ import annotations

from typing import Any, Protocol

from .use_cases import (
    CreateAnnotationCommand,
    CreateWorkflowCommand,
    PublishWorkflowCommand,
    StartWorkflowRunCommand,
    UpdateAnnotationCommand,
    UpdateWorkflowCommand,
)


class WorkflowOperations(Protocol):
    """Outbound boundary for the existing Workflow persistence/runtime implementation."""

    def create(self, command: CreateWorkflowCommand) -> dict[str, Any]: ...

    def list(self, status_filter: str | None) -> list[dict[str, Any]]: ...

    def get(self, workflow_id: str) -> dict[str, Any]: ...

    def update(self, command: UpdateWorkflowCommand) -> dict[str, Any]: ...

    def publish(self, command: PublishWorkflowCommand) -> dict[str, Any]: ...

    async def start_run(self, command: StartWorkflowRunCommand) -> Any: ...

    def list_versions(self, workflow_id: str) -> list[dict[str, Any]]: ...

    def get_version(
        self,
        workflow_id: str,
        version_number: int,
    ) -> dict[str, Any]: ...

    def list_annotations(
        self,
        workflow_id: str,
        version_number: int | None,
    ) -> list[dict[str, Any]]: ...

    def create_annotation(self, command: CreateAnnotationCommand) -> dict[str, Any]: ...

    def update_annotation(self, command: UpdateAnnotationCommand) -> dict[str, Any]: ...

    def delete_annotation(self, annotation_id: str, actor_id: str) -> None: ...

    def set_status(self, workflow_id: str, status: str) -> dict[str, Any]: ...

    def list_runs(self) -> list[dict[str, Any]]: ...
