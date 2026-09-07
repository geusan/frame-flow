from __future__ import annotations

from dataclasses import dataclass, field


CANVAS_ARTIFACT_MAX_BYTES = 250 * 1024 * 1024


class ArtifactError(Exception):
    pass


class ArtifactNotFoundError(ArtifactError):
    pass


class ArtifactConflictError(ArtifactError):
    pass


class ArtifactValidationError(ArtifactError):
    pass


class ArtifactUnsupportedMediaError(ArtifactError):
    pass


class ArtifactPayloadTooLargeError(ArtifactError):
    pass


class ArtifactServiceUnavailableError(ArtifactError):
    pass


@dataclass(frozen=True)
class BinaryContent:
    data: bytes
    content_type: str
    headers: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class StoredContent:
    content_type: str
    data: bytes | None = None
    redirect_url: str | None = None
