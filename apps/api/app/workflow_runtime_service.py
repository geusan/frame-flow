from __future__ import annotations

import os
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session
from temporalio.client import Client

from .canvas_runs import (
    canvas_dependencies,
    canvas_run_response,
    create_canvas_run,
    local_canvas_engine,
    record_canvas_approval,
    record_canvas_selection,
)
from .canvas_temporal import CanvasRunWorkflow, CanvasWorkflowInput
from .database import (
    ArtifactRecord,
    CanvasNodeRunRecord,
    CanvasRunRecord,
    WorkflowDefinitionRecord,
    WorkflowVersionRecord,
)
from .domain import NodeStatus, WorkflowVersionRunRequest, utc_now
from .nodes import node_registry
from .service import audit
from .temporal_runtime import TASK_QUEUE
from .workflow_definitions import (
    WORKFLOW_COMPILER_VERSION,
    WorkflowContractError,
    resolve_workflow_execution,
)


TERMINAL_STATUSES = {NodeStatus.SUCCEEDED, NodeStatus.FAILED, NodeStatus.CANCELED}


def uses_temporal() -> bool:
    return os.getenv("EXECUTION_BACKEND", "local").lower() == "temporal"


async def temporal_client() -> Client:
    return await Client.connect(
        os.getenv("TEMPORAL_ADDRESS", "localhost:7233"),
        namespace=os.getenv("TEMPORAL_NAMESPACE", "default"),
    )


async def schedule_canvas_run(run: CanvasRunRecord, nodes: list[dict[str, Any]]) -> None:
    if uses_temporal():
        dependencies = canvas_dependencies(run)
        node_keys = {
            str(node.get("id")): str((node.get("data") or {}).get("key") or "unknown")
            for node in nodes
        }
        completed = [node.canvas_node_id for node in run.node_runs if node.status == NodeStatus.SUCCEEDED]
        approval_node_ids = [
            str(node.get("id"))
            for node in nodes
            if (node.get("data") or {}).get("waitForInput") is True
        ]
        client = await temporal_client()
        await client.start_workflow(
            CanvasRunWorkflow.run,
            CanvasWorkflowInput(
                run.id,
                list(node_keys),
                node_keys,
                dependencies,
                completed,
                approval_node_ids,
            ),
            id=f"frameflow/canvas/{run.id}",
            task_queue=TASK_QUEUE,
        )
    else:
        await local_canvas_engine.start(run.id)


def _workflow_version(
    db: Session,
    definition: WorkflowDefinitionRecord,
    version_number: int | None,
) -> WorkflowVersionRecord:
    if version_number is not None:
        version = db.scalar(
            select(WorkflowVersionRecord).where(
                WorkflowVersionRecord.workflow_definition_id == definition.id,
                WorkflowVersionRecord.version_number == version_number,
            )
        )
    else:
        version = db.get(WorkflowVersionRecord, definition.current_version_id) if definition.current_version_id else None
    if version is None:
        requested = f" v{version_number}" if version_number is not None else ""
        raise WorkflowContractError(f"Workflow{requested} has no published Version")
    return version


async def start_published_workflow_run(
    db: Session,
    *,
    workflow_id: str,
    version_number: int | None,
    inputs: dict[str, Any],
    actor_id: str = "local-mcp",
) -> CanvasRunRecord:
    definition = db.get(WorkflowDefinitionRecord, workflow_id)
    if definition is None:
        raise WorkflowContractError("Workflow was not found")
    if definition.status != "ACTIVE":
        raise WorkflowContractError("Archived Workflow cannot be run")
    version = _workflow_version(db, definition, version_number)
    request = WorkflowVersionRunRequest(version=version.version_number, inputs=inputs)
    run_payload, resolved_inputs, model_snapshot = resolve_workflow_execution(
        db,
        definition,
        version,
        request,
    )
    run = create_canvas_run(db, run_payload)
    run.source_type = "WORKFLOW_VERSION"
    run.workflow_definition_id = definition.id
    run.workflow_version_id = version.id
    run.input_snapshot = resolved_inputs
    run.model_snapshot = model_snapshot
    run.compiler_version = WORKFLOW_COMPILER_VERSION
    audit(db, "workflow.run_created_by_mcp", run.id, {
        "actor_id": actor_id,
        "workflow_definition_id": definition.id,
        "workflow_version_id": version.id,
        "version_number": version.version_number,
    })
    db.commit()
    db.refresh(run)
    await schedule_canvas_run(run, run_payload.nodes)
    return run


