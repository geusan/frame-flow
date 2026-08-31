from __future__ import annotations

import os
from typing import Any

from ...providers_generation import LIVE_GENERATION_REVISION, get_google_generation_services
from ...service import create_artifact
from ...storage import artifact_content_url
from ..contracts import NodeExecutionContext, NodeExecutionResult
from .media_support import load_input_media


VIDEO_MODEL_COSTS = {
    "google.video.fast": 1.40,
    "google.video.quality": 2.80,
    "google.video.omni": 1.40,
}


class VideoGenerationCapabilityExecutor:
    def supports(self, context: NodeExecutionContext) -> bool:
        return (
            context.definition.execution.kind == "provider"
            and context.definition.artifact_contract.primary_type == "Video"
            and context.payload.model_alias.startswith("google.video.")
            and os.getenv("GENERATION_PROVIDER_MODE", "live").strip().lower() == "live"
        )

    def execute(
        self,
        context: NodeExecutionContext,
        resolved_node_config: dict[str, Any],
        typed_inputs: list[dict[str, Any]],
    ) -> NodeExecutionResult:
        if not self.supports(context):
            raise RuntimeError("video generation capability does not support this execution context")
        prompt = context.payload.prompt.strip()
        if not prompt:
            raise ValueError("video generation requires a connected Prompt")
        ordered_inputs = sorted(
            typed_inputs,
            key=lambda item: {"Image": 0, "Character": 1, "Video": 2}.get(str(item.get("type") or ""), 3),
        )
        media, input_artifact_ids, input_roles = load_input_media(context.db, context.definition, ordered_inputs)
        image_inputs = [item for item in media if item.artifact_type == "Image"][:3]
        video_inputs = [item for item in media if item.artifact_type in {"Video", "FinalVideo"}][:1]
        seed = resolved_node_config.get("seed")
        model_alias = context.payload.model_alias
        generated = get_google_generation_services().generate_videos(
            logical_model=model_alias,
            prompt=prompt,
            duration_seconds=int(resolved_node_config.get("duration_seconds") or 6),
            candidate_count=int(resolved_node_config.get("output_count") or 1),
            aspect_ratio=str(resolved_node_config.get("aspect_ratio") or "9:16"),
            resolution=str(resolved_node_config.get("resolution") or "1080p"),
            seed=int(seed) if seed is not None else None,
            image_inputs=image_inputs,
            video_inputs=video_inputs,
        )
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
                    "execution_mode": LIVE_GENERATION_REVISION,
                    "immutable": True,
                    "source": "node_executor_registry",
                    "provider": "google",
                    "model_alias": model_alias,
                    "exact_model_id": item.exact_model_id,
                    "normalized_config": resolved_node_config,
                    "output_role": context.definition.artifact_contract.output_role,
                    "candidate_index": index,
                },
                content=item.data,
                content_type=item.mime_type,
                filename=f"generated-{index}.mp4",
            )
            for index, item in enumerate(generated, start=1)
        ]
        context.db.flush()
        primary = artifacts[0]
        omni = model_alias == "google.video.omni"
        return NodeExecutionResult(
            output={
                "kind": "video",
                "title": "Generated character video" if omni else "Generated video",
                "mimeType": generated[0].mime_type,
                "url": artifact_content_url(primary.id),
            },
            output_artifact_ids=[artifact.id for artifact in artifacts],
            provider_request_id=generated[0].provider_request_id,
            cost_usd=VIDEO_MODEL_COSTS.get(model_alias, 0.0),
            metadata={
                "artifact_type": context.definition.artifact_contract.primary_type,
                "schema_id": context.definition.artifact_contract.schema_id,
                "input_artifact_ids": input_artifact_ids,
                "lineage_roles": input_roles,
                "retryable": True,
                "exact_model_id": generated[0].exact_model_id,
            },
        )
