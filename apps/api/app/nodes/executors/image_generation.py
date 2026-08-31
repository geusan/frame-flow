from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from ...providers import model_id_for_alias
from ...providers_generation import LIVE_GENERATION_REVISION, InputMedia, get_google_generation_services
from ...providers_openai import OPENAI_LIVE_REVISION, get_openai_generation_services
from ...service import create_artifact
from ...storage import artifact_content_url
from ..contracts import NodeExecutionContext, NodeExecutionResult
from .media_support import load_input_media


IMAGE_MODEL_COSTS = {
    "google.image.fast": 0.067,
    "google.image.quality": 0.134,
    "google.image.edit.fast": 0.0336,
}


@dataclass(frozen=True)
class ImageProviderAsset:
    data: bytes
    content_type: str
    filename: str


class ImageGenerationCapabilityExecutor:
    def supports(self, context: NodeExecutionContext) -> bool:
        return (
            context.definition.execution.kind == "provider"
            and context.definition.artifact_contract.primary_type == "Image"
            and context.payload.model_alias.startswith(("google.image.", "openai.image."))
            and os.getenv("GENERATION_PROVIDER_MODE", "live").strip().lower() == "live"
        )

    def execute(
        self,
        context: NodeExecutionContext,
        resolved_node_config: dict[str, Any],
        typed_inputs: list[dict[str, Any]],
    ) -> NodeExecutionResult:
        if not self.supports(context):
            raise RuntimeError("image generation capability does not support this execution context")
        prompt = context.payload.prompt.strip()
        if not prompt:
            raise ValueError("image generation requires a connected Prompt")
        media, input_artifact_ids, input_roles = load_input_media(context.db, context.definition, typed_inputs)
        image_inputs = [item for item in media if item.artifact_type == "Image"][:4]
        model_alias = context.payload.model_alias
        count = max(1, min(4, int(resolved_node_config.get("output_count") or 1)))
        aspect_ratio = str(resolved_node_config.get("aspect_ratio") or "9:16")
        if model_alias.startswith("google.image."):
            seed = resolved_node_config.get("seed")
            generated = get_google_generation_services().generate_images(
                logical_model=model_alias,
                prompt=prompt,
                candidate_count=count,
                aspect_ratio=aspect_ratio,
                seed=int(seed) if seed is not None else None,
                reference_images=image_inputs,
            )
            assets = [
                ImageProviderAsset(item.data, item.mime_type, f"generated-{index}{'.png' if 'png' in item.mime_type else '.jpg'}")
                for index, item in enumerate(generated, start=1)
            ]
            request_id = generated[0].provider_request_id
            exact_model_id = generated[0].exact_model_id
            provider = "google"
            revision = LIVE_GENERATION_REVISION
        else:
            images, request_id = get_openai_generation_services().generate_images(
                logical_model=model_alias,
                prompt=prompt,
                count=count,
                aspect_ratio=aspect_ratio,
                quality=str(resolved_node_config.get("quality") or "medium"),
                reference_images=image_inputs,
            )
            assets = [ImageProviderAsset(data, "image/png", f"generated-{index}.png") for index, data in enumerate(images, start=1)]
            exact_model_id = model_id_for_alias(model_alias) or model_alias
            provider = "openai"
            revision = OPENAI_LIVE_REVISION
        artifacts = [
            create_artifact(
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
                    "candidate_index": index,
                },
                content=asset.data,
                content_type=asset.content_type,
                filename=asset.filename,
            )
            for index, asset in enumerate(assets, start=1)
        ]
        context.db.flush()
        primary = artifacts[0]
        return NodeExecutionResult(
            output={"kind": "image", "title": "Generated image", "mimeType": assets[0].content_type, "url": artifact_content_url(primary.id)},
            output_artifact_ids=[artifact.id for artifact in artifacts],
            provider_request_id=request_id,
            cost_usd=IMAGE_MODEL_COSTS.get(model_alias, 0.0),
            metadata={
                "artifact_type": context.definition.artifact_contract.primary_type,
                "schema_id": context.definition.artifact_contract.schema_id,
                "input_artifact_ids": input_artifact_ids,
                "lineage_roles": input_roles,
                "retryable": True,
                "exact_model_id": exact_model_id,
            },
        )
