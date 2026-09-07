class RunError(Exception):
    pass


class RunNotFoundError(RunError):
    pass


class RunConflictError(RunError):
    pass


class RunValidationError(RunError):
    pass
