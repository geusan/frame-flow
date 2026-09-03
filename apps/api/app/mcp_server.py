from __future__ import annotations

import argparse
import json
import os
from contextlib import asynccontextmanager
from datetime import date, datetime
from typing import Any, AsyncIterator, Literal

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ResourceError, ToolError
from mcp.types import ToolAnnotations
from sqlalchemy import select
from sqlalchemy.orm import Session

from .artifact_lineage import artifact_lineage_graph
from .database import (
    ArtifactRecord,
    CanvasRecord,
    CanvasRunRecord,
    SessionLocal,
    WorkflowDefinitionRecord,
    WorkflowVersionRecord,
    create_all,
)
from .nodes import node_registry
from .nodes.contracts import NodeDefinition
from .project_skills import ensure_bundled_skills, list_project_skills
from .provider_settings import apply_provider_settings_to_environment, ensure_provider_settings
from .providers import ALL_MODEL_REGISTRY
from .service import backfill_artifact_edges
from .storage import artifact_content_url, get_storage
from .workflow_authoring import (
    WorkflowAuthoringSpec,
    create_workflow_draft,
    prepare_workflow_draft,
    update_workflow_draft,
    workflow_draft_payload,
)
from .workflow_definitions import (
    WorkflowContractError,
    WorkflowPublishRequest,
    compile_canvas_version,
    publish_workflow_version,
    workflow_definition_payload,
    workflow_version_payload,
)
from .workflow_runtime_service import (
    cancel_workflow_run,
    respond_to_workflow_run,
    start_published_workflow_run,
    workflow_run_payload,
)


READ_ONLY = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)
ADDITIVE_WRITE = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=False,
    idempotent_hint=False,
    open_world_hint=False,
)
OPEN_WORLD_WRITE = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=False,
    idempotent_hint=False,
    open_world_hint=True,
)
IDEMPOTENT_WRITE = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)


@asynccontextmanager
async def mcp_lifespan(_: MCPServer[Any]) -> AsyncIterator[dict[str, Any]]:
    create_all()
    with SessionLocal() as settings_db:
        apply_provider_settings_to_environment(ensure_provider_settings(settings_db))
    with SessionLocal() as skill_db:
        ensure_bundled_skills(skill_db)
    get_storage().initialize()
    with SessionLocal() as lineage_db:
        if backfill_artifact_edges(lineage_db):
            lineage_db.commit()
    yield {}


server = MCPServer(
    name="frameflow",
    title="Frameflow Workflow Server",
    description="Build, publish, run, and inspect versioned Frameflow video workflows.",
    instructions=(
        "Discover Node contracts before authoring. Create a Draft with "
        "frameflow.workflow_drafts.plan and frameflow.workflow_drafts.create, "
        "validate it, then publish an immutable WorkflowVersion. Never invent Node "
        "types, config fields, ports, or workflow-input bindings."
    ),
    version="0.1.0",
    lifespan=mcp_lifespan,
)


def _json_default(value: Any) -> str:
    if isinstance(value, datetime | date):
        return value.isoformat()
    return str(value)


def _json_resource(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=_json_default)


def _tool_failure(exc: Exception) -> ToolError:
    return ToolError(str(exc))


def _definition_for(type_key: str, contract_version: int | None) -> NodeDefinition:
    if contract_version is not None:
        definition = node_registry.get(type_key, contract_version)
    else:
        matches = [item for item in node_registry.list() if item.type_key == type_key]
        definition = max(matches, key=lambda item: item.contract_version) if matches else None
    if definition is None:
        suffix = f"@{contract_version}" if contract_version is not None else ""
        raise ValueError(f"Node Definition was not found: {type_key}{suffix}")
    return definition


