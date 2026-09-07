from __future__ import annotations

from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...canvas_runs import canvas_run_response, create_canvas_run
from ...contexts.workflows.application import (
    CreateAnnotationCommand,
    CreateWorkflowCommand,
    PublishWorkflowCommand,
    StartWorkflowRunCommand,
    UpdateAnnotationCommand,
    UpdateWorkflowCommand,
)
from ...contexts.workflows.domain import (
    WorkflowConflictError,
    WorkflowNotFoundError,
    WorkflowValidationError,
)
from ...database import (
    CanvasRunRecord,
    RunRecord,
    SessionLocal,
    WorkflowAnnotationRecord,
    WorkflowDefinitionRecord,
    WorkflowVersionRecord,
)
from ...domain import (
    NodeStatus,
    WorkflowAnnotationCreateRequest,
    WorkflowAnnotationUpdateRequest,
    WorkflowCreateRequest,
    WorkflowPublishRequest,
    WorkflowUpdateRequest,
    WorkflowVersionRunRequest,
    utc_now,
)
from ...service import audit
from ...workflow_definitions import (
    WORKFLOW_COMPILER_VERSION,
    WorkflowContractError,
    create_annotation,
    create_workflow_definition,
    delete_annotation,
    publish_workflow_version,
    resolve_workflow_execution,
    update_annotation,
    update_workflow_definition,
    workflow_annotation_payload,
    workflow_definition_payload,
    workflow_version_payload,
)
from ...workflow_runtime_service import schedule_canvas_run


def _translate_contract_error(exc: WorkflowContractError) -> Exception:
    message = str(exc)
    if "conflict" in message.lower() or "already belongs" in message.lower():
        return WorkflowConflictError(message)
    return WorkflowValidationError(message)


