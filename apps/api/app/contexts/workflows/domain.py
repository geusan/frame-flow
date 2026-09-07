class WorkflowError(Exception):
    pass


class WorkflowNotFoundError(WorkflowError):
    pass


class WorkflowConflictError(WorkflowError):
    pass


class WorkflowValidationError(WorkflowError):
    pass


def require_runnable_workflow(status: str) -> None:
    if status != "ACTIVE":
        raise WorkflowValidationError("Archived Workflow cannot be run")
