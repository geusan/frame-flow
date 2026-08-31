from __future__ import annotations

import os
from typing import Any

from ...providers_xai import XAI_LIVE_REVISION, get_xai_text_services
from ..contracts import NodeExecutionContext, NodeExecutionResult
from .text_support import TextProviderResult, complete_text_execution, text_instructions


class XAITextCapabilityExecutor:
    def supports(self, context: NodeExecutionContext) -> bool:
        return (
            context.definition.execution.kind == "provider"
            and context.payload.model_alias.startswith("xai.text.")
            and os.getenv("GENERATION_PROVIDER_MODE", "live").strip().lower() == "live"
        )

    def execute(
        self,
        context: NodeExecutionContext,
        resolved_node_config: dict[str, Any],
        typed_inputs: list[dict[str, Any]],
    ) -> NodeExecutionResult:
        if not self.supports(context):
            raise RuntimeError("xAI text capability does not support this execution context")
        prompt = context.payload.prompt.strip()
        if not prompt:
            raise ValueError("xAI text generation requires a connected Prompt")
        generated = get_xai_text_services().generate(
            model_alias=context.payload.model_alias,
            prompt=prompt,
            instructions=text_instructions(context, resolved_node_config),
            reasoning_effort="high",
            timeout_seconds=300,
            prompt_cache_key=context.request_hash,
        )
        result = TextProviderResult(
            text=generated.text,
            provider_request_id=generated.provider_request_id,
            exact_model_id=generated.exact_model_id,
            cost_usd=generated.cost_usd,
            metadata={"usage": {"input_tokens": generated.input_tokens, "output_tokens": generated.output_tokens}},
        )
        return complete_text_execution(
            context,
            resolved_node_config,
            typed_inputs,
            result,
            provider="xai",
            execution_revision=XAI_LIVE_REVISION,
        )
