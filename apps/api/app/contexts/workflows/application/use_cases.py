from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .ports import WorkflowOperations


@dataclass(frozen=True)
class CreateWorkflowCommand:
    name: str
    description: str = ""
    tags: list[str] = field(default_factory=list)
    source_canvas_id: str | None = None


@dataclass(frozen=True)
class UpdateWorkflowCommand:
    workflow_id: str
    values: dict[str, Any]


@dataclass(frozen=True)
class PublishWorkflowCommand:
    workflow_id: str
    expected_canvas_revision: int
    release_notes: str = ""
    published_by: str = "local-user"


@dataclass(frozen=True)
class StartWorkflowRunCommand:
    workflow_id: str
    version: int | None
    inputs: dict[str, Any]


@dataclass(frozen=True)
class CreateAnnotationCommand:
    workflow_id: str
    version_number: int | None
    values: dict[str, Any]


@dataclass(frozen=True)
class UpdateAnnotationCommand:
    annotation_id: str
    values: dict[str, Any]


class WorkflowApplication:
    def __init__(self, operations: "WorkflowOperations") -> None:
        self._operations = operations

    def create(self, command: CreateWorkflowCommand) -> dict[str, Any]:
        return self._operations.create(command)

    def list(self, status_filter: str | None = None) -> list[dict[str, Any]]:
        return self._operations.list(status_filter)

    def get(self, workflow_id: str) -> dict[str, Any]:
        return self._operations.get(workflow_id)

    def update(self, command: UpdateWorkflowCommand) -> dict[str, Any]:
        return self._operations.update(command)

    def publish(self, command: PublishWorkflowCommand) -> dict[str, Any]:
        return self._operations.publish(command)

    async def start_run(self, command: StartWorkflowRunCommand) -> Any:
        return await self._operations.start_run(command)

    def list_versions(self, workflow_id: str) -> list[dict[str, Any]]:
        return self._operations.list_versions(workflow_id)

    def get_version(
        self,
        workflow_id: str,
        version_number: int,
    ) -> dict[str, Any]:
        return self._operations.get_version(workflow_id, version_number)

    def list_annotations(
        self,
        workflow_id: str,
        version_number: int | None = None,
    ) -> list[dict[str, Any]]:
        return self._operations.list_annotations(workflow_id, version_number)

    def create_annotation(self, command: CreateAnnotationCommand) -> dict[str, Any]:
        return self._operations.create_annotation(command)

    def update_annotation(self, command: UpdateAnnotationCommand) -> dict[str, Any]:
        return self._operations.update_annotation(command)

    def delete_annotation(self, annotation_id: str, actor_id: str) -> None:
        self._operations.delete_annotation(annotation_id, actor_id)

    def archive(self, workflow_id: str) -> dict[str, Any]:
        return self._operations.set_status(workflow_id, "ARCHIVED")

    def activate(self, workflow_id: str) -> dict[str, Any]:
        return self._operations.set_status(workflow_id, "ACTIVE")

    def list_runs(self) -> list[dict[str, Any]]:
        return self._operations.list_runs()
