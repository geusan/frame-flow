from __future__ import annotations

from sqlalchemy.orm import Session

from ...database import ArtifactRecord
from ...nodes.contracts import (
    NodeArtifactContent,
    NodeArtifactRef,
    NodeArtifactSnapshot,
    NodeArtifactWrite,
    NodeDefinition,
    NodeInputMedia,
)
from ...nodes.port_types import port_type_registry
from ...service import create_artifact
from ...storage import artifact_content_url, get_storage, storage_location


class SqlAlchemyNodeArtifactStore:
    def __init__(self, session: Session) -> None:
        self._session = session

    def load_input_media(
        self,
        definition: NodeDefinition,
        typed_inputs: list[dict],
        *,
        expand_characters: bool = True,
    ) -> tuple[list[NodeInputMedia], list[str], dict[str, str]]:
        storage = get_storage()
        media: list[NodeInputMedia] = []
        artifact_ids: list[str] = []
        roles: dict[str, str] = {}

        def append_artifact(artifact_id: str, role: str) -> None:
            if artifact_id in artifact_ids:
                return
            artifact = self._session.get(ArtifactRecord, artifact_id)
            if artifact is None:
                raise ValueError(f"input artifact does not exist: {artifact_id}")
            bucket, key = storage_location(artifact.uri, artifact.metadata_json)
            content_type = str(
                (artifact.metadata_json.get("storage") or {}).get("content_type")
                or "application/octet-stream"
            )
            media.append(
                NodeInputMedia(
                    artifact_id=artifact.id,
                    artifact_type=artifact.type,
                    data=storage.get_bytes(bucket=bucket, key=key),
                    content_type=content_type,
                )
            )
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
                (
                    candidate
                    for candidate in definition.ports.inputs
                    if port_type_registry.get(candidate.type).legacy_type == legacy_type
                ),
                None,
            )
            role = (
                definition.artifact_contract.input_roles.get(
                    port.type,
                    "supporting_input",
                )
                if port
                else "supporting_input"
            )
            values = [
                *(item.get("artifact_ids") or []),
                *([item.get("artifact_id")] if item.get("artifact_id") else []),
            ]
            for value in values:
                append_artifact(str(value), role)
        return media, artifact_ids, roles

    def read(self, artifact_id: str) -> NodeArtifactContent:
        artifact = self._session.get(ArtifactRecord, artifact_id)
        if artifact is None:
            raise ValueError(f"input artifact does not exist: {artifact_id}")
        storage = get_storage()
        bucket, key = storage_location(artifact.uri, artifact.metadata_json)
        content_type = str(
            (artifact.metadata_json.get("storage") or {}).get("content_type")
            or "application/octet-stream"
        )
        return NodeArtifactContent(
            record=NodeArtifactSnapshot(
                id=artifact.id,
                type=artifact.type,
                metadata=dict(artifact.metadata_json or {}),
            ),
            data=storage.get_bytes(bucket=bucket, key=key),
            content_type=content_type,
        )

    def read_inputs(
        self,
        typed_inputs: list[dict],
    ) -> list[NodeArtifactContent]:
        artifact_ids: list[str] = []
        for item in typed_inputs:
            values = [
                *(item.get("artifact_ids") or []),
                *([item.get("artifact_id")] if item.get("artifact_id") else []),
            ]
            for value in values:
                artifact_id = str(value)
                if artifact_id and artifact_id not in artifact_ids:
                    artifact_ids.append(artifact_id)
        return [self.read(artifact_id) for artifact_id in artifact_ids]

    def create(self, write: NodeArtifactWrite) -> NodeArtifactRef:
        artifact = create_artifact(
            self._session,
            write.artifact_type,
            schema_id=write.schema_id,
            input_artifact_ids=write.input_artifact_ids,
            input_artifact_roles=write.input_artifact_roles,
            metadata=write.metadata,
            content=write.content,
            content_type=write.content_type,
            filename=write.filename,
        )
        return NodeArtifactRef(id=artifact.id, type=artifact.type)

    def flush(self) -> None:
        self._session.flush()

    def content_url(self, artifact_id: str) -> str:
        return artifact_content_url(artifact_id)
