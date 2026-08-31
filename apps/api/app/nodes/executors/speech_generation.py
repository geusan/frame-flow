from __future__ import annotations

import os
from typing import Any

from ...providers_generation import LIVE_GENERATION_REVISION, get_google_generation_services
from ...providers_openai import OPENAI_LIVE_REVISION, get_openai_generation_services
from ...service import create_artifact
from ...storage import artifact_content_url
from ..contracts import NodeExecutionContext, NodeExecutionResult
from .text_support import input_lineage


SPEECH_MODEL_COSTS = {
    "google.tts.latest": 0.12,
    "google.tts.fast": 0.12,
    "google.tts.quality": 0.24,
    "openai.tts.default": 0.12,
    "openai.tts.fast": 0.12,
    "openai.tts.quality": 0.24,
}


class SpeechGenerationCapabilityExecutor:
    def supports(self, context: NodeExecutionContext) -> bool:
        return (
            context.definition.execution.kind == "provider"
            and context.definition.artifact_contract.primary_type == "Audio"
            and context.payload.model_alias.startswith(("google.tts.", "openai.tts."))
            and os.getenv("GENERATION_PROVIDER_MODE", "live").strip().lower() == "live"
        )

    def execute(
        self,
        context: NodeExecutionContext,
        resolved_node_config: dict[str, Any],
        typed_inputs: list[dict[str, Any]],
    ) -> NodeExecutionResult:
        if not self.supports(context):
            raise RuntimeError("speech generation capability does not support this execution context")
        text = context.payload.prompt.strip()
        if not text:
            raise ValueError("speech generation requires a connected Prompt")
        model_alias = context.payload.model_alias
        voice_name = str(resolved_node_config.get("voice_name") or "Kore")
        style_prompt = str(resolved_node_config.get("style_prompt") or "Read naturally and clearly for a short-form video.")
        if model_alias.startswith("google.tts."):
            generated = get_google_generation_services().generate_speech(
                logical_model=model_alias,
                text=text,
                style_prompt=style_prompt,
                voice_name=voice_name,
                locale=str(resolved_node_config.get("language") or "ko-KR"),
            )
            audio = generated.data
            request_id = generated.provider_request_id
            exact_model_id = generated.exact_model_id
            provider = "google"
            revision = LIVE_GENERATION_REVISION
        else:
            audio, request_id, exact_model_id = get_openai_generation_services().generate_speech(
                logical_model=model_alias,
                text=text,
                voice_name=voice_name,
                style_prompt=style_prompt,
            )
            provider = "openai"
            revision = OPENAI_LIVE_REVISION
        input_artifact_ids, input_roles = input_lineage(context, typed_inputs)
        artifact = create_artifact(
            context.db,
            context.definition.artifact_contract.primary_type,
            schema_id=context.definition.artifact_contract.schema_id,
            input_artifact_ids=input_artifact_ids,
            input_artifact_roles=input_roles,
            metadata={
                "experiment_id": context.experiment_id,
                "request_hash": context.request_hash,
                "execution_mode": revision,
                "immutable": True,
                "source": "node_executor_registry",
                "provider": provider,
                "model_alias": model_alias,
                "exact_model_id": exact_model_id,
                "normalized_config": resolved_node_config,
                "output_role": context.definition.artifact_contract.output_role,
            },
            content=audio,
            content_type="audio/wav",
            filename="voiceover.wav",
        )
        context.db.flush()
        return NodeExecutionResult(
            output={"kind": "audio", "title": "Generated voiceover", "mimeType": "audio/wav", "url": artifact_content_url(artifact.id)},
            output_artifact_ids=[artifact.id],
            provider_request_id=request_id,
            cost_usd=SPEECH_MODEL_COSTS.get(model_alias, 0.0),
            metadata={
                "artifact_type": context.definition.artifact_contract.primary_type,
                "schema_id": context.definition.artifact_contract.schema_id,
                "input_artifact_ids": input_artifact_ids,
                "lineage_roles": input_roles,
                "retryable": True,
                "exact_model_id": exact_model_id,
            },
        )