def _node_contract_summary(definition: NodeDefinition) -> dict[str, Any]:
    workflow_fields = []
    for name, field in (definition.config_schema.get("properties") or {}).items():
        exposure = field.get("x-workflow-input") or {}
        if exposure.get("enabled"):
            workflow_fields.append({
                "field": name,
                "workflow_input_type": exposure.get("type"),
                "title": field.get("title"),
                "required": name in definition.config_schema.get("required", []),
            })
    return {
        "type_key": definition.type_key,
        "contract_version": definition.contract_version,
        "definition_digest": definition.definition_digest,
        "lifecycle": definition.lifecycle,
        "label": definition.display.label,
        "description": definition.display.description,
        "category": definition.display.category,
        "execution_kind": definition.execution.kind,
        "input_ports": [port.model_dump(mode="json") for port in definition.ports.inputs],
        "output_ports": [port.model_dump(mode="json") for port in definition.ports.outputs],
        "workflow_input_fields": workflow_fields,
    }


@server.tool(
    name="frameflow.node_contracts.list",
    title="List Frameflow Node contracts",
    annotations=READ_ONLY,
    structured_output=True,
)
def list_node_contracts(
    query: str | None = None,
    lifecycle: Literal["ACTIVE", "DEPRECATED", "RETIRED", "BLOCKED", "ALL"] = "ACTIVE",
    limit: int = 100,
) -> dict[str, Any]:
    """List versioned Node contracts. Search matches type key, label, description, and keywords."""
    if limit < 1 or limit > 500:
        raise ToolError("limit must be between 1 and 500")
    needle = (query or "").strip().lower()
    matches = []
    for definition in node_registry.list(lifecycle=None if lifecycle == "ALL" else lifecycle):
        haystack = " ".join([
            definition.type_key,
            definition.display.label,
            definition.display.description,
            *definition.display.keywords,
        ]).lower()
        if not needle or needle in haystack:
            matches.append(_node_contract_summary(definition))
    return {"contracts": matches[:limit], "count": min(len(matches), limit), "total": len(matches)}


@server.tool(
    name="frameflow.node_contracts.get",
    title="Get a Frameflow Node contract",
    annotations=READ_ONLY,
    structured_output=True,
)
def get_node_contract(type_key: str, contract_version: int | None = None) -> dict[str, Any]:
    """Get the immutable Manifest for an exact Node contract, or its latest registered version."""
    try:
        definition = _definition_for(type_key, contract_version)
    except ValueError as exc:
        raise _tool_failure(exc) from exc
    return definition.public_payload()


@server.tool(
    name="frameflow.models.list",
    title="List Frameflow model aliases",
    annotations=READ_ONLY,
    structured_output=True,
)
def list_model_aliases(
    type_key: str | None = None,
    contract_version: int | None = None,
) -> dict[str, Any]:
    """List logical model aliases, optionally restricted to one Node contract's capability families."""
    try:
        definition = _definition_for(type_key, contract_version) if type_key else None
    except ValueError as exc:
        raise _tool_failure(exc) from exc
    families = definition.execution.model_families if definition else []
    aliases = [
        alias
        for alias in sorted(ALL_MODEL_REGISTRY)
        if not families or any(alias.startswith(prefix) for prefix in families)
    ]
    if definition and not families:
        aliases = [definition.execution.model_alias]
    return {
        "models": [
            {
                "logical_alias": alias,
                "provider": alias.split(".", 1)[0],
                "capability": alias.split(".", 2)[1] if "." in alias else "unknown",
            }
            for alias in aliases
        ],
        "node_contract": (
            f"{definition.type_key}@{definition.contract_version}" if definition else None
        ),
        "count": len(aliases),
    }


@server.tool(
    name="frameflow.skills.list",
    title="List Frameflow project skills",
    annotations=READ_ONLY,
    structured_output=True,
)
def list_skills(include_disabled: bool = False) -> dict[str, Any]:
    """List registered Skill versions that can be referenced by skill.execute Nodes."""
    with SessionLocal() as db:
        skills = list_project_skills(db, include_disabled=include_disabled)
        return {
            "skills": [skill.public_payload() for skill in skills],
            "count": len(skills),
        }


def _plan_payload(prepared: Any) -> dict[str, Any]:
    return {
        "valid": True,
        "content_hash": prepared.compiled.content_hash,
        "resolved_nodes": prepared.resolved_nodes,
        "graph": prepared.compiled.graph,
        "input_schema": prepared.compiled.input_schema,
        "output_schema": prepared.compiled.output_schema,
        "warnings": prepared.compiled.warnings,
    }


