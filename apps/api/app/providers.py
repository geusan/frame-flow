from __future__ import annotations

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

OPENAI_MODEL_REGISTRY = {
    "openai.text.fast": "gpt-5.6-luna",
    "openai.text.quality": "gpt-5.6-terra",
    "openai.chat.latest": "chat-latest",
    "openai.image.default": "gpt-image-2",
    "openai.tts.default": "gpt-4o-mini-tts",
}

ALL_MODEL_REGISTRY = {**MODEL_REGISTRY, **OPENAI_MODEL_REGISTRY}
