from __future__ import annotations

from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...canvas_runs import get_local_canvas_engine
from ...canvas_runs import (
    canvas_run_response,
    create_canvas_run,
    local_canvas_engine,
    record_canvas_approval,
    record_canvas_selection,
)
from ...canvas_temporal import CanvasRunWorkflow
from ...compiler import CompileError, DEFAULT_NODES, compile_generation_plan
from ...contexts.runs.application import (
    ApproveCanvasNodeCommand,
    CreateExperimentCommand,
    CreateGenerationRunCommand,
    RegenerateNodeCommand,
    SelectCanvasCandidateCommand,
    SelectGenerationCandidateCommand,
    StartCanvasRunCommand,
)
from ...contexts.runs.domain import (
    RunConflictError,
    RunNotFoundError,
    RunValidationError,
    require_successful_baseline,
)
from ...database import (
    CanvasRecord,
    CanvasRunRecord,
    ExperimentRunRecord,
    GenerationBriefRecord,
    NodeRunRecord,
    RunRecord,
    SessionLocal,
)
from ...domain import (
    CanvasRunRequest,
    ExperimentRunRequest,
    GenerationRunRequest,
    NodeStatus,
    RegenerateRequest,
    utc_now,
)
from ...experiments import experiment_response, run_experiment
from ...service import audit, broker, create_artifact, local_engine, new_id, run_response
from ...temporal_runtime import TASK_QUEUE
from ...temporal_workflow import GenerationRunWorkflow, GenerationWorkflowInput
from ...workflow_runtime_service import schedule_canvas_run, temporal_client, uses_temporal