@server.tool(
    name="frameflow.workflow_drafts.plan",
    title="Plan a Frameflow Workflow Draft",
    annotations=READ_ONLY,
    structured_output=True,
)
def plan_workflow_draft(spec: WorkflowAuthoringSpec) -> dict[str, Any]:
    """Validate and normalize a declarative Workflow without writing data."""
    try:
        with SessionLocal() as db:
            return _plan_payload(prepare_workflow_draft(db, spec))
    except (ValueError, WorkflowContractError) as exc:
        raise _tool_failure(exc) from exc


@server.tool(
    name="frameflow.workflow_drafts.create",
    title="Create a Frameflow Workflow Draft",
    annotations=ADDITIVE_WRITE,
    structured_output=True,
)
def create_mcp_workflow_draft(spec: WorkflowAuthoringSpec) -> dict[str, Any]:
    """Create an editable Canonical Canvas Draft from a validated declarative Workflow."""
    try:
        with SessionLocal() as db:
            definition, canvas, prepared = create_workflow_draft(db, spec)
            return {
                "workflow_id": definition.id,
                "draft_canvas_id": canvas.id,
                "revision": canvas.revision,
                "status": "DRAFT",
                "content_hash": prepared.compiled.content_hash,
                "resolved_nodes": prepared.resolved_nodes,
                "warnings": prepared.compiled.warnings,
                "resource_uri": f"frameflow://workflows/{definition.id}",
            }
    except (ValueError, WorkflowContractError) as exc:
        raise _tool_failure(exc) from exc


@server.tool(
    name="frameflow.workflow_drafts.get",
    title="Get a Frameflow Workflow Draft",
    annotations=READ_ONLY,
    structured_output=True,
)
def get_workflow_draft(workflow_id: str) -> dict[str, Any]:
    """Get the active Draft as a reusable declarative authoring Spec."""
    try:
        with SessionLocal() as db:
            definition = db.get(WorkflowDefinitionRecord, workflow_id)
            if definition is None:
                raise ValueError("Workflow was not found")
            canvas = db.get(CanvasRecord, definition.draft_canvas_id)
            if canvas is None:
                raise ValueError("Workflow Draft Canvas is missing")
            return workflow_draft_payload(definition, canvas)
    except ValueError as exc:
        raise _tool_failure(exc) from exc


@server.tool(
    name="frameflow.workflow_drafts.update",
    title="Update a Frameflow Workflow Draft",
    annotations=ADDITIVE_WRITE,
    structured_output=True,
)
def update_mcp_workflow_draft(
    workflow_id: str,
    expected_revision: int,
    spec: WorkflowAuthoringSpec,
) -> dict[str, Any]:
    """Replace an editable Draft with a fully validated declarative Spec using optimistic revision control."""
    try:
        with SessionLocal() as db:
            definition, canvas, prepared, changed = update_workflow_draft(
                db,
                workflow_id=workflow_id,
                expected_revision=expected_revision,
                spec=spec,
            )
            return {
                **workflow_draft_payload(definition, canvas),
                "changed": changed,
                "content_hash": prepared.compiled.content_hash,
                "warnings": prepared.compiled.warnings,
            }
    except (ValueError, WorkflowContractError) as exc:
        raise _tool_failure(exc) from exc


@server.tool(
    name="frameflow.workflow_drafts.validate",
    title="Validate a Frameflow Workflow Draft",
    annotations=READ_ONLY,
    structured_output=True,
)
def validate_workflow_draft(workflow_id: str) -> dict[str, Any]:
    """Compile the active Draft without publishing and report its immutable content hash and warnings."""
    try:
        with SessionLocal() as db:
            definition = db.get(WorkflowDefinitionRecord, workflow_id)
            if definition is None:
                raise ValueError("Workflow was not found")
            canvas = db.get(CanvasRecord, definition.draft_canvas_id)
            if canvas is None:
                raise ValueError("Workflow Draft Canvas is missing")
            compiled = compile_canvas_version(db, canvas)
            return {
                "valid": True,
                "workflow_id": workflow_id,
                "draft_canvas_id": canvas.id,
                "revision": canvas.revision,
                "content_hash": compiled.content_hash,
                "node_count": len(compiled.graph.get("nodes") or []),
                "edge_count": len(compiled.graph.get("edges") or []),
                "warnings": compiled.warnings,
            }
    except (ValueError, WorkflowContractError) as exc:
        raise _tool_failure(exc) from exc