def _graph_node(run: CanvasRunRecord, canvas_node_id: str) -> dict[str, Any]:
    return next(
        (
            node
            for node in (run.graph_snapshot or {}).get("nodes", [])
            if str(node.get("id")) == canvas_node_id
        ),
        {},
    )


def _artifact_payload(artifact: ArtifactRecord | None, artifact_id: str) -> dict[str, Any]:
    if artifact is None:
        return {
            "artifact_id": artifact_id,
            "resource_uri": f"frameflow://artifacts/{artifact_id}",
        }
    storage = dict((artifact.metadata_json or {}).get("storage") or {})
    return {
        "artifact_id": artifact.id,
        "type": artifact.type,
        "schema_id": artifact.schema_id,
        "sha256": artifact.sha256,
        "filename": str(
            (artifact.metadata_json or {}).get("filename")
            or ((artifact.metadata_json or {}).get("output") or {}).get("title")
            or artifact.id
        ),
        "content_type": str(storage.get("content_type") or "application/octet-stream"),
        "size_bytes": int(storage.get("size_bytes") or 0),
        "duration_ms": int((artifact.metadata_json or {}).get("duration_ms") or 0),
        "resource_uri": f"frameflow://artifacts/{artifact.id}",
    }


def workflow_run_payload(db: Session, run: CanvasRunRecord) -> dict[str, Any]:
    version = db.get(WorkflowVersionRecord, run.workflow_version_id) if run.workflow_version_id else None
    definition = db.get(WorkflowDefinitionRecord, run.workflow_definition_id) if run.workflow_definition_id else None
    node_runs = {node.canvas_node_id: node for node in run.node_runs}
    artifact_ids = {
        artifact_id
        for node in run.node_runs
        for artifact_id in (node.output_artifact_ids or [])
    }
    artifacts = {
        artifact.id: artifact
        for artifact in db.scalars(
            select(ArtifactRecord).where(ArtifactRecord.id.in_(artifact_ids))
        ).all()
    } if artifact_ids else {}

    outputs: dict[str, Any] = {}
    for output in ((version.output_schema_json or {}).get("outputs") or []) if version else []:
        node_id = str(output.get("node_id") or "")
        node_run = node_runs.get(node_id)
        output_artifacts = list(node_run.output_artifact_ids or []) if node_run else []
        outputs[str(output.get("key") or node_id)] = {
            "label": str(output.get("label") or output.get("key") or node_id),
            "primary": output.get("primary") is True,
            "port_key": output.get("port_key"),
            "port_type": output.get("port_type"),
            "status": str(node_run.status) if node_run else "PENDING",
            "artifacts": [
                _artifact_payload(artifacts.get(artifact_id), artifact_id)
                for artifact_id in output_artifacts
            ],
        }

    dependencies = canvas_dependencies(run)
    required_actions: list[dict[str, Any]] = []
    for node_run in run.node_runs:
        if node_run.status != NodeStatus.WAITING_INPUT:
            continue
        graph_node = _graph_node(run, node_run.canvas_node_id)
        data = dict(graph_node.get("data") or {})
        contract_version = int(data.get("contractVersion") or 1)
        node_definition = node_registry.get(node_run.node_key, contract_version)
        approval_schema = node_definition.execution.approval_schema if node_definition else None
        is_approval = data.get("waitForInput") is True
        action: dict[str, Any] = {
            "node_id": node_run.canvas_node_id,
            "type_key": node_run.node_key,
            "contract_version": contract_version,
            "kind": "approve" if is_approval else "select_artifact",
        }
        if is_approval:
            action["schema"] = approval_schema or {
                "type": "object",
                "additionalProperties": True,
            }
        else:
            candidate_ids: list[str] = []
            for source_id in dependencies.get(node_run.canvas_node_id, []):
                source_run = node_runs.get(source_id)
                if source_run is not None:
                    candidate_ids.extend(source_run.output_artifact_ids or [])
            action["candidates"] = [
                _artifact_payload(artifacts.get(artifact_id), artifact_id)
                for artifact_id in candidate_ids
            ]
        required_actions.append(action)

    response = canvas_run_response(run)
    return {
        "run_id": run.id,
        "resource_uri": f"frameflow://runs/{run.id}",
        "workflow_id": run.workflow_definition_id,
        "workflow_name": definition.name if definition else None,
        "workflow_version": version.version_number if version else None,
        "status": str(run.status),
        "progress": run.progress,
        "inputs": run.input_snapshot or {},
        "cost_usd": sum(node.cost_usd for node in run.node_runs),
        "required_actions": required_actions,
        "outputs": outputs,
        "node_runs": [
            {
                "node_id": node.canvas_node_id,
                "type_key": node.node_key,
                "status": str(node.status),
                "progress": node.progress,
                "attempt_count": node.attempt_count,
                "cost_usd": node.cost_usd,
                "duration_ms": node.duration_ms,
                "error": node.error,
                "artifact_ids": list(node.output_artifact_ids or []),
            }
            for node in response.node_runs
        ],
        "created_at": run.created_at.isoformat(),
        "poll_after_ms": 2_000 if run.status not in TERMINAL_STATUSES else None,
    }


