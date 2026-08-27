from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy


@dataclass
class GenerationWorkflowInput:
    run_id: str
    node_keys: list[str]


@dataclass
class WorkflowState:
    run_id: str
    current_node_key: str | None
    completed_node_keys: list[str]
    waiting_for_selection: bool
    selected_artifact_id: str | None


@workflow.defn(name="frameflow.generation.v1")
class GenerationRunWorkflow:
    def __init__(self) -> None:
        self.run_id = ""
        self.current_node_key: str | None = None
        self.completed_node_keys: list[str] = []
        self.waiting_for_selection = False
        self.selected_artifact_id: str | None = None

    @workflow.run
    async def run(self, payload: GenerationWorkflowInput) -> dict[str, Any]:
        self.run_id = payload.run_id
        retry_policy = RetryPolicy(
            initial_interval=timedelta(seconds=2),
            backoff_coefficient=2,
            maximum_interval=timedelta(minutes=2),
            maximum_attempts=5,
            non_retryable_error_types=["RightsPolicyViolation", "BudgetExceeded", "SchemaValidationError"],
        )
        for node_key in payload.node_keys:
            self.current_node_key = node_key
            if node_key == "candidate.select":
                self.waiting_for_selection = True
                await workflow.execute_activity(
                    "mark_waiting_input",
                    args=[payload.run_id, node_key],
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=retry_policy,
                )
                await workflow.wait_condition(lambda: self.selected_artifact_id is not None)
                await workflow.execute_activity(
                    "record_candidate_selection",
                    args=[payload.run_id, node_key, self.selected_artifact_id],
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=retry_policy,
                )
                self.waiting_for_selection = False
            else:
                await workflow.execute_activity(
                    "execute_node",
                    args=[payload.run_id, node_key],
                    start_to_close_timeout=timedelta(minutes=30),
                    heartbeat_timeout=timedelta(minutes=1),
                    retry_policy=retry_policy,
                    cancellation_type=workflow.ActivityCancellationType.WAIT_CANCELLATION_COMPLETED,
                )
            self.completed_node_keys.append(node_key)
        self.current_node_key = None
        await workflow.execute_activity(
            "finalize_run",
            payload.run_id,
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=retry_policy,
        )
        return {"run_id": payload.run_id, "status": "SUCCEEDED", "completed_node_keys": self.completed_node_keys}

    @workflow.signal(name="candidate_selected")
    def candidate_selected(self, artifact_id: str) -> None:
        if self.waiting_for_selection:
            self.selected_artifact_id = artifact_id

    @workflow.query(name="state")
    def state(self) -> WorkflowState:
        return WorkflowState(
            run_id=self.run_id,
            current_node_key=self.current_node_key,
            completed_node_keys=list(self.completed_node_keys),
            waiting_for_selection=self.waiting_for_selection,
            selected_artifact_id=self.selected_artifact_id,
        )

