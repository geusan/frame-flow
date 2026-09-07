from __future__ import annotations

from typing import Any, Literal, Protocol

from ....domain import ArtifactResponse
from ..domain import BinaryContent, StoredContent
from .use_cases import (
    CaptureFrameCommand,
    ImportArtifactUrlCommand,
    SaveImageEditCommand,
    SceneSearchCommand,
    TrainCharacterLoraCommand,
    UploadArtifactCommand,
)


class ArtifactOperations(Protocol):
    def list_artifacts(
        self,
        types: str,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]: ...

    def list_characters(self) -> list[dict[str, Any]]: ...

    def start_character_lora(self, command: TrainCharacterLoraCommand) -> dict[str, Any]: ...

    def get_character_lora(self, character_id: str) -> dict[str, Any]: ...

    def get_artifact(self, artifact_id: str) -> ArtifactResponse: ...

    def create_audio_asset(self, artifact_id: str) -> dict[str, Any]: ...

    def get_lineage(
        self,
        artifact_id: str,
        direction: Literal["ancestors", "descendants", "both"],
        depth: int,
    ) -> dict[str, object]: ...

    def search_scenes(self, command: SceneSearchCommand) -> dict[str, object]: ...

    def capture_frame(self, command: CaptureFrameCommand) -> dict[str, Any]: ...

    def preview_frame(self, artifact_id: str, timestamp_ms: int) -> BinaryContent: ...

    def create_upload_target(self, filename: str, content_type: str) -> dict[str, Any]: ...

    def import_url(self, command: ImportArtifactUrlCommand) -> dict[str, Any]: ...

    def upload(self, command: UploadArtifactCommand) -> dict[str, Any]: ...

    def save_image_edit(self, command: SaveImageEditCommand) -> dict[str, Any]: ...

    def create_download_url(self, artifact_id: str) -> dict[str, Any]: ...

    def get_content(self, artifact_id: str) -> StoredContent: ...
