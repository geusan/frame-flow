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
    "google.text.fast": "gemini-3.6-flash",
    "google.text.quality": "gemini-3.1-pro-preview",
    "google.text.3.6-flash": "gemini-3.6-flash",
    "google.text.3.5-flash": "gemini-3.5-flash",
    "google.text.3.5-flash-lite": "gemini-3.5-flash-lite",
    "google.text.3.1-pro-preview": "gemini-3.1-pro-preview",
    "google.text.3.1-flash-lite": "gemini-3.1-flash-lite",
    "google.text.2.5-flash": "gemini-2.5-flash",
    "google.text.2.5-flash-lite": "gemini-2.5-flash-lite",
    "google.image.fast": "gemini-3.1-flash-image",
    "google.image.quality": "gemini-3-pro-image",
    "google.image.edit.fast": "gemini-3.1-flash-lite-image",
    "google.video.fast": "veo-3.1-fast-generate-001",
    "google.video.quality": "veo-3.1-generate-001",
    "google.video.omni": "gemini-omni-1.1-flash",
    "google.tts.latest": "gemini-3.1-flash-tts-preview",
    "google.tts.fast": "gemini-2.5-flash-tts",
    "google.tts.quality": "gemini-2.5-pro-tts",
    "google.stt.default": "chirp_3",
}

GEMINI_API_MODEL_OVERRIDES = {
    "google.video.fast": "veo-3.1-fast-generate-preview",
    "google.video.quality": "veo-3.1-generate-preview",
    "google.tts.fast": "gemini-2.5-flash-preview-tts",
    "google.tts.quality": "gemini-2.5-pro-preview-tts",
}

OPENAI_MODEL_REGISTRY = {
    "openai.text.fast": "gpt-5.6-luna",
    "openai.text.quality": "gpt-5.6-terra",
    "openai.chat.latest": "chat-latest",
    "openai.image.default": "gpt-image-2",
    "openai.tts.default": "gpt-4o-mini-tts",
    "openai.tts.fast": "tts-1",
    "openai.tts.quality": "tts-1-hd",
}

LOCAL_SUBSCRIPTION_MODEL_REGISTRY = {
    "chatgpt.local.quality": "gpt-5.6-terra",
    "chatgpt.local.fast": "gpt-5.6-luna",
    "claude.local.sonnet": "claude-sonnet-4-6",
    "claude.local.opus": "claude-opus-4-6",
    "claude.local.haiku": "claude-haiku-4-5-20251001",
}

FAL_MODEL_REGISTRY = {
    "fal.image.flux2-lora": "fal-ai/flux-2/lora",
    "fal.training.flux2-lora": "fal-ai/flux-2-trainer-v2",
}

ALL_MODEL_REGISTRY = {
    **MODEL_REGISTRY,
    **OPENAI_MODEL_REGISTRY,
    **LOCAL_SUBSCRIPTION_MODEL_REGISTRY,
    **FAL_MODEL_REGISTRY,
}


def model_id_for_alias(logical_alias: str, *, gemini_api: bool = False) -> str | None:
    if gemini_api and logical_alias in GEMINI_API_MODEL_OVERRIDES:
        return GEMINI_API_MODEL_OVERRIDES[logical_alias]
    return ALL_MODEL_REGISTRY.get(logical_alias)
