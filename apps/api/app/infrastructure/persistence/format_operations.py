from __future__ import annotations

import json
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...contexts.formats.application import (
    CreateExtractionRecipeCommand,
    CreateFormatRunCommand,
    CreateVariantsCommand,
    MergeFormatsCommand,
)
from ...contexts.formats.domain import FormatNotFoundError, FormatValidationError
from ...database import (
    ArtifactRecord,
    DefinitionRecord,
    FormatRecord,
    ReferenceRecord,
    ReferenceSetRecord,
    SessionLocal,
)
from ...domain import ExtractionRecipeRequest, FormatRunRequest, MergeRequest, VariationRequest
from ...format_extraction import FormatSource, get_format_extractor
from ...service import create_artifact, new_id
from ...storage import get_artifact_storage, storage_location


class LegacySqlAlchemyFormatOperations:
    """Strangler adapter around Format extraction and persistence."""

    def __init__(
        self,
        session_factory: Callable[[], Session] = SessionLocal,
    ) -> None:
        self._session_factory = session_factory

    def create_recipe(
        self,
        command: CreateExtractionRecipeCommand,
    ) -> dict[str, Any]:
        payload = ExtractionRecipeRequest.model_validate(command.values)
        with self._session_factory() as db:
            record = DefinitionRecord(
                id=new_id("recipe"),
                kind="extraction_recipe",
                version=payload.version,
                payload=payload.model_dump(mode="json"),
            )
            db.add(record)
            db.commit()
            return {"id": record.id, **record.payload}

    def create_run(self, command: CreateFormatRunCommand) -> dict[str, Any]:
        payload = FormatRunRequest.model_validate(command.values)
        with self._session_factory() as db:
            reference_set = db.get(ReferenceSetRecord, payload.reference_set_id)
            if reference_set is None:
                raise FormatNotFoundError("reference set not found")
            references = [
                db.get(ReferenceRecord, reference_id)
                for reference_id in reference_set.reference_ids
            ]
            if any(reference is None for reference in references):
                raise FormatNotFoundError(
                    "reference set contains a missing reference"
                )
            proxy_artifacts = db.scalars(
                select(ArtifactRecord).where(ArtifactRecord.type == "ProxyVideo")
            ).all()
            proxy_by_reference = {
                str(artifact.metadata_json.get("reference_id")): artifact
                for artifact in proxy_artifacts
                if artifact.metadata_json.get("reference_id")
            }
            sources: list[FormatSource] = []
            for reference in references:
                assert reference is not None
                proxy = proxy_by_reference.get(reference.id)
                if proxy is None:
                    raise FormatValidationError(
                        f"reference has no ProxyVideo artifact: {reference.id}"
                    )
                storage = get_artifact_storage(proxy.uri, proxy.metadata_json)
                bucket, key = storage_location(proxy.uri, proxy.metadata_json)
                sources.append(
                    FormatSource(
                        reference.id,
                        reference.title,
                        reference.creator,
                        reference.duration_ms,
                        storage.get_bytes(bucket=bucket, key=key),
                        str(
                            (proxy.metadata_json.get("storage") or {}).get(
                                "content_type"
                            )
                            or "video/mp4"
                        ),
                    )
                )
            try:
                extracted = get_format_extractor().extract(sources)
            except Exception as exc:
                raise FormatValidationError(str(exc)) from exc
            record = FormatRecord(
                id=new_id("fmt"),
                name=payload.name,
                kind="profile",
                parent_ids=reference_set.reference_ids,
                payload=extracted.profile.model_dump(mode="json"),
                lineage={
                    "recipe_id": payload.recipe_id,
                    "recipe_version": payload.recipe_version,
                    "provider_request_id": extracted.provider_request_id,
                    "exact_model_id": extracted.exact_model_id,
                },
            )
            db.add(record)
            content = json.dumps(
                record.payload,
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
            ).encode()
            artifact = create_artifact(
                db,
                "FormatProfile",
                schema_id="format.profile.v1",
                content=content,
                content_type="application/json",
                filename="format-profile.json",
                input_artifact_ids=[
                    proxy_by_reference[reference_id].id
                    for reference_id in reference_set.reference_ids
                ],
                metadata={
                    "format_id": record.id,
                    "provider_request_id": extracted.provider_request_id,
                },
            )
            db.commit()
            return {
                "id": record.id,
                "name": record.name,
                "kind": record.kind,
                "payload": record.payload,
                "lineage": record.lineage,
                "artifact_id": artifact.id,
            }

    def get(self, format_id: str) -> dict[str, Any]:
        with self._session_factory() as db:
            record = db.get(FormatRecord, format_id)
            if record is None:
                raise FormatNotFoundError("format not found")
            return {
                "id": record.id,
                "name": record.name,
                "kind": record.kind,
                "parent_ids": record.parent_ids,
                "payload": record.payload,
                "lineage": record.lineage,
            }

    def list(self) -> list[dict[str, Any]]:
        with self._session_factory() as db:
            rows = db.scalars(
                select(FormatRecord).order_by(FormatRecord.created_at.desc())
            ).all()
            return [
                {
                    "id": row.id,
                    "created_at": row.created_at,
                    "name": row.name,
                    "kind": row.kind,
                    "parent_ids": row.parent_ids,
                    "payload": row.payload,
                    "lineage": row.lineage,
                }
                for row in rows
            ]

    def create_variants(
        self,
        command: CreateVariantsCommand,
    ) -> list[dict[str, Any]]:
        payload = VariationRequest.model_validate(command.values)
        with self._session_factory() as db:
            parent = db.get(FormatRecord, command.format_id)
            if parent is None:
                raise FormatNotFoundError("format not found")
            results = []
            for index in range(payload.count):
                variant_payload = json.loads(json.dumps(parent.payload))
                previous = variant_payload["core"]["visual"]["motion_intensity"]
                new_value = round(min(1, previous + (index + 1) * 0.04), 2)
                variant_payload["core"]["visual"]["motion_intensity"] = new_value
                record = FormatRecord(
                    id=new_id("fmtvar"),
                    name=f"{parent.name} · Variant {index + 1}",
                    kind="variant",
                    parent_ids=[parent.id],
                    payload=variant_payload,
                    lineage={
                        "variation_recipe": payload.model_dump(mode="json"),
                        "diff": [
                            {
                                "field": "core.visual.motion_intensity",
                                "previous": previous,
                                "value": new_value,
                                "reason": "diversity axis",
                            }
                        ],
                    },
                )
                db.add(record)
                results.append(
                    {
                        "id": record.id,
                        "name": record.name,
                        "diff": record.lineage["diff"],
                    }
                )
            db.commit()
            return results

    def merge(self, command: MergeFormatsCommand) -> dict[str, Any]:
        payload = MergeRequest.model_validate(command.values)
        with self._session_factory() as db:
            rows = [
                db.get(FormatRecord, source.format_id) for source in payload.sources
            ]
            if any(row is None for row in rows):
                raise FormatNotFoundError("one or more formats were not found")
            formats = [row for row in rows if row is not None]
            merged = json.loads(json.dumps(formats[0].payload))
            total_weight = sum(source.weight for source in payload.sources) or 1
            fields = ["median_shot_duration_ms", "cuts_per_10_seconds"]
            lineage: dict[str, Any] = {}
            for field in fields:
                value = (
                    sum(
                        float(row.payload["core"]["editing"][field])
                        * source.weight
                        for row, source in zip(
                            formats,
                            payload.sources,
                            strict=True,
                        )
                    )
                    / total_weight
                )
                merged["core"]["editing"][field] = round(value, 2)
                lineage[f"core.editing.{field}"] = {
                    "value": round(value, 2),
                    "sources": [source.model_dump() for source in payload.sources],
                    "strategy": payload.default_strategy,
                }
            record = FormatRecord(
                id=new_id("fmtmerge"),
                name=payload.name,
                kind="composition",
                parent_ids=[source.format_id for source in payload.sources],
                payload=merged,
                lineage=lineage,
            )
            db.add(record)
            db.commit()
            return {
                "id": record.id,
                "name": record.name,
                "kind": record.kind,
                "payload": record.payload,
                "lineage": record.lineage,
            }
