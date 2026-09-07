from __future__ import annotations

import os
from typing import Any

from ..contracts import NodeExecutionContext, NodeExecutionResult, NodeExecutor


class LegacyCompatibilityExecutor:
    """Capability registry for immutable contracts naming the legacy executor."""

    def __init__(self, capabilities: tuple[NodeExecutor, ...] = ()) -> None:
        self._capabilities = capabilities

    def supports(self, context: NodeExecutionContext) -> bool:
        return any(_supports(capability, context) for capability in self._capabilities)

    def execute(
        self,
        context: NodeExecutionContext,
        resolved_node_config: dict[str, Any],
        typed_inputs: list[dict[str, Any]],
    ) -> NodeExecutionResult:
        capability = next((item for item in self._capabilities if _supports(item, context)), None)
        if not capability:
            raise RuntimeError("legacy compatibility capability is not registered yet")
        return capability.execute(context, resolved_node_config, typed_inputs)

    @staticmethod
    def runtime_revision(definition: Any, resolved_config: dict[str, Any]) -> str:
        del resolved_config
        schema_id = definition.artifact_contract.schema_id
        if schema_id == "reference.decomposition.v1":
            mode = os.getenv("REFERENCE_ANALYSIS_MODE", "live").strip().lower()
            separator = os.getenv("REFERENCE_AUDIO_SEPARATOR", "demucs").strip().lower()
            return f"reference-analysis.v1:{mode}:{separator}"
        if schema_id == "motion.track.v1":
            return "mediapipe.holistic.v1"
        if schema_id == "subtitle.srt.v1":
            return (
                "google-speech.v4"
                if os.getenv("SUBTITLE_ALIGNMENT_MODE", "live").strip().lower() == "live"
                else "local-media.v1"
            )
        if schema_id == "video.translation.v1":
            return "google-localization.v1"
        return str(definition.execution.revision)


def _supports(executor: NodeExecutor, context: NodeExecutionContext) -> bool:
    supports = getattr(executor, "supports", None)
    return bool(supports(context)) if callable(supports) else False
