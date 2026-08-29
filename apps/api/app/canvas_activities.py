from __future__ import annotations

import asyncio
from typing import Any

from temporalio import activity

from .canvas_runs import execute_canvas_node, finalize_canvas_run, mark_canvas_waiting, record_canvas_approval, record_canvas_selection
from .provider_settings import refresh_provider_environment


@activity.defn(name="execute_canvas_node")
async def execute_canvas_node_activity(run_id: str, canvas_node_id: str) -> dict[str, Any]:
    refresh_provider_environment()
    task = asyncio.create_task(asyncio.to_thread(execute_canvas_node, run_id, canvas_node_id))
    while not task.done():
        activity.heartbeat({"canvas_node_id": canvas_node_id, "stage": "executing"})
        done, _ = await asyncio.wait({task}, timeout=20)
        if done:
            break
    return await task


@activity.defn(name="mark_canvas_waiting")
async def mark_canvas_waiting_activity(run_id: str, canvas_node_id: str) -> None:
    mark_canvas_waiting(run_id, canvas_node_id)


@activity.defn(name="record_canvas_selection")
async def record_canvas_selection_activity(run_id: str, canvas_node_id: str, artifact_id: str) -> None:
    record_canvas_selection(run_id, canvas_node_id, artifact_id)


@activity.defn(name="record_canvas_approval")
async def record_canvas_approval_activity(run_id: str, canvas_node_id: str, parameters: dict[str, Any]) -> None:
    record_canvas_approval(run_id, canvas_node_id, parameters)


@activity.defn(name="finalize_canvas_run")
async def finalize_canvas_run_activity(run_id: str) -> None:
    finalize_canvas_run(run_id)