class LegacySqlAlchemyRunOperations:
    """Strangler adapter around persisted Run state and execution backends."""

    def __init__(
        self,
        session_factory: Callable[[], Session] = SessionLocal,
    ) -> None:
        self._session_factory = session_factory

    @staticmethod
    def _node_or_error(db: Session, node_run_id: str) -> NodeRunRecord:
        node = db.get(NodeRunRecord, node_run_id)
        if node is None:
            raise RunNotFoundError("node run not found")
        return node

    def create_experiment(self, command: CreateExperimentCommand) -> Any:
        with self._session_factory() as db:
            try:
                record = run_experiment(
                    db,
                    ExperimentRunRequest.model_validate(command.values),
                )
            except (ValueError, RuntimeError) as exc:
                raise RunValidationError(str(exc)) from exc
            return experiment_response(record)

    def list_costs(self, owner_id: str | None, limit: int, offset: int) -> list[dict[str, Any]]:
        from ...billing import list_costs
        with self._session_factory() as db:
            return list_costs(db, owner_id, limit, offset)

    async def start_canvas_run(self, command: StartCanvasRunCommand) -> Any:
        with self._session_factory() as db:
            payload = CanvasRunRequest.model_validate(command.values)
            try:
                run = create_canvas_run(db, payload)
            except (ValueError, RuntimeError) as exc:
                raise RunValidationError(str(exc)) from exc
            canvas = db.get(CanvasRecord, payload.canvas_id)
            if canvas:
                canvas.active_run_id = run.id
                canvas.updated_at = utc_now()
                db.commit()
            await schedule_canvas_run(
                run,
                list((run.graph_snapshot or {}).get("nodes") or []),
            )
            return canvas_run_response(run)

    def get_canvas_run(self, run_id: str) -> Any:
        with self._session_factory() as db:
            run = db.get(CanvasRunRecord, run_id)
            if run is None:
                raise RunNotFoundError("Canvas run not found")
            return canvas_run_response(run)

    async def cancel_canvas_run(self, run_id: str) -> Any:
        with self._session_factory() as db:
            run = db.get(CanvasRunRecord, run_id)
            if run is None:
                raise RunNotFoundError("Canvas run not found")
            if run.status in {NodeStatus.SUCCEEDED, NodeStatus.FAILED, NodeStatus.CANCELED}:
                return canvas_run_response(run)
            run.status = NodeStatus.CANCELED
            run.canceled_at = utc_now()
            for node in run.node_runs:
                if node.status not in {NodeStatus.SUCCEEDED, NodeStatus.FAILED}:
                    node.status = NodeStatus.CANCELED
            db.commit()
            if uses_temporal():
                client = await temporal_client()
                await client.get_workflow_handle(
                    f"frameflow/canvas/{run.id}"
                ).cancel()
            return canvas_run_response(run)

    async def select_canvas_candidate(
        self,
        command: SelectCanvasCandidateCommand,
    ) -> Any:
        with self._session_factory() as db:
            run = db.get(CanvasRunRecord, command.run_id)
            if run is None:
                raise RunNotFoundError("Canvas run not found")
            if uses_temporal():
                client = await temporal_client()
                handle = client.get_workflow_handle_for(
                    CanvasRunWorkflow.run,
                    f"frameflow/canvas/{run.id}",
                )
                await handle.signal(
                    CanvasRunWorkflow.candidate_selected,
                    args=[command.canvas_node_id, command.artifact_id],
                )
            else:
                try:
                    record_canvas_selection(
                        command.run_id,
                        command.canvas_node_id,
                        command.artifact_id,
                    )
                except ValueError as exc:
                    raise RunConflictError(str(exc)) from exc
                await get_local_canvas_engine().start(command.run_id)
            db.expire_all()
            refreshed = db.get(CanvasRunRecord, command.run_id)
            if refreshed is None:
                raise RunNotFoundError("Canvas run not found")
            return canvas_run_response(refreshed)

    async def approve_canvas_node(self, command: ApproveCanvasNodeCommand) -> Any:
        with self._session_factory() as db:
            run = db.get(CanvasRunRecord, command.run_id)
            if run is None:
                raise RunNotFoundError("Canvas run not found")
            if uses_temporal():
                client = await temporal_client()
                handle = client.get_workflow_handle_for(
                    CanvasRunWorkflow.run,
                    f"frameflow/canvas/{run.id}",
                )
                await handle.signal(
                    CanvasRunWorkflow.node_approved,
                    args=[command.canvas_node_id, command.parameters],
                )
            else:
                try:
                    record_canvas_approval(
                        command.run_id,
                        command.canvas_node_id,
                        command.parameters,
                    )
                except ValueError as exc:
                    raise RunConflictError(str(exc)) from exc
                await get_local_canvas_engine().start(command.run_id)
            db.expire_all()
            refreshed = db.get(CanvasRunRecord, command.run_id)
            if refreshed is None:
                raise RunNotFoundError("Canvas run not found")
            return canvas_run_response(refreshed)

    def list_experiments(
        self,
        canvas_id: str,
        node_id: str | None,
        limit: int,
    ) -> list[Any]:
        with self._session_factory() as db:
            query = select(ExperimentRunRecord).where(
                ExperimentRunRecord.canvas_id == canvas_id
            )
            if node_id:
                query = query.where(ExperimentRunRecord.node_id == node_id)
            rows = db.scalars(
                query.order_by(ExperimentRunRecord.created_at.desc()).limit(limit)
            ).all()
            return [experiment_response(row) for row in rows]

    def set_experiment_baseline(self, experiment_id: str) -> Any:
        with self._session_factory() as db:
            record = db.get(ExperimentRunRecord, experiment_id)
            if record is None:
                raise RunNotFoundError("experiment not found")
            require_successful_baseline(record.status)
            siblings = db.scalars(
                select(ExperimentRunRecord).where(
                    ExperimentRunRecord.canvas_id == record.canvas_id,
                    ExperimentRunRecord.node_id == record.node_id,
                    ExperimentRunRecord.is_baseline.is_(True),
                )
            ).all()
            for sibling in siblings:
                sibling.is_baseline = False
            record.is_baseline = True
            audit(db, "experiment.baseline_set", record.id)
            db.commit()
            db.refresh(record)
            return experiment_response(record)

    async def create_generation_run(
        self,
        command: CreateGenerationRunCommand,
    ) -> Any:
        with self._session_factory() as db:
            payload = GenerationRunRequest.model_validate(command.values)
            brief = db.get(GenerationBriefRecord, payload.brief_id)
            if brief is None:
                raise RunNotFoundError("generation brief not found")
            try:
                plan = compile_generation_plan(
                    brief.payload,
                    payload.workflow_definition_id,
                )
            except CompileError as exc:
                raise RunValidationError(str(exc)) from exc
            execution_plan = {
                **plan.payload,
                "brief_id": brief.id,
                "format_id": brief.format_id,
            }
            run = RunRecord(
                id=new_id("run"),
                name=brief.topic,
                status=NodeStatus.READY,
                progress=0,
                estimated_cost_usd=plan.estimated_cost_usd,
                actual_cost_usd=0,
                budget_limit_usd=brief.payload["budget_limit_usd"],
                execution_plan=execution_plan,
            )
            db.add(run)
            for ordinal, (node_key, _pool, _cost) in enumerate(DEFAULT_NODES):
                db.add(
                    NodeRunRecord(
                        id=new_id("node"),
                        run_id=run.id,
                        node_key=node_key,
                        ordinal=ordinal,
                        status=(
                            NodeStatus.READY if ordinal == 0 else NodeStatus.BLOCKED
                        ),
                        progress=0,
                        cost_usd=0,
                        attempt_count=0,
                        output_artifact_ids=[],
                    )
                )
            audit(
                db,
                "run.created",
                run.id,
                {"brief_id": brief.id, "dry_run": payload.dry_run},
            )
            db.commit()
            db.refresh(run)
            if not payload.dry_run:
                if uses_temporal():
                    client = await temporal_client()
                    await client.start_workflow(
                        GenerationRunWorkflow.run,
                        GenerationWorkflowInput(
                            run_id=run.id,
                            node_keys=[node[0] for node in DEFAULT_NODES],
                        ),
                        id=f"frameflow/{run.id}",
                        task_queue=TASK_QUEUE,
                    )
                else:
                    await local_engine.start(run.id)
            return run_response(run)

    def get_run(self, run_id: str) -> Any:
        with self._session_factory() as db:
            run = db.get(RunRecord, run_id)
            if run is None:
                raise RunNotFoundError("run not found")
            return run_response(run)

    def list_runs(self) -> list[Any]:
        with self._session_factory() as db:
            rows = db.scalars(
                select(RunRecord).order_by(RunRecord.created_at.desc())
            ).unique().all()
            return [run_response(row) for row in rows]

    async def cancel_run(self, run_id: str) -> Any:
        with self._session_factory() as db:
            run = db.get(RunRecord, run_id)
            if run is None:
                raise RunNotFoundError("run not found")
            run.status = NodeStatus.CANCELED
            run.canceled_at = utc_now()
            for node in run.node_runs:
                if node.status not in {NodeStatus.SUCCEEDED, NodeStatus.FAILED}:
                    node.status = NodeStatus.CANCELED
            audit(db, "run.canceled", run.id)
            db.commit()
            if uses_temporal():
                client = await temporal_client()
                await client.get_workflow_handle(f"frameflow/{run.id}").cancel()
            return run_response(run)

    def event_snapshot(self, run_id: str, offset: int) -> list[Any]:
        return broker.snapshot(run_id, offset)

    async def wait_for_event(self, run_id: str) -> None:
        await broker.wait(run_id)

    async def retry_node(self, node_run_id: str) -> dict[str, Any]:
        with self._session_factory() as db:
            node = self._node_or_error(db, node_run_id)
            node.status = NodeStatus.READY
            audit(db, "node.retry", node.id, {"attempt": node.attempt_count + 1})
            db.commit()
            run_id = node.run_id
            result = {
                "node_run_id": node.id,
                "status": node.status,
                "attempt_count": node.attempt_count,
            }
        await local_engine.start(run_id)
        return result

    def regenerate_node(self, command: RegenerateNodeCommand) -> dict[str, Any]:
        with self._session_factory() as db:
            node = self._node_or_error(db, command.node_run_id)
            payload = RegenerateRequest.model_validate(command.values)
            artifact = create_artifact(
                db,
                "RegenerationRequest",
                schema_id="regenerate.v1",
                producer_node_run_id=node.id,
                input_artifact_ids=node.output_artifact_ids,
                metadata=payload.model_dump(exclude_none=True),
            )
            node.status = NodeStatus.READY
            audit(
                db,
                "node.regenerate",
                node.id,
                payload.model_dump(exclude_none=True),
            )
            db.commit()
            return {
                "node_run_id": node.id,
                "request_artifact_id": artifact.id,
                "status": node.status,
            }

    def fork_node(self, node_run_id: str) -> dict[str, Any]:
        with self._session_factory() as db:
            node = self._node_or_error(db, node_run_id)
            source = db.get(RunRecord, node.run_id)
            if source is None:
                raise RunNotFoundError("source run not found")
            fork = RunRecord(
                id=new_id("run"),
                name=f"{source.name} · Fork",
                status=NodeStatus.READY,
                progress=source.progress,
                estimated_cost_usd=source.estimated_cost_usd,
                actual_cost_usd=source.actual_cost_usd,
                budget_limit_usd=source.budget_limit_usd,
                execution_plan={
                    **source.execution_plan,
                    "forked_from": source.id,
                    "forked_at_node": node.node_key,
                },
            )
            db.add(fork)
            for old in source.node_runs:
                reusable = (
                    old.ordinal < node.ordinal and old.status == NodeStatus.SUCCEEDED
                )
                db.add(
                    NodeRunRecord(
                        id=new_id("node"),
                        run_id=fork.id,
                        node_key=old.node_key,
                        ordinal=old.ordinal,
                        status=(
                            NodeStatus.SUCCEEDED if reusable else NodeStatus.STALE
                        ),
                        progress=100 if reusable else 0,
                        cost_usd=0,
                        attempt_count=0,
                        output_artifact_ids=(
                            old.output_artifact_ids if reusable else []
                        ),
                    )
                )
            audit(
                db,
                "run.forked",
                fork.id,
                {"source_run_id": source.id, "node_run_id": node.id},
            )
            db.commit()
            return {
                "run_id": fork.id,
                "source_run_id": source.id,
                "forked_at": node.node_key,
            }

    async def select_generation_candidate(
        self,
        command: SelectGenerationCandidateCommand,
    ) -> dict[str, Any]:
        with self._session_factory() as db:
            node = self._node_or_error(db, command.node_run_id)
            run_id = node.run_id
        if uses_temporal():
            client = await temporal_client()
            handle = client.get_workflow_handle_for(
                GenerationRunWorkflow.run,
                f"frameflow/{run_id}",
            )
            await handle.signal(
                GenerationRunWorkflow.candidate_selected,
                command.artifact_id,
            )
            return {
                "node_run_id": command.node_run_id,
                "selected_artifact_id": command.artifact_id,
                "status": NodeStatus.WAITING_INPUT,
                "signal_accepted": True,
            }
        try:
            await local_engine.resume_after_selection(
                run_id,
                command.node_run_id,
                command.artifact_id,
            )
        except (ValueError, RuntimeError) as exc:
            raise RunConflictError(str(exc)) from exc
        return {
            "node_run_id": command.node_run_id,
            "selected_artifact_id": command.artifact_id,
            "status": NodeStatus.SUCCEEDED,
        }