@server.tool(
    name="frameflow.workflow_drafts.publish",
    title="Publish a Frameflow Workflow Draft",
    annotations=IDEMPOTENT_WRITE,
    structured_output=True,
)
def publish_mcp_workflow_draft(
    workflow_id: str,
    expected_revision: int,
    release_notes: str = "",
) -> dict[str, Any]:
    """Publish an exact Draft revision as a new immutable WorkflowVersion."""
    try:
        with SessionLocal() as db:
            version, warnings = publish_workflow_version(
                db,
                workflow_id,
                WorkflowPublishRequest(
                    expected_canvas_revision=expected_revision,
                    release_notes=release_notes,
                    published_by="local-mcp",
                ),
            )
            return {
                **workflow_version_payload(version),
                "warnings": warnings,
                "resource_uri": (
                    f"frameflow://workflows/{workflow_id}/versions/{version.version_number}"
                ),
            }
    except (ValueError, WorkflowContractError) as exc:
        raise _tool_failure(exc) from exc


@server.tool(
    name="frameflow.workflows.list",
    title="List Frameflow Workflows",
    annotations=READ_ONLY,
    structured_output=True,
)
def list_workflows(
    status: Literal["ACTIVE", "ARCHIVED", "ALL"] = "ACTIVE",
    limit: int = 100,
) -> dict[str, Any]:
    """List Workflow Definitions and their current published versions."""
    if limit < 1 or limit > 500:
        raise ToolError("limit must be between 1 and 500")
    with SessionLocal() as db:
        query = select(WorkflowDefinitionRecord)
        if status != "ALL":
            query = query.where(WorkflowDefinitionRecord.status == status)
        records = db.scalars(query.order_by(WorkflowDefinitionRecord.updated_at.desc()).limit(limit)).all()
        return {
            "workflows": [workflow_definition_payload(record, db) for record in records],
            "count": len(records),
        }


@server.tool(
    name="frameflow.workflows.get",
    title="Get a Frameflow Workflow",
    annotations=READ_ONLY,
    structured_output=True,
)
def get_workflow(workflow_id: str, version: int | None = None) -> dict[str, Any]:
    """Get a Workflow Definition and optionally an immutable Version contract."""
    try:
        with SessionLocal() as db:
            definition = db.get(WorkflowDefinitionRecord, workflow_id)
            if definition is None:
                raise ValueError("Workflow was not found")
            payload = workflow_definition_payload(definition, db)
            if version is not None:
                record = db.scalar(
                    select(WorkflowVersionRecord).where(
                        WorkflowVersionRecord.workflow_definition_id == workflow_id,
                        WorkflowVersionRecord.version_number == version,
                    )
                )
                if record is None:
                    raise ValueError(f"Workflow v{version} was not found")
                payload["version"] = workflow_version_payload(record)
            return payload
    except ValueError as exc:
        raise _tool_failure(exc) from exc


@server.tool(
    name="frameflow.workflows.run",
    title="Run a published Frameflow Workflow",
    annotations=OPEN_WORLD_WRITE,
    structured_output=True,
)
async def run_workflow(
    workflow_id: str,
    inputs: dict[str, Any],
    version: int | None = None,
) -> dict[str, Any]:
    """Start a published WorkflowVersion and return an explicit Run handle immediately."""
    try:
        with SessionLocal() as db:
            run = await start_published_workflow_run(
                db,
                workflow_id=workflow_id,
                version_number=version,
                inputs=inputs,
            )
            return workflow_run_payload(db, run)
    except (ValueError, RuntimeError, WorkflowContractError) as exc:
        raise _tool_failure(exc) from exc


@server.tool(
    name="frameflow.runs.get",
    title="Get a Frameflow Workflow Run",
    annotations=READ_ONLY,
    structured_output=True,
)
def get_workflow_run(run_id: str) -> dict[str, Any]:
    """Get status, progress, declared outputs, cost, and required human actions for a Workflow Run."""
    try:
        with SessionLocal() as db:
            run = db.get(CanvasRunRecord, run_id)
            if run is None or run.source_type != "WORKFLOW_VERSION":
                raise ValueError("Workflow Run was not found")
            return workflow_run_payload(db, run)
    except ValueError as exc:
        raise _tool_failure(exc) from exc


