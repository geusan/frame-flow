from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy


@dataclass
class CanvasWorkflowInput:
    run_id: str
    node_ids: list[str]
    node_keys: dict[str, str]
    dependencies: dict[str, list[str]]
    completed_node_ids: list[str]


@workflow.defn(name="frameflow.canvas.v1")
class CanvasRunWorkflow:
    def __init__(self) -> None:
        self.waiting_node_id: str | None = None
        self.selected_artifact_id: str | None = None

    @workflow.run
    async def run(self, payload: CanvasWorkflowInput) -> dict[str, object]:
        completed = set(payload.completed_node_ids)
        remaining = set(payload.node_ids) - completed
        retry = RetryPolicy(initial_interval=timedelta(seconds=2), maximum_interval=timedelta(minutes=1), maximum_attempts=3)
        while remaining:
            ready = sorted(node_id for node_id in remaining if set(payload.dependencies.get(node_id, [])) <= completed)
            if not ready:
                raise RuntimeError("Canvas DAG cannot make progress")
            candidates = [node_id for node_id in ready if payload.node_keys[node_id] == "candidate.select"]
            executable = [node_id for node_id in ready if payload.node_keys[node_id] != "candidate.select"]
            if executable:
                await asyncio.gather(*[
                    workflow.execute_activity(
                        "execute_canvas_node",
                        args=[payload.run_id, node_id],
                        start_to_close_timeout=timedelta(minutes=30),
                        heartbeat_timeout=timedelta(minutes=1),
                        retry_policy=retry,
                        cancellation_type=workflow.ActivityCancellationType.WAIT_CANCELLATION_COMPLETED,
                    ) for node_id in executable
                ])
                completed.update(executable)
                remaining.difference_update(executable)
            for node_id in candidates:
                self.waiting_node_id = node_id
                self.selected_artifact_id = None
                await workflow.execute_activity(
                    "mark_canvas_waiting",
                    args=[payload.run_id, node_id],
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=retry,
                )
                await workflow.wait_condition(lambda: self.selected_artifact_id is not None)
                await workflow.execute_activity(
                    "record_canvas_selection",
                    args=[payload.run_id, node_id, self.selected_artifact_id],
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=retry,
                )
                completed.add(node_id)
                remaining.remove(node_id)
                self.waiting_node_id = None
        await workflow.execute_activity(
            "finalize_canvas_run",
            payload.run_id,
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=retry,
        )
        return {"run_id": payload.run_id, "status": "SUCCEEDED", "completed_node_ids": sorted(completed)}

    @workflow.signal(name="canvas_candidate_selected")
    def candidate_selected(self, canvas_node_id: str, artifact_id: str) -> None:
        if self.waiting_node_id == canvas_node_id:
            self.selected_artifact_id = artifact_id
