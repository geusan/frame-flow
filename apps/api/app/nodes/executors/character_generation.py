from __future__ import annotations

import json
import os
from typing import Any

from ...providers import model_id_for_alias
from ...providers_generation import LIVE_GENERATION_REVISION, get_google_generation_services
from ...providers_openai import OPENAI_LIVE_REVISION, get_openai_generation_services
from ...service import create_artifact
from ...storage import artifact_content_url
from ..contracts import NodeExecutionContext, NodeExecutionResult
from .image_generation import IMAGE_MODEL_COSTS
from .media_support import load_input_media


class CharacterGenerationCapabilityExecutor:
    def supports(self, context: NodeExecutionContext) -> bool:
        return (
            context.definition.execution.kind == "provider"
            and context.definition.artifact_contract.primary_type == "Character"
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
            raise RuntimeError("character generation capability does not support this execution context")
        synopsis = context.payload.prompt.strip()
        media, input_artifact_ids, input_roles = load_input_media(
            context.db,
            context.definition,
            typed_inputs,
            expand_characters=False,
        )
        references = [item for item in media if item.artifact_type == "Image"][:3]
        name = str(resolved_node_config.get("character_name") or "Generated character").strip() or "Generated character"
        model_alias = context.payload.model_alias
        common = {
            "logical_model": model_alias,
            "synopsis": synopsis,
            "name": name,
            "shot_count": int(resolved_node_config.get("shot_count") or 6),
            "aspect_ratio": str(resolved_node_config.get("aspect_ratio") or "9:16"),
            "reference_images": references,
        }
        if model_alias.startswith("google.image."):
            seed = resolved_node_config.get("seed")
            generated = get_google_generation_services().generate_character(
                **common,
                seed=int(seed) if seed is not None else None,
            )
            provider = "google"
            revision = LIVE_GENERATION_REVISION
        else:
            generated = get_openai_generation_services().generate_character(
                **common,
                quality=str(resolved_node_config.get("quality") or "medium"),
            )
            provider = "openai"
            revision = OPENAI_LIVE_REVISION
        exact_model_id = model_id_for_alias(model_alias) or model_alias
        image_artifacts = [
            create_artifact(
                context.db,
                "Image",
                schema_id="character.view.v1",
                input_artifact_ids=input_artifact_ids,
                input_artifact_roles=input_roles,
                metadata={
                    "experiment_id": context.experiment_id,
                    "request_hash": context.request_hash,
                    "execution_mode": revision,
                    "immutable": True,
                    "source": "character_generation",
                    "provider": provider,
                    "model_alias": model_alias,
                    "exact_model_id": exact_model_id,
                    "filename": f"{name} · {image.role.replace('_', ' ')}",
                    "character_role": image.role,
                    "character_view_index": index,
                    "prompt": image.prompt,
                },
                content=image.data,
                content_type=image.content_type,
                filename=image.filename,
            )
            for index, image in enumerate(generated.images)
        ]
        context.db.flush()
        image_ids = [artifact.id for artifact in image_artifacts]
        manifest = {
            "schema_version": context.definition.artifact_contract.schema_id,
            "name": generated.name,
            "synopsis": generated.synopsis,
            "cover_artifact_id": image_ids[0],
            "reference_image_artifact_ids": input_artifact_ids,
            "images": [
                {"artifact_id": artifact.id, "role": image.role, "prompt": image.prompt}
                for artifact, image in zip(image_artifacts, generated.images, strict=True)
            ],
        }
        character_inputs = [*input_artifact_ids, *image_ids]
        character_roles = {**input_roles, **{image_id: "character_view" for image_id in image_ids}}
        character = create_artifact(
            context.db,
            context.definition.artifact_contract.primary_type,
            schema_id=context.definition.artifact_contract.schema_id,
            input_artifact_ids=character_inputs,
            input_artifact_roles=character_roles,
            metadata={
                "experiment_id": context.experiment_id,
                "request_hash": context.request_hash,
                "execution_mode": revision,
                "immutable": True,
                "source": "node_executor_registry",
                "provider": provider,
                "filename": generated.name,
                "name": generated.name,
                "synopsis": generated.synopsis,
                "cover_artifact_id": image_ids[0],
                "reference_image_artifact_ids": input_artifact_ids,
                "image_artifact_ids": image_ids,
                "image_roles": [image.role for image in generated.images],
                "model_alias": model_alias,
                "exact_model_id": exact_model_id,
                "normalized_config": resolved_node_config,
                "output_role": context.definition.artifact_contract.output_role,
            },
            content=json.dumps(manifest, ensure_ascii=False, separators=(",", ":")).encode(),
            content_type="application/json",
            filename="character.json",
        )
        context.db.flush()
        output = {
            **generated.output,
            "url": artifact_content_url(image_ids[0]),
            "characterId": character.id,
            "imageCount": len(generated.images),
        }
        return NodeExecutionResult(
            output=output,
            output_artifact_ids=[character.id],
            provider_request_id=generated.provider_request_id,
            cost_usd=IMAGE_MODEL_COSTS.get(model_alias, 0.0) * len(generated.images),
            metadata={
                "artifact_type": context.definition.artifact_contract.primary_type,
                "schema_id": context.definition.artifact_contract.schema_id,
                "input_artifact_ids": character_inputs,
                "lineage_roles": character_roles,
                "retryable": True,
                "exact_model_id": exact_model_id,
            },
        )
