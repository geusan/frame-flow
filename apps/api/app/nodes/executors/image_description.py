from __future__ import annotations

from ...provider_credentials import provider_value

import io
import os

from openai import APIConnectionError, APIStatusError
from PIL import Image, UnidentifiedImageError

from ...providers import model_id_for_alias
from ...providers_openai import get_openai_generation_services
from ..contracts import NodeArtifactWrite, NodeExecutionResult, NodeInputMedia


class ImageDescriptionError(ValueError):
    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


class ImageDescriptionExecutor:
    @staticmethod
    def runtime_revision(definition, resolved_config):
        mode = provider_value("GENERATION_PROVIDER_MODE", "live").strip().lower()
        return f"{definition.execution.revision}:{mode}"

    def execute(self, context, config, typed_inputs):
        store = context.require_artifact_store()
        artifacts = store.read_inputs(typed_inputs)
        images = [item for item in artifacts if item.type == "Image"]
        if len(images) != 1 or any(item.type not in {"Image", "Text", "Prompt"} for item in artifacts):
            raise ImageDescriptionError("Image description requires exactly one Image")
        source = images[0]
        artifact_ids = [item.id for item in artifacts]
        roles = {item.id: context.definition.artifact_contract.input_roles["media.image.v1" if item.type == "Image" else "prompt.text.v1"] for item in artifacts}
        if source.content_type not in {"image/png", "image/jpeg", "image/webp", "image/gif"}:
            raise ImageDescriptionError("Image description supports PNG, JPEG, WEBP or a non-animated GIF")
        try:
            with Image.open(io.BytesIO(source.data)) as image:
                if getattr(image, "n_frames", 1) != 1:
                    raise ImageDescriptionError("Image description requires a single still image")
                image.verify()
        except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError) as exc:
            raise ImageDescriptionError("Image description input is not a valid image") from exc
        exact_model = model_id_for_alias(context.model_alias)
        if not exact_model or not context.model_alias.startswith(tuple(context.definition.execution.model_families)):
            raise ImageDescriptionError("Image description requires a registered OpenAI text/vision model")
        mode = provider_value("GENERATION_PROVIDER_MODE", "live").strip().lower()
        context.report_progress(15, "Reading the reference image's action, pose and contact points")
        if mode == "fixture" and provider_value("APP_ENV") == "test":
            observation = "Fixture image description: a subject is performing the action shown in the supplied image."
            request_id = "fixture_vision_" + context.request_hash[:16]
            provider_metadata = {"usage": {}, "response_model": exact_model}
        elif mode == "live":
            try:
                observation, request_id, provider_metadata = get_openai_generation_services().generate_vision_text(
                    logical_model=context.model_alias, instructions=config["instructions"],
                    images=[NodeInputMedia(source.id, "Image", source.data, source.content_type)],
                    detail=config["image_detail"], max_output_tokens=config["max_output_tokens"],
                )
            except APIStatusError as exc:
                raise ImageDescriptionError(f"Image description provider returned HTTP {exc.status_code}", retryable=exc.status_code in {408, 409, 429} or exc.status_code >= 500) from exc
            except APIConnectionError as exc:
                raise ImageDescriptionError("Image description provider could not be reached", retryable=True) from exc
            except ValueError as exc:
                raise ImageDescriptionError(str(exc)) from exc
        else:
            raise ImageDescriptionError("Fixture image description is available only in the test environment")
        text = f"Observed reference image:\n{observation.strip()}"
        if context.prompt.strip():
            text += f"\n\nDownstream generation constraints (verbatim):\n{context.prompt.strip()}"
        revision = self.runtime_revision(context.definition, config)
        metadata = {
            "source": "node_executor_registry", "immutable": True,
            "experiment_id": context.experiment_id, "request_hash": context.request_hash,
            "definition_digest": context.definition.definition_digest, "executor_revision": revision,
            "execution_mode": revision, "provider": "openai", "model_alias": context.model_alias,
            "exact_model_id": exact_model, "normalized_config": config,
            "output_role": context.definition.artifact_contract.output_role,
            "cost_status": "fixture" if mode == "fixture" else "provider_billed_unreported",
            **provider_metadata,
        }
        artifact = store.create(NodeArtifactWrite(
            artifact_type="Text", schema_id=context.definition.artifact_contract.schema_id,
            content=text.encode(), content_type="text/plain", filename="image-description.txt",
            input_artifact_ids=artifact_ids, input_artifact_roles=roles, metadata=metadata,
        ))
        store.flush()
        return NodeExecutionResult(
            output={"kind": "text", "title": "Image action and pose description", "text": text},
            output_artifact_ids=[artifact.id], provider_request_id=request_id, cost_usd=0,
            metadata={"artifact_type": "Text", "schema_id": context.definition.artifact_contract.schema_id,
                      "input_artifact_ids": artifact_ids, "lineage_roles": roles, "retryable": False,
                      "exact_model_id": exact_model, "cost_status": metadata["cost_status"], **provider_metadata},
        )
