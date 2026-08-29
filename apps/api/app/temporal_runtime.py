from __future__ import annotations

import asyncio
import os

from temporalio.client import Client
from temporalio.worker import Worker

from .database import create_all
from .provider_settings import refresh_provider_environment
from .canvas_activities import execute_canvas_node_activity, finalize_canvas_run_activity, mark_canvas_waiting_activity, record_canvas_approval_activity, record_canvas_selection_activity
from .canvas_temporal import CanvasRunWorkflow
from .temporal_activities import execute_node, finalize_run, mark_waiting_input, record_candidate_selection
from .temporal_workflow import GenerationRunWorkflow


TASK_QUEUE = os.getenv("TEMPORAL_TASK_QUEUE", "frameflow-generation-v1")


async def run_worker() -> None:
    create_all()
    refresh_provider_environment()
    retry_seconds = float(os.getenv("TEMPORAL_CONNECT_RETRY_SECONDS", "2"))
    while True:
        try:
            client = await Client.connect(
                os.getenv("TEMPORAL_ADDRESS", "localhost:7233"),
                namespace=os.getenv("TEMPORAL_NAMESPACE", "default"),
            )
            worker = Worker(
                client,
                task_queue=TASK_QUEUE,
                workflows=[GenerationRunWorkflow, CanvasRunWorkflow],
                activities=[execute_node, mark_waiting_input, record_candidate_selection, finalize_run, execute_canvas_node_activity, mark_canvas_waiting_activity, record_canvas_selection_activity, record_canvas_approval_activity, finalize_canvas_run_activity],
                max_concurrent_activities=int(os.getenv("TEMPORAL_MAX_CONCURRENT_ACTIVITIES", "32")),
            )
            await worker.run()
            return
        except (ConnectionError, RuntimeError) as exc:
            print(f"Temporal is not ready ({exc}); retrying in {retry_seconds:g}s", flush=True)
            await asyncio.sleep(retry_seconds)


if __name__ == "__main__":
    asyncio.run(run_worker())
