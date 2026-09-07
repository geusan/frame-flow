from __future__ import annotations

from sqlalchemy.orm import Session

from ...character_lora import (
    character_lora_state,
    require_character,
    start_character_lora_training,
    wait_for_character_lora_training,
)
from ...nodes.contracts import (
    NodeArtifactSnapshot,
    NodeCharacterLoraResult,
)


class SqlAlchemyNodeCharacterLoraRuntime:
    def __init__(self, session: Session) -> None:
        self._session = session

    def ensure_ready(
        self,
        character_id: str,
        *,
        trigger_word: str,
        steps: int,
        learning_rate: float,
        timeout_seconds: int,
    ) -> NodeCharacterLoraResult:
        character = require_character(self._session, character_id)
        metadata = character.metadata_json or {}
        ready = str(metadata.get("lora_status") or "").upper() == "READY"
        matching_trigger = str(metadata.get("lora_trigger_word") or "") == trigger_word
        if not (
            ready
            and matching_trigger
            and metadata.get("lora_artifact_id")
            and metadata.get("lora_url")
        ):
            running = str(metadata.get("lora_status") or "").upper() in {
                "IN_QUEUE",
                "IN_PROGRESS",
            }
            if running and not matching_trigger:
                raise ValueError(
                    "Connected Character is already training with a different trigger word"
                )
            if running:
                try:
                    state = wait_for_character_lora_training(
                        self._session,
                        character.id,
                        timeout_seconds=timeout_seconds,
                    )
                except RuntimeError:
                    character = require_character(self._session, character.id)
                    if (
                        str(
                            (character.metadata_json or {}).get("lora_status") or ""
                        ).upper()
                        != "FAILED"
                    ):
                        raise
                    running = False
            if not running:
                start_character_lora_training(
                    self._session,
                    character.id,
                    trigger_word=trigger_word,
                    steps=steps,
                    learning_rate=learning_rate,
                )
                state = wait_for_character_lora_training(
                    self._session,
                    character.id,
                    timeout_seconds=timeout_seconds,
                )
            character = require_character(self._session, character.id)
        else:
            state = character_lora_state(character)
        return NodeCharacterLoraResult(
            character=NodeArtifactSnapshot(
                id=character.id,
                type=character.type,
                schema_id=character.schema_id,
                sha256=character.sha256,
                metadata=dict(character.metadata_json or {}),
            ),
            state=state,
        )
