from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from ..domain import BinaryContent, StoredContent

if TYPE_CHECKING:
    from .ports import ArtifactOperations


@dataclass(frozen=True)
class TrainCharacterLoraCommand:
    character_id: str
    trigger_word: str
    steps: int
    learning_rate: float


@dataclass(frozen=True)
class SceneSearchCommand:
    artifact_id: str
    values: dict[str, Any]


@dataclass(frozen=True)
class CaptureFrameCommand:
    artifact_id: str
    values: dict[str, Any]


@dataclass(frozen=True)
class ImportArtifactUrlCommand:
    url: str


@dataclass(frozen=True)
class UploadArtifactCommand:
    filename: str
    content_type: str
    content: bytes


@dataclass(frozen=True)
class SaveImageEditCommand:
    artifact_id: str
    filename: str
    content_type: str
    content: bytes
    document: dict[str, Any]


class ArtifactApplication:
    def __init__(self, operations: "ArtifactOperations") -> None:
        self._operations = operations

    def list_artifacts(self, types: str, limit: int, offset: int) -> list[dict[str, Any]]:
        return self._operations.list_artifacts(types, limit, offset)

    def list_characters(self) -> list[dict[str, Any]]:
        return self._operations.list_characters()

    def start_character_lora(self, command: TrainCharacterLoraCommand) -> dict[str, Any]:
        return self._operations.start_character_lora(command)

    def get_character_lora(self, character_id: str) -> dict[str, Any]:
        return self._operations.get_character_lora(character_id)

    def get_artifact(self, artifact_id: str) -> Any:
        return self._operations.get_artifact(artifact_id)

    def create_audio_asset(self, artifact_id: str) -> dict[str, Any]:
        return self._operations.create_audio_asset(artifact_id)

    def get_lineage(
        self,
        artifact_id: str,
        direction: Literal["ancestors", "descendants", "both"],
        depth: int,
    ) -> dict[str, object]:
        return self._operations.get_lineage(artifact_id, direction, depth)

    def search_scenes(self, command: SceneSearchCommand) -> dict[str, object]:
        return self._operations.search_scenes(command)

    def capture_frame(self, command: CaptureFrameCommand) -> dict[str, Any]:
        return self._operations.capture_frame(command)

    def preview_frame(self, artifact_id: str, timestamp_ms: int) -> BinaryContent:
        return self._operations.preview_frame(artifact_id, timestamp_ms)

    def create_upload_target(self, filename: str, content_type: str) -> dict[str, Any]:
        return self._operations.create_upload_target(filename, content_type)

    def import_url(self, command: ImportArtifactUrlCommand) -> dict[str, Any]:
        return self._operations.import_url(command)

    def upload(self, command: UploadArtifactCommand) -> dict[str, Any]:
        return self._operations.upload(command)

    def save_image_edit(self, command: SaveImageEditCommand) -> dict[str, Any]:
        return self._operations.save_image_edit(command)

    def create_download_url(self, artifact_id: str) -> dict[str, Any]:
        return self._operations.create_download_url(artifact_id)

    def get_content(self, artifact_id: str) -> StoredContent:
        return self._operations.get_content(artifact_id)
