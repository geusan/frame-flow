from __future__ import annotations

from sqlalchemy.orm import Session

from ...database import ArtifactRecord
from ...providers_generation import InputMedia
from ...storage import get_storage, storage_location
from ..contracts import NodeDefinition
from ..port_types import port_type_registry


def load_input_media(
    db: Session,
    definition: NodeDefinition,
    typed_inputs: list[dict],
    *,
    expand_characters: bool = True,
) -> tuple[list[InputMedia], list[str], dict[str, str]]:
    storage = get_storage()
    media: list[InputMedia] = []
    artifact_ids: list[str] = []
    roles: dict[str, str] = {}

    def append_artifact(artifact_id: str, role: str) -> None:
        if artifact_id in artifact_ids:
            return
        artifact = db.get(ArtifactRecord, artifact_id)
        if not artifact:
            raise ValueError(f"input artifact does not exist: {artifact_id}")
        bucket, key = storage_location(artifact.uri, artifact.metadata_json)
        content_type = str((artifact.metadata_json.get("storage") or {}).get("content_type") or "application/octet-stream")
        media.append(InputMedia(artifact.id, artifact.type, storage.get_bytes(bucket=bucket, key=key), content_type))
        artifact_ids.append(artifact.id)
        roles[artifact.id] = role
        if expand_characters and artifact.type == "Character":
            image_ids = [
                *(artifact.metadata_json.get("reference_image_artifact_ids") or []),
                *(artifact.metadata_json.get("image_artifact_ids") or []),
            ]
            for image_id in image_ids:
                append_artifact(str(image_id), "character_reference")

    for item in typed_inputs:
        legacy_type = str(item.get("type") or "")
        port = next(
            (candidate for candidate in definition.ports.inputs if port_type_registry.get(candidate.type).legacy_type == legacy_type),
            None,
        )
        role = definition.artifact_contract.input_roles.get(port.type, "supporting_input") if port else "supporting_input"
        values = [*(item.get("artifact_ids") or []), *([item.get("artifact_id")] if item.get("artifact_id") else [])]
        for value in values:
            append_artifact(str(value), role)
    return media, artifact_ids, roles
