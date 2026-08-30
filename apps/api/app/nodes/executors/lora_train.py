from __future__ import annotations

from typing import Any

from ...character_lora import (
    character_lora_state,
    require_character,
    start_character_lora_training,
    wait_for_character_lora_training,
)
from ...database import ArtifactRecord
from ...storage import artifact_content_url
from ..contracts import NodeExecutionContext, NodeExecutionResult


class FalLoraTrainingExecutor:
    def execute(
        self,
        context: NodeExecutionContext,
        resolved_node_config: dict[str, Any],
        typed_inputs: list[dict[str, Any]],
    ) -> NodeExecutionResult:
        character = self._resolve_character(context, typed_inputs)
        trigger_word = str(resolved_node_config["trigger_word"])
        metadata = character.metadata_json or {}
        ready = str(metadata.get("lora_status") or "").upper() == "READY"
        matching_trigger = str(metadata.get("lora_trigger_word") or "") == trigger_word
        if not (ready and matching_trigger and metadata.get("lora_artifact_id") and metadata.get("lora_url")):
            running = str(metadata.get("lora_status") or "").upper() in {"IN_QUEUE", "IN_PROGRESS"}
            if running and not matching_trigger:
                raise ValueError("Connected Character is already training with a different trigger word")
            if running:
                try:
                    state = wait_for_character_lora_training(
                        context.db,
                        character.id,
                        timeout_seconds=int(resolved_node_config["timeout_seconds"]),
                    )
                except RuntimeError:
                    character = require_character(context.db, character.id)
                    if str((character.metadata_json or {}).get("lora_status") or "").upper() != "FAILED":
                        raise
                    running = False
            if not running:
                start_character_lora_training(
                    context.db,
                    character.id,
                    trigger_word=trigger_word,
                    steps=int(resolved_node_config["steps"]),
                    learning_rate=float(resolved_node_config["learning_rate"]),
                )
                state = wait_for_character_lora_training(
                    context.db,
                    character.id,
                    timeout_seconds=int(resolved_node_config["timeout_seconds"]),
                )
            character = require_character(context.db, character.id)
        else:
            state = character_lora_state(character)
        metadata = character.metadata_json or {}
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
            output["url"] = artifact_content_url(cover_id)
        return NodeExecutionResult(
            output=output,
            output_artifact_ids=output_ids,
            provider_request_id=str(state.get("request_id") or ""),
            metadata={"lora_artifact_id": lora_artifact_id, "weights_url": state.get("weights_url")},
        )

    @staticmethod
    def _resolve_character(context: NodeExecutionContext, typed_inputs: list[dict[str, Any]]) -> ArtifactRecord:
        for item in typed_inputs:
            if str(item.get("type") or "") != "Character":
                continue
            artifact_ids = [*(item.get("artifact_ids") or []), *([item.get("artifact_id")] if item.get("artifact_id") else [])]
            for artifact_id in artifact_ids:
                character = context.db.get(ArtifactRecord, str(artifact_id))
                if character and character.type == "Character":
                    return character
        raise ValueError("LoRA Trainer requires a connected Character artifact")
