class RunError(Exception):
    pass


class RunNotFoundError(RunError):
    pass


class RunConflictError(RunError):
    pass


class RunValidationError(RunError):
    pass


def require_successful_baseline(status: object) -> None:
    if str(status) != "SUCCEEDED":
        raise RunConflictError("only successful experiments can be a baseline")


def is_terminal_run_status(status: object) -> bool:
    return str(status) in {"SUCCEEDED", "FAILED", "CANCELED"}
