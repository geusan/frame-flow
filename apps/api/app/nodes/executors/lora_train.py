from __future__ import annotations

from typing import Any

from ..contracts import NodeArtifactSnapshot, NodeExecutionContext, NodeExecutionResult


class FalLoraTrainingExecutor:
    def execute(
        self,
        context: NodeExecutionContext,
        resolved_node_config: dict[str, Any],
        typed_inputs: list[dict[str, Any]],
    ) -> NodeExecutionResult:
        character = self._resolve_character(context, typed_inputs)
        trigger_word = str(resolved_node_config["trigger_word"])
        result = context.require_character_lora_runtime().ensure_ready(
            character.id,
            trigger_word=trigger_word,
            steps=int(resolved_node_config["steps"]),
            learning_rate=float(resolved_node_config["learning_rate"]),
            timeout_seconds=int(resolved_node_config["timeout_seconds"]),
        )
        character = result.character
        state = result.state
        metadata = character.metadata
        cover_id = str(metadata.get("cover_artifact_id") or "")
        lora_artifact_id = str(state.get("lora_artifact_id") or "")
        output_ids = [character.id, *([lora_artifact_id] if lora_artifact_id else [])]
        name = str(metadata.get("name") or metadata.get("filename") or "Character")
        output: dict[str, object] = {
            "kind": "image",
            "title": f"{name} · LoRA ready",
            "characterId": character.id,
            "text": f"Trigger: {state.get('trigger_word') or trigger_word}",
        }
        if cover_id:
            output["url"] = context.require_artifact_store().content_url(cover_id)
        return NodeExecutionResult(
            output=output,
            output_artifact_ids=output_ids,
            provider_request_id=str(state.get("request_id") or ""),
            metadata={"lora_artifact_id": lora_artifact_id, "weights_url": state.get("weights_url")},
        )

    @staticmethod
    def _resolve_character(context: NodeExecutionContext, typed_inputs: list[dict[str, Any]]) -> NodeArtifactSnapshot:
        artifact_store = context.require_artifact_store()
        for item in typed_inputs:
            if str(item.get("type") or "") != "Character":
                continue
            artifact_ids = [*(item.get("artifact_ids") or []), *([item.get("artifact_id")] if item.get("artifact_id") else [])]
            for artifact_id in artifact_ids:
                character = artifact_store.read(str(artifact_id)).record
                if character.type == "Character":
                    return character
        raise ValueError("LoRA Trainer requires a connected Character artifact")