async def cancel_workflow_run(db: Session, run_id: str) -> CanvasRunRecord:
    run = db.get(CanvasRunRecord, run_id)
    if run is None or run.source_type != "WORKFLOW_VERSION":
        raise ValueError("Workflow Run was not found")
    if run.status in TERMINAL_STATUSES:
        return run
    run.status = NodeStatus.CANCELED
    run.canceled_at = utc_now()
    for node in run.node_runs:
        if node.status not in {NodeStatus.SUCCEEDED, NodeStatus.FAILED}:
            node.status = NodeStatus.CANCELED
    audit(db, "workflow.run_canceled_by_mcp", run.id)
    db.commit()
    if uses_temporal():
        client = await temporal_client()
        await client.get_workflow_handle(f"frameflow/canvas/{run.id}").cancel()
    db.refresh(run)
    return run


async def respond_to_workflow_run(
    db: Session,
    *,
    run_id: str,
    node_id: str,
    action: Literal["approve", "select_artifact"],
    parameters: dict[str, Any] | None = None,
    artifact_id: str | None = None,
) -> CanvasRunRecord:
    run = db.get(CanvasRunRecord, run_id)
    if run is None or run.source_type != "WORKFLOW_VERSION":
        raise ValueError("Workflow Run was not found")
    node_run = db.scalar(
        select(CanvasNodeRunRecord).where(
            CanvasNodeRunRecord.run_id == run_id,
            CanvasNodeRunRecord.canvas_node_id == node_id,
        )
    )
    if node_run is None or node_run.status != NodeStatus.WAITING_INPUT:
        raise ValueError("Workflow Node is not waiting for input")
    graph_node = _graph_node(run, node_id)
    data = dict(graph_node.get("data") or {})
    expects_approval = data.get("waitForInput") is True
    if expects_approval and action != "approve":
        raise ValueError("Workflow Node requires approval parameters")
    if not expects_approval and action != "select_artifact":
        raise ValueError("Workflow Node requires candidate Artifact selection")
    if action == "approve":
        approval_parameters = parameters or {}
        if uses_temporal():
            client = await temporal_client()
            handle = client.get_workflow_handle_for(CanvasRunWorkflow.run, f"frameflow/canvas/{run.id}")
            await handle.signal(CanvasRunWorkflow.node_approved, node_id, approval_parameters)
        else:
            record_canvas_approval(run_id, node_id, approval_parameters)
            await local_canvas_engine.start(run_id)
    else:
        if not artifact_id:
            raise ValueError("artifact_id is required for candidate selection")
        if uses_temporal():
            client = await temporal_client()
            handle = client.get_workflow_handle_for(CanvasRunWorkflow.run, f"frameflow/canvas/{run.id}")
            await handle.signal(CanvasRunWorkflow.candidate_selected, node_id, artifact_id)
        else:
            record_canvas_selection(run_id, node_id, artifact_id)
            await local_canvas_engine.start(run_id)
    db.expire_all()
    refreshed = db.get(CanvasRunRecord, run_id)
    if refreshed is None:
        raise ValueError("Workflow Run was not found")
    return refreshed
