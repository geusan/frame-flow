"""Workspace isolation for Core ORM operations, including nested JSON references.

This is an explicit Session adapter. Raw SQL and bulk writes are reserved for
migrations/system jobs; they are never allowed through a customer session.
"""
from __future__ import annotations

from typing import Any, Callable

from sqlalchemy import event, inspect, select
from sqlalchemy.orm import Session, with_loader_criteria

from .access import AccessDenied, WorkspaceContext
from .database_namespace import table_name as database_table_name
from .database import Base, ProviderCostRecord, ProviderCostObservation, ProviderSettingRecord, WorkspaceOwned, WorkspaceRecord


REFERENCE_TABLES = {
    "artifact_id": "artifacts", "artifact_ids": "artifacts", "input_artifact_ids": "artifacts", "output_artifact_ids": "artifacts",
    "selected_artifact_id": "artifacts", "playback_artifact_id": "artifacts", "image_artifact_id": "artifacts", "audio_artifact_id": "artifacts", "video_artifact_id": "artifacts",
    "reference_id": "reference_assets", "reference_ids": "reference_assets", "reference_set_id": "reference_sets",
    "format_id": "formats", "parent_ids": "formats", "font_id": "fonts", "font_ids": "fonts", "supersedes_id": "fonts",
    "canvas_id": "canvases", "source_canvas_id": "canvases", "draft_canvas_id": "canvases",
    "workflow_definition_id": "workflow_definitions", "workflow_version_id": "workflow_versions", "base_version_id": "workflow_versions", "current_version_id": "workflow_versions",
    "skill_definition_id": "skill_definitions", "skill_version_id": "skill_versions", "experiment_id": "experiment_runs", "cached_from_id": "experiment_runs",
    "producer_node_run_id": ("node_runs","canvas_node_runs"), "node_run_id": ("node_runs","canvas_node_runs"), "billing_node_run_id": ("node_runs","canvas_node_runs"),
    "billing_run_id": ("runs","canvas_runs"), "run_id": ("runs","canvas_runs"), "active_run_id": ("runs","canvas_runs"),
}


class WorkspaceSession(Session):
    def __init__(self, *args, context: WorkspaceContext, revalidate: Callable[[WorkspaceContext], None], **kwargs):
        super().__init__(*args, **kwargs)
        self.context = context
        self.revalidate = revalidate

    def __enter__(self):
        from .access import _active_session
        self._scope_token=_active_session.set(self)
        return super().__enter__()

    def __exit__(self,*args):
        from .access import _active_session
        try:return super().__exit__(*args)
        finally:_active_session.reset(self._scope_token)

    def assert_live(self):
        self.revalidate(self.context)

    def get(self, entity, ident, **kwargs):
        self.assert_live()
        row = super().get(entity, ident, **kwargs)
        if row is not None and isinstance(row, WorkspaceOwned) and row.workspace_id != self.context.workspace_id:
            return None
        return row


@event.listens_for(WorkspaceSession, "do_orm_execute")
def scope_queries(state):
    session = state.session
    session.assert_live()
    if not state.is_select or not state.is_orm_statement:
        raise AccessDenied(403, "unscoped_statement_denied")
    if any(mapper.class_ is ProviderSettingRecord for mapper in state.all_mappers):
        raise AccessDenied(403, "deployment_configuration_denied")
    workspace_id = session.context.workspace_id
    state.statement = state.statement.options(
        with_loader_criteria(WorkspaceOwned, lambda model: model.workspace_id == workspace_id, include_aliases=True),
        with_loader_criteria(WorkspaceRecord, lambda model: model.id == workspace_id, include_aliases=True),
    )


def referenced_ids(value: Any):
    if isinstance(value, dict):
        for key, item in value.items():
            table = REFERENCE_TABLES.get(key)
            if table is None and (key.endswith("_artifact_id") or key.endswith("_artifact_ids") or key.endswith("ArtifactId")):
                table = "artifacts"
            if table:
                for identifier in item if isinstance(item, list) else [item]:
                    if isinstance(identifier, str) and identifier:
                        yield table, identifier
            yield from referenced_ids(item)
    elif isinstance(value, list):
        for item in value:
            yield from referenced_ids(item)


@event.listens_for(WorkspaceSession, "before_flush")
def validate_writes(session, flush_context, instances):
    session.assert_live()
    changed = set(session.new) | set(session.dirty) | set(session.deleted)
    if changed and session.context.action == "read":
        raise AccessDenied(403,"read_only_context")
    if session.context.action=="cost" and any(not isinstance(row,(ProviderCostRecord,ProviderCostObservation)) for row in changed):
        raise AccessDenied(403,"cost_writer_scope_required")
    pending = {(record.__tablename__, record.id): record for record in session.new if isinstance(record, WorkspaceOwned)}
    for record in changed:
        if not isinstance(record, WorkspaceOwned):
            raise AccessDenied(403, "deployment_configuration_denied")
        state = inspect(record)
        previous = state.attrs.workspace_id.history.deleted
        if previous and previous[0] != session.context.workspace_id:
            raise AccessDenied(404, "resource_not_found")
        if record in session.new and record.workspace_id is None:
            record.workspace_id = session.context.workspace_id
        if record.workspace_id != session.context.workspace_id:
            raise AccessDenied(404, "resource_not_found")
        if record in session.new and hasattr(record, "access_context_json"):
            from dataclasses import asdict
            record.access_context_json = asdict(session.context)
            from .access import current_scope
            scope=current_scope()
            if scope and scope.adapters.execution_policy:
                scope.adapters.execution_policy.reserve(session.context,record,session.connection())
        elif hasattr(record,"access_context_json") and str(record.status) in {"SUCCEEDED","FAILED","CANCELED"}:
            from .access import current_scope
            scope=current_scope()
            if scope and scope.adapters.execution_policy:
                scope.adapters.execution_policy.settle(session.context,record,session.connection())
        for actor_field in ("actor_id", "created_by", "updated_by", "published_by"):
            if hasattr(record, actor_field):
                setattr(record, actor_field, session.context.principal.id)
        references = []
        for column in state.mapper.columns:
            value = getattr(record, column.key)
            if value is None or column.key == "workspace_id":
                continue
            for foreign in column.foreign_keys:
                if foreign.column.table.name != database_table_name("workspaces"):
                    references.append((foreign.column.table.name, value))
            if column.key in REFERENCE_TABLES and isinstance(value, str):
                references.append((REFERENCE_TABLES[column.key], value))
            references.extend(referenced_ids(value))
        for table_name, identifier in references:
            names = table_name if isinstance(table_name,tuple) else (table_name,)
            found = False
            for name in names:
                if name not in Base.metadata.tables:
                    name = database_table_name(name)
                if (name,identifier) in pending:
                    target=pending[name,identifier]
                    if target.workspace_id in (None,session.context.workspace_id):
                        found=True
                        break
                table=Base.metadata.tables.get(name)
                if table is None or "workspace_id" not in table.c:
                    continue
                # Trusted internal lookup returns no foreign row to the caller.
                if session.connection().execute(select(table.c.id).where(table.c.id==identifier,table.c.workspace_id==session.context.workspace_id)).first():
                    found=True
                    break
            if not found:
                raise AccessDenied(404, "resource_not_found")


def workspace_session_factory(engine, revalidate):
    def create(context: WorkspaceContext) -> WorkspaceSession:
        return WorkspaceSession(bind=engine, context=context, revalidate=revalidate, expire_on_commit=False)
    return create
