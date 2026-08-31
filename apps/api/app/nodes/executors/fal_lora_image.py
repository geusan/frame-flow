from __future__ import annotations

import os
from typing import Any

from ...providers import model_id_for_alias
from ...providers_fal import FAL_LIVE_REVISION, get_fal_generation_services
from ...service import create_artifact
from ...storage import artifact_content_url
from ..contracts import NodeExecutionContext, NodeExecutionResult
from .media_support import load_input_media


class FalLoraImageCapabilityExecutor:
    def supports(self, context: NodeExecutionContext) -> bool:
        return (
            context.definition.execution.kind == "provider"
            and context.definition.artifact_contract.primary_type == "Image"
            and context.payload.model_alias.startswith("fal.image.")
            and "lora_url" in context.definition.config_schema.get("properties", {})
            and os.getenv("GENERATION_PROVIDER_MODE", "live").strip().lower() == "live"
        )

    def execute(
        self,
        context: NodeExecutionContext,
        resolved_node_config: dict[str, Any],
        typed_inputs: list[dict[str, Any]],
    ) -> NodeExecutionResult:
        if not self.supports(context):
            raise RuntimeError("fal LoRA image capability does not support this execution context")
        prompt = context.payload.prompt.strip()
        if not prompt:
            raise ValueError("fal LoRA image generation requires a connected Prompt")
        _, input_artifact_ids, input_roles = load_input_media(
            context.db,
            context.definition,
            typed_inputs,
            expand_characters=False,
        )
        lora_artifact_id = str(resolved_node_config.get("character_lora_artifact_id") or "")
        if lora_artifact_id and lora_artifact_id not in input_artifact_ids:
            input_artifact_ids.append(lora_artifact_id)
            input_roles[lora_artifact_id] = "lora_weights"
        generated = get_fal_generation_services().generate_lora_image(
            prompt=prompt,
            lora_url=str(resolved_node_config.get("lora_url") or ""),
            lora_scale=float(resolved_node_config.get("lora_scale") or 0.9),
            trigger_word=str(resolved_node_config.get("trigger_word") or ""),
            aspect_ratio=str(resolved_node_config.get("aspect_ratio") or "9:16"),
            resolution=str(resolved_node_config.get("resolution") or "2K"),
        )
        model_alias = context.payload.model_alias
        exact_model_id = model_id_for_alias(model_alias) or model_alias
        artifact = create_artifact(
            context.db,
            context.definition.artifact_contract.primary_type,
            schema_id=context.definition.artifact_contract.schema_id,
            input_artifact_ids=input_artifact_ids,
            input_artifact_roles=input_roles,
            metadata={
                "experiment_id": context.experiment_id,
                "request_hash": context.request_hash,
                "execution_mode": FAL_LIVE_REVISION,
                "immutable": True,
                "source": "node_executor_registry",
                "provider": "fal",
                "model_alias": model_alias,
                "exact_model_id": exact_model_id,
                "normalized_config": resolved_node_config,
                "output_role": context.definition.artifact_contract.output_role,
                "lora_artifact_id": lora_artifact_id or None,
            },
            content=generated.data,
            content_type=generated.content_type,
            filename="lora-generated.png",
        )
        context.db.flush()
        return NodeExecutionResult(
            output={"kind": "image", "title": "LoRA generated image", "mimeType": generated.content_type, "url": artifact_content_url(artifact.id)},
            output_artifact_ids=[artifact.id],
            provider_request_id=generated.provider_request_id,
            cost_usd=0.07,
            metadata={
                "artifact_type": context.definition.artifact_contract.primary_type,
                "schema_id": context.definition.artifact_contract.schema_id,
                "input_artifact_ids": input_artifact_ids,
                "lineage_roles": input_roles,
                "retryable": True,
                "exact_model_id": exact_model_id,
            },
        )