class LegacySqlAlchemyWorkflowOperations:
    """Strangler adapter around the existing Workflow SQLAlchemy implementation."""

    def __init__(
        self,
        session_factory: Callable[[], Session] = SessionLocal,
    ) -> None:
        self._session_factory = session_factory

    @staticmethod
    def _workflow_or_error(
        db: Session,
        workflow_id: str,
    ) -> WorkflowDefinitionRecord:
        record = db.get(WorkflowDefinitionRecord, workflow_id)
        if record is None:
            raise WorkflowNotFoundError("Workflow not found")
        return record

    @staticmethod
    def _version_or_error(
        db: Session,
        workflow_id: str,
        version_number: int,
    ) -> WorkflowVersionRecord:
        record = db.scalar(
            select(WorkflowVersionRecord).where(
                WorkflowVersionRecord.workflow_definition_id == workflow_id,
                WorkflowVersionRecord.version_number == version_number,
            )
        )
        if record is None:
            raise WorkflowNotFoundError("Workflow Version not found")
        return record

    def create(self, command: CreateWorkflowCommand) -> dict[str, Any]:
        with self._session_factory() as db:
            try:
                record = create_workflow_definition(
                    db,
                    WorkflowCreateRequest(
                        name=command.name,
                        description=command.description,
                        tags=command.tags,
                        source_canvas_id=command.source_canvas_id,
                    ),
                )
            except WorkflowContractError as exc:
                raise _translate_contract_error(exc) from exc
            return workflow_definition_payload(record, db)

    def list(self, status_filter: str | None) -> list[dict[str, Any]]:
        with self._session_factory() as db:
            query = select(WorkflowDefinitionRecord)
            if status_filter:
                query = query.where(
                    WorkflowDefinitionRecord.status == status_filter.upper()
                )
            records = db.scalars(
                query.order_by(WorkflowDefinitionRecord.updated_at.desc())
            ).all()
            return [workflow_definition_payload(record, db) for record in records]

    def get(self, workflow_id: str) -> dict[str, Any]:
        with self._session_factory() as db:
            return workflow_definition_payload(
                self._workflow_or_error(db, workflow_id),
                db,
            )

    def update(self, command: UpdateWorkflowCommand) -> dict[str, Any]:
        with self._session_factory() as db:
            record = update_workflow_definition(
                db,
                self._workflow_or_error(db, command.workflow_id),
                WorkflowUpdateRequest.model_validate(command.values),
            )
            return workflow_definition_payload(record, db)

    def publish(self, command: PublishWorkflowCommand) -> dict[str, Any]:
        with self._session_factory() as db:
            try:
                version, warnings = publish_workflow_version(
                    db,
                    command.workflow_id,
                    WorkflowPublishRequest(
                        expected_canvas_revision=command.expected_canvas_revision,
                        release_notes=command.release_notes,
                        published_by=command.published_by,
                    ),
                )
            except WorkflowContractError as exc:
                raise _translate_contract_error(exc) from exc
            return {**workflow_version_payload(version), "warnings": warnings}

    async def start_run(self, command: StartWorkflowRunCommand) -> Any:
        with self._session_factory() as db:
            definition = self._workflow_or_error(db, command.workflow_id)
            if definition.status != "ACTIVE":
                raise WorkflowValidationError("Archived Workflow cannot be run")
            if command.version is not None:
                version = self._version_or_error(
                    db,
                    command.workflow_id,
                    command.version,
                )
            elif definition.current_version_id:
                version = db.get(WorkflowVersionRecord, definition.current_version_id)
            else:
                version = None
            if version is None:
                raise WorkflowValidationError("Workflow has no published Version")
            try:
                run_payload, resolved_inputs, model_snapshot = (
                    resolve_workflow_execution(
                        db,
                        definition,
                        version,
                        WorkflowVersionRunRequest(
                            version=command.version,
                            inputs=command.inputs,
                        ),
                    )
                )
                run = create_canvas_run(db, run_payload)
            except (WorkflowContractError, ValueError, RuntimeError) as exc:
                raise WorkflowValidationError(str(exc)) from exc
            run.source_type = "WORKFLOW_VERSION"
            run.workflow_definition_id = definition.id
            run.workflow_version_id = version.id
            run.input_snapshot = resolved_inputs
            run.model_snapshot = model_snapshot
            run.compiler_version = WORKFLOW_COMPILER_VERSION
            audit(
                db,
                "workflow.run_created",
                run.id,
                {
                    "workflow_definition_id": definition.id,
                    "workflow_version_id": version.id,
                    "version_number": version.version_number,
                },
            )
            db.commit()
            db.refresh(run)
            await schedule_canvas_run(run, run_payload.nodes)
            return canvas_run_response(run)

    def list_versions(self, workflow_id: str) -> list[dict[str, Any]]:
        with self._session_factory() as db:
            self._workflow_or_error(db, workflow_id)
            records = db.scalars(
                select(WorkflowVersionRecord)
                .where(WorkflowVersionRecord.workflow_definition_id == workflow_id)
                .order_by(WorkflowVersionRecord.version_number.desc())
            ).all()
            return [workflow_version_payload(record) for record in records]

    def get_version(
        self,
        workflow_id: str,
        version_number: int,
    ) -> dict[str, Any]:
        with self._session_factory() as db:
            return workflow_version_payload(
                self._version_or_error(db, workflow_id, version_number)
            )

    def list_annotations(
        self,
        workflow_id: str,
        version_number: int | None,
    ) -> list[dict[str, Any]]:
        with self._session_factory() as db:
            self._workflow_or_error(db, workflow_id)
            version_id = (
                self._version_or_error(db, workflow_id, version_number).id
                if version_number is not None
                else None
            )
            query = select(WorkflowAnnotationRecord).where(
                WorkflowAnnotationRecord.workflow_definition_id == workflow_id,
                WorkflowAnnotationRecord.deleted_at.is_(None),
            )
            query = query.where(
                WorkflowAnnotationRecord.workflow_version_id == version_id
                if version_id is not None
                else WorkflowAnnotationRecord.workflow_version_id.is_(None)
            )
            records = db.scalars(
                query.order_by(WorkflowAnnotationRecord.created_at)
            ).all()
            return [workflow_annotation_payload(record) for record in records]

    def create_annotation(
        self,
        command: CreateAnnotationCommand,
    ) -> dict[str, Any]:
        with self._session_factory() as db:
            definition = self._workflow_or_error(db, command.workflow_id)
            version = (
                self._version_or_error(
                    db,
                    command.workflow_id,
                    command.version_number,
                )
                if command.version_number is not None
                else None
            )
            try:
                record = create_annotation(
                    db,
                    definition,
                    WorkflowAnnotationCreateRequest.model_validate(command.values),
                    version=version,
                )
            except WorkflowContractError as exc:
                raise _translate_contract_error(exc) from exc
            return workflow_annotation_payload(record)

    def update_annotation(
        self,
        command: UpdateAnnotationCommand,
    ) -> dict[str, Any]:
        with self._session_factory() as db:
            record = db.get(WorkflowAnnotationRecord, command.annotation_id)
            if record is None or record.deleted_at:
                raise WorkflowNotFoundError("Workflow Annotation not found")
            try:
                record = update_annotation(
                    db,
                    record,
                    WorkflowAnnotationUpdateRequest.model_validate(command.values),
                )
            except WorkflowContractError as exc:
                raise _translate_contract_error(exc) from exc
            return workflow_annotation_payload(record)

    def delete_annotation(self, annotation_id: str, actor_id: str) -> None:
        with self._session_factory() as db:
            record = db.get(WorkflowAnnotationRecord, annotation_id)
            if record is None or record.deleted_at:
                raise WorkflowNotFoundError("Workflow Annotation not found")
            delete_annotation(db, record, actor_id)

    def set_status(self, workflow_id: str, status: str) -> dict[str, Any]:
        with self._session_factory() as db:
            record = self._workflow_or_error(db, workflow_id)
            record.status = status
            record.updated_at = utc_now()
            audit(
                db,
                "workflow.archived" if status == "ARCHIVED" else "workflow.activated",
                record.id,
            )
            db.commit()
            db.refresh(record)
            return workflow_definition_payload(record, db)

    def list_runs(self) -> list[dict[str, Any]]:
        with self._session_factory() as db:
            rows: list[dict[str, Any]] = []
            regular_runs = db.scalars(
                select(RunRecord).order_by(RunRecord.created_at.desc())
            ).unique().all()
            for run in regular_runs:
                rows.append(
                    {
                        "id": run.id,
                        "created_at": run.created_at,
                        "run_type": "generation",
                        "name": run.name,
                        "status": run.status,
                        "progress": run.progress,
                        "cost_usd": run.actual_cost_usd,
                        "estimated_cost_usd": run.estimated_cost_usd,
                        "nodes_done": sum(
                            node.status == NodeStatus.SUCCEEDED
                            for node in run.node_runs
                        ),
                        "nodes_total": len(run.node_runs),
                        "attempt_count": sum(
                            node.attempt_count for node in run.node_runs
                        ),
                        "duration_ms": None,
                    }
                )
            canvas_runs = db.scalars(
                select(CanvasRunRecord).order_by(CanvasRunRecord.created_at.desc())
            ).unique().all()
            for run in canvas_runs:
                rows.append(
                    {
                        "id": run.id,
                        "created_at": run.created_at,
                        "run_type": (
                            "workflow"
                            if run.source_type == "WORKFLOW_VERSION"
                            else "canvas"
                        ),
                        "name": run.name,
                        "status": run.status,
                        "progress": run.progress,
                        "cost_usd": sum(node.cost_usd for node in run.node_runs),
                        "estimated_cost_usd": None,
                        "nodes_done": sum(
                            node.status == NodeStatus.SUCCEEDED
                            for node in run.node_runs
                        ),
                        "nodes_total": len(run.node_runs),
                        "attempt_count": sum(
                            node.attempt_count for node in run.node_runs
                        ),
                        "duration_ms": (
                            sum(node.duration_ms for node in run.node_runs) or None
                        ),
                        "workflow_definition_id": run.workflow_definition_id,
                        "workflow_version_id": run.workflow_version_id,
                    }
                )
            return sorted(rows, key=lambda row: row["created_at"], reverse=True)
