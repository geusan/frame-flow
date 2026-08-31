from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from openai import OpenAI

from .providers import XAI_MODEL_REGISTRY


XAI_LIVE_REVISION = "xai-responses.v1"
XAI_API_BASE_URL = "https://api.x.ai/v1"


@dataclass(frozen=True)
class XAIProviderConfig:
    api_key: str

    @classmethod
    def from_env(cls) -> "XAIProviderConfig":
        api_key = os.getenv("XAI_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("XAI_API_KEY is required for Grok models")
        return cls(api_key=api_key)


@dataclass(frozen=True)
class XAITextResult:
    text: str
    provider_request_id: str
    exact_model_id: str
    input_tokens: int
    output_tokens: int
    cost_usd: float


class XAITextServices:
    def __init__(self, config: XAIProviderConfig | None = None, client: Any | None = None) -> None:
        self.config = config or XAIProviderConfig.from_env()
        self.client = client or OpenAI(api_key=self.config.api_key, base_url=XAI_API_BASE_URL)

    def generate(
        self,
        *,
        model_alias: str,
        prompt: str,
        instructions: str,
        reasoning_effort: str,
        timeout_seconds: int,
        prompt_cache_key: str,
    ) -> XAITextResult:
        try:
            exact_model = XAI_MODEL_REGISTRY[model_alias]
        except KeyError as exc:
            raise ValueError(f"xAI model alias is not registered: {model_alias}") from exc
        response = self.client.with_options(timeout=timeout_seconds).responses.create(
            model=exact_model,
            instructions=instructions,
            input=prompt,
            reasoning={"effort": reasoning_effort},
            prompt_cache_key=prompt_cache_key,
        )
        text = str(response.output_text or "").strip()
        if not text:
            raise RuntimeError("xAI Responses API returned no text")
        usage = getattr(response, "usage", None)
        input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
        # Grok 4.6 public list pricing as of 2026-08-31: $2/M input, $6/M output.
        cost_usd = input_tokens * 2.0 / 1_000_000 + output_tokens * 6.0 / 1_000_000
        return XAITextResult(
            text=text,
            provider_request_id=str(response.id),
            exact_model_id=exact_model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
        )


def get_xai_text_services() -> XAITextServices:
    return XAITextServices()