@server.tool(
    name="frameflow.runs.cancel",
    title="Cancel a Frameflow Workflow Run",
    annotations=IDEMPOTENT_WRITE,
    structured_output=True,
)
async def cancel_mcp_workflow_run(run_id: str) -> dict[str, Any]:
    """Cancel a non-terminal Workflow Run and all unfinished NodeRuns."""
    try:
        with SessionLocal() as db:
            run = await cancel_workflow_run(db, run_id)
            return workflow_run_payload(db, run)
    except (ValueError, RuntimeError) as exc:
        raise _tool_failure(exc) from exc


@server.tool(
    name="frameflow.runs.respond",
    title="Respond to a Frameflow human gate",
    annotations=ADDITIVE_WRITE,
    structured_output=True,
)
async def respond_to_mcp_workflow_run(
    run_id: str,
    node_id: str,
    action: Literal["approve", "select_artifact"],
    parameters: dict[str, Any] | None = None,
    artifact_id: str | None = None,
) -> dict[str, Any]:
    """Approve a human-gate schema or select one of the connected candidate Artifacts."""
    try:
        with SessionLocal() as db:
            run = await respond_to_workflow_run(
                db,
                run_id=run_id,
                node_id=node_id,
                action=action,
                parameters=parameters,
                artifact_id=artifact_id,
            )
            return workflow_run_payload(db, run)
    except (ValueError, RuntimeError) as exc:
        raise _tool_failure(exc) from exc


def _artifact_metadata(db: Session, artifact_id: str) -> dict[str, Any]:
    artifact = db.get(ArtifactRecord, artifact_id)
    if artifact is None:
        raise ValueError("Artifact was not found")
    storage = dict((artifact.metadata_json or {}).get("storage") or {})
    return {
        "artifact_id": artifact.id,
        "type": artifact.type,
        "schema_id": artifact.schema_id,
        "sha256": artifact.sha256,
        "producer_node_run_id": artifact.producer_node_run_id,
        "input_artifact_ids": list(artifact.input_artifact_ids or []),
        "content_type": str(storage.get("content_type") or "application/octet-stream"),
        "size_bytes": int(storage.get("size_bytes") or 0),
        "duration_ms": int((artifact.metadata_json or {}).get("duration_ms") or 0),
        "content_url": artifact_content_url(artifact.id),
        "resource_uri": f"frameflow://artifacts/{artifact.id}",
        "created_at": artifact.created_at.isoformat(),
    }


