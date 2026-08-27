from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ProviderSubmission:
    provider_request_id: str
    provider_operation_id: str | None
    request_hash: str


class GenerationProvider(Protocol):
    logical_model: str

    def submit(self, payload: dict[str, Any], idempotency_key: str) -> ProviderSubmission: ...
    def cancel(self, operation_id: str) -> None: ...


class MockGoogleProvider:
    """Deterministic provider used by local development and contract tests."""

    def __init__(self, logical_model: str) -> None:
        self.logical_model = logical_model

    def submit(self, payload: dict[str, Any], idempotency_key: str) -> ProviderSubmission:
        request_hash = hashlib.sha256(f"{self.logical_model}:{payload}:{idempotency_key}".encode()).hexdigest()
        suffix = request_hash[:14]
        operation = f"operations/mock-{suffix}" if "video" in self.logical_model else None
        return ProviderSubmission(f"req_{suffix}", operation, request_hash)

    def cancel(self, operation_id: str) -> None:
        return None


MODEL_REGISTRY = {
    "google.text.fast": "gemini-2.5-flash",
    "google.text.quality": "gemini-2.5-pro",
    "google.image.fast": "gemini-3.1-flash-image",
    "google.image.quality": "gemini-3-pro-image",
    "google.video.fast": "veo-3.1-fast-generate-001",
    "google.video.quality": "veo-3.1-generate-001",
    "google.tts.fast": "gemini-2.5-flash-tts",
    "google.stt.default": "chirp_3",
}

