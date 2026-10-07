"""Use unchanged Local/Temporal executors with trusted persisted Run scope."""
from dataclasses import replace
from inspect import isawaitable

from temporalio import activity

from .access import AccessDenied, CredentialReference, Principal, WorkspaceContext, execution_scope


def context_from_record(record):
    value = record.access_context_json or {}
    if value.get("workspace_id") != record.workspace_id or not value.get("organization_id") or not value.get("principal", {}).get("id"):
        raise AccessDenied(403, "run_scope_missing")
    return WorkspaceContext(Principal(**value["principal"]),record.workspace_id,value["request_id"],value["organization_id"],run_id=record.id,
                            action="edit",credential_references=tuple(CredentialReference(**item) for item in value.get("credential_references",[])))


def scoped_activity(original, *, name, adapters, context_resolver):
    async def execute(*args):
        if not args or not isinstance(args[0],str):
            raise AccessDenied(403,"run_scope_missing")
        context=context_resolver(args[0])
        with execution_scope(context,adapters):
            result=original(*args)
            return await result if isawaitable(result) else result
    execute.__name__ = original.__name__ + "_scoped"
    return activity.defn(name=name)(execute)


def create_worker(client, *, task_queue, adapters, context_resolver):
    from temporalio.worker import Worker
    from .canvas_temporal import CanvasRunWorkflow
    from .canvas_activities import execute_canvas_node_activity, finalize_canvas_run_activity, mark_canvas_waiting_activity, record_canvas_approval_activity, record_canvas_selection_activity
    activities=[(execute_canvas_node_activity,"execute_canvas_node"),(finalize_canvas_run_activity,"finalize_canvas_run"),(mark_canvas_waiting_activity,"mark_canvas_waiting"),(record_canvas_approval_activity,"record_canvas_approval"),(record_canvas_selection_activity,"record_canvas_selection")]
    return Worker(client,task_queue=task_queue,workflows=[CanvasRunWorkflow],activities=[scoped_activity(fn,name=name,adapters=adapters,context_resolver=context_resolver) for fn,name in activities])