@server.tool(
    name="frameflow.artifacts.list",
    title="List Frameflow Artifacts",
    annotations=READ_ONLY,
    structured_output=True,
)
def list_artifacts(
    types: list[str] | None = None,
    query: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """List immutable Artifacts for asset.select, character.select, and Artifact workflow inputs."""
    if limit < 1 or limit > 500:
        raise ToolError("limit must be between 1 and 500")
    requested_types = {item.strip() for item in (types or []) if item.strip()}
    needle = (query or "").strip().lower()
    with SessionLocal() as db:
        statement = select(ArtifactRecord).order_by(ArtifactRecord.created_at.desc())
        if requested_types:
            statement = statement.where(ArtifactRecord.type.in_(requested_types))
        candidates = db.scalars(statement.limit(500)).all()
        matches = []
        for artifact in candidates:
            filename = str(
                (artifact.metadata_json or {}).get("filename")
                or ((artifact.metadata_json or {}).get("output") or {}).get("title")
                or artifact.id
            )
            if needle and needle not in f"{artifact.id} {artifact.type} {filename}".lower():
                continue
            matches.append(_artifact_metadata(db, artifact.id))
            if len(matches) == limit:
                break
        return {"artifacts": matches, "count": len(matches)}


@server.tool(
    name="frameflow.artifacts.get",
    title="Get a Frameflow Artifact",
    annotations=READ_ONLY,
    structured_output=True,
)
def get_artifact(artifact_id: str, include_lineage: bool = False) -> dict[str, Any]:
    """Get immutable Artifact metadata and optionally its bounded lineage graph."""
    try:
        with SessionLocal() as db:
            payload = _artifact_metadata(db, artifact_id)
            if include_lineage:
                payload["lineage"] = artifact_lineage_graph(db, artifact_id, direction="both", depth=8)
            return payload
    except ValueError as exc:
        raise _tool_failure(exc) from exc


@server.resource(
    "frameflow://node-contracts/{type_key}/{contract_version}",
    name="Frameflow Node contract",
    description="Immutable Node Manifest used by Canvas, Publish validation, and execution.",
    mime_type="application/json",
)
def node_contract_resource(type_key: str, contract_version: int) -> str:
    try:
        return _json_resource(_definition_for(type_key, contract_version).public_payload())
    except ValueError as exc:
        raise ResourceError(str(exc)) from exc


@server.resource(
    "frameflow://workflows/{workflow_id}",
    name="Frameflow Workflow",
    description="Workflow Definition metadata and current published version.",
    mime_type="application/json",
)
def workflow_resource(workflow_id: str) -> str:
    with SessionLocal() as db:
        definition = db.get(WorkflowDefinitionRecord, workflow_id)
        if definition is None:
            raise ResourceError("Workflow was not found")
        return _json_resource(workflow_definition_payload(definition, db))


@server.resource(
    "frameflow://workflows/{workflow_id}/versions/{version_number}",
    name="Frameflow Workflow Version",
    description="Immutable published graph and input/output contract.",
    mime_type="application/json",
)
def workflow_version_resource(workflow_id: str, version_number: int) -> str:
    with SessionLocal() as db:
        version = db.scalar(
            select(WorkflowVersionRecord).where(
                WorkflowVersionRecord.workflow_definition_id == workflow_id,
                WorkflowVersionRecord.version_number == version_number,
            )
        )
        if version is None:
            raise ResourceError("Workflow Version was not found")
        return _json_resource(workflow_version_payload(version))


@server.resource(
    "frameflow://runs/{run_id}",
    name="Frameflow Workflow Run",
    description="Current Workflow Run state, outputs, and required human actions.",
    mime_type="application/json",
)
def workflow_run_resource(run_id: str) -> str:
    with SessionLocal() as db:
        run = db.get(CanvasRunRecord, run_id)
        if run is None or run.source_type != "WORKFLOW_VERSION":
            raise ResourceError("Workflow Run was not found")
        return _json_resource(workflow_run_payload(db, run))


@server.resource(
    "frameflow://artifacts/{artifact_id}",
    name="Frameflow Artifact",
    description="Immutable Artifact metadata and stable content URL.",
    mime_type="application/json",
)
def artifact_resource(artifact_id: str) -> str:
    try:
        with SessionLocal() as db:
            return _json_resource(_artifact_metadata(db, artifact_id))
    except ValueError as exc:
        raise ResourceError(str(exc)) from exc


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Frameflow MCP server")
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default=os.getenv("FRAMEFLOW_MCP_TRANSPORT", "stdio"),
    )
    parser.add_argument("--host", default=os.getenv("FRAMEFLOW_MCP_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("FRAMEFLOW_MCP_PORT", "8001")))
    args = parser.parse_args()
    try:
        if args.transport == "streamable-http":
            loopback = args.host in {"127.0.0.1", "localhost", "::1"}
            insecure_remote = os.getenv("FRAMEFLOW_MCP_ALLOW_INSECURE_REMOTE", "").lower() == "true"
            if not loopback and not insecure_remote:
                parser.error(
                    "remote MCP binding requires OAuth/Workspace authorization; keep --host on loopback "
                    "or explicitly set FRAMEFLOW_MCP_ALLOW_INSECURE_REMOTE=true for an isolated network"
                )
            server.run(
                transport="streamable-http",
                host=args.host,
                port=args.port,
                streamable_http_path="/mcp",
                stateless_http=True,
            )
        else:
            server.run(transport="stdio")
    except KeyboardInterrupt:  # pragma: no cover - normal CLI shutdown
        pass


if __name__ == "__main__":
    main()
