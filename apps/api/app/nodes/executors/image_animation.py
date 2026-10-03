from __future__ import annotations

import os

from .contract_capabilities import FixtureProviderCapabilityExecutor
from .video_generation import VideoGenerationCapabilityExecutor


class ImageAnimationError(ValueError):
    retryable = False


class ImageAnimationExecutor(VideoGenerationCapabilityExecutor):
    image_input_mode = "first_frame"

    def supports(self, context):
        return context.model_alias.startswith(tuple(context.definition.execution.model_families))

    @staticmethod
    def runtime_revision(definition, resolved_config):
        mode = os.getenv("GENERATION_PROVIDER_MODE", "live").strip().lower()
        return f"{definition.execution.revision}:{mode}"

    def execute(self, context, config, typed_inputs):
        if not context.prompt.strip():
            raise ImageAnimationError("Image animation requires a connected motion Prompt")
        artifacts = context.require_artifact_store().read_inputs(typed_inputs)
        images = [a for a in artifacts if a.type == "Image"]
        if len(images) != 1 or any(a.type in {"Video", "FinalVideo", "Character"} for a in artifacts):
            raise ImageAnimationError("Image animation requires exactly one starting Image")
        if config["resolution"] == "1080p" and config["duration_seconds"] != 8:
            raise ImageAnimationError("1080p image animation requires an 8-second clip")
        if os.getenv("GENERATION_PROVIDER_MODE", "live").strip().lower() != "live":
            return FixtureProviderCapabilityExecutor().execute(context, config, typed_inputs)
        tasks = context.require_provider_tasks()
        tasks.claim("google", "image-animation", resumable=False)
        try:
            result = super().execute(context, config, typed_inputs)
            tasks.remember("google", "image-animation", result.provider_request_id)
            return result
        except Exception as exc:
            raise ImageAnimationError("Image animation failed after provider submission may have started; inspect the provider operation before resubmitting. " + str(exc)) from exc
