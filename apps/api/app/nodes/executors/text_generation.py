from __future__ import annotations

import os
from typing import Any

from ...providers import model_id_for_alias
from ...providers_generation import LIVE_GENERATION_REVISION, get_google_generation_services
from ...providers_openai import OPENAI_LIVE_REVISION, get_openai_generation_services
from ..contracts import NodeExecutionContext, NodeExecutionResult
from .text_support import TextProviderResult, complete_text_execution, text_instructions


GOOGLE_TEXT_COSTS = {
    "google.text.fast": 0.01,
    "google.text.quality": 0.03,
    "google.text.3.6-flash": 0.01,
    "google.text.3.5-flash": 0.01,
    "google.text.3.5-flash-lite": 0.005,
    "google.text.3.1-pro-preview": 0.03,
    "google.text.3.1-flash-lite": 0.005,
    "google.text.2.5-flash": 0.01,
    "google.text.2.5-flash-lite": 0.005,
}


class TextGenerationCapabilityExecutor:
    def supports(self, context: NodeExecutionContext) -> bool:
        return (
            context.definition.execution.kind == "provider"
            and context.payload.model_alias.startswith(("google.text.", "openai.text.", "openai.chat."))
            and os.getenv("GENERATION_PROVIDER_MODE", "live").strip().lower() == "live"
        )

    def execute(
        self,
        context: NodeExecutionContext,
        resolved_node_config: dict[str, Any],
        typed_inputs: list[dict[str, Any]],
    ) -> NodeExecutionResult:
        if not self.supports(context):
            raise RuntimeError("text generation capability does not support this execution context")
        prompt = context.payload.prompt.strip()
        if not prompt:
            raise ValueError("text generation requires a connected Prompt")
        instructions = text_instructions(context, resolved_node_config)
        model_alias = context.payload.model_alias
        exact_model_id = model_id_for_alias(
            model_alias,
            gemini_api=bool((os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()),
        )
        if not exact_model_id:
            raise ValueError(f"text model alias is not registered: {model_alias}")
        if model_alias.startswith("google.text."):
            seed = resolved_node_config.get("seed")
            text, request_id = get_google_generation_services().text.generate_text(
                logical_model=model_alias,
                system_prompt=instructions,
                rendered_prompt=prompt,
                temperature=float(resolved_node_config.get("temperature") or 0.4),
                seed=int(seed) if seed is not None else None,
            )
            generated = TextProviderResult(text, request_id, exact_model_id, GOOGLE_TEXT_COSTS.get(model_alias, 0.0))
            return complete_text_execution(context, resolved_node_config, typed_inputs, generated, provider="google", execution_revision=LIVE_GENERATION_REVISION)
        text, request_id = get_openai_generation_services().generate_text(
            logical_model=model_alias,
            prompt=prompt,
            instructions=instructions,
        )
        generated = TextProviderResult(text, request_id, exact_model_id)
        return complete_text_execution(context, resolved_node_config, typed_inputs, generated, provider="openai", execution_revision=OPENAI_LIVE_REVISION)
