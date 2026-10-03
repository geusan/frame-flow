class AdministrationError(Exception):
    pass


class AdministrationNotFoundError(AdministrationError):
    pass


class AdministrationConflictError(AdministrationError):
    pass


class AdministrationValidationError(AdministrationError):
    pass


class AdministrationUnsupportedMediaError(AdministrationError):
    pass


class AdministrationPayloadTooLargeError(AdministrationError):
    pass


class AdministrationUpstreamError(AdministrationError):
    pass
