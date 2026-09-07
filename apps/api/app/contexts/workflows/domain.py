class WorkflowError(Exception):
    pass


class WorkflowNotFoundError(WorkflowError):
    pass


class WorkflowConflictError(WorkflowError):
    pass


class WorkflowValidationError(WorkflowError):
    pass
