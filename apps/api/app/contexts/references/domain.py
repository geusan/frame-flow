class ReferenceError(Exception):
    pass


class ReferenceNotFoundError(ReferenceError):
    pass


class ReferenceValidationError(ReferenceError):
    pass
