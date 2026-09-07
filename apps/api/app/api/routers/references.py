from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...database import ArtifactRecord, ReferenceRecord, ReferenceSetRecord, get_db
from ...domain import (
    ReferenceImportRequest,
    ReferenceInspectRequest,
    ReferenceMetadata,
    ReferenceSetRequest,
)
from ...reference_ingest import ReferenceIngestError, get_reference_provider, render_proxy
from ...service import audit, canonicalize_url, create_artifact, new_id
from ...storage import artifact_content_url


router = APIRouter(tags=["references"])


@router.post("/references/inspect", response_model=list[ReferenceMetadata])
def inspect_references(
    payload: ReferenceInspectRequest,
    db: Session = Depends(get_db),
) -> list[ReferenceMetadata]:
    results: list[ReferenceMetadata] = []
    provider = get_reference_provider()
    for raw_url in payload.urls:
        try:
            inspected = provider.inspect(str(raw_url))
            canonical = canonicalize_url(inspected.canonical_url)
        except (ValueError, ReferenceIngestError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        existing = db.scalar(
            select(ReferenceRecord).where(ReferenceRecord.canonical_url == canonical)
        )
        results.append(
            ReferenceMetadata(
                canonical_url=canonical,
                source_id=inspected.source_id,
                title=inspected.title,
                creator=inspected.creator,
                duration_ms=inspected.duration_ms,
                width=inspected.width,
                height=inspected.height,
                has_subtitles=inspected.has_subtitles,
                estimated_bytes=inspected.estimated_bytes,
                thumbnail_url=inspected.thumbnail_url,
                duplicate_reference_id=existing.id if existing else None,
            )
        )
    return results


@router.post("/references/import", status_code=status.HTTP_201_CREATED)
def import_reference(
    payload: ReferenceImportRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        canonical = canonicalize_url(payload.metadata.canonical_url)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(422, str(exc)) from exc
    existing = db.scalar(
        select(ReferenceRecord).where(ReferenceRecord.canonical_url == canonical)
    )
    if existing:
        return {"reference_id": existing.id, "deduplicated": True, "artifact_ids": []}
    provider = get_reference_provider()
    try:
        inspected = provider.inspect(canonical)
        downloaded = provider.download(canonical, max_duration_seconds=600)
        proxy = render_proxy(downloaded.video)
    except ReferenceIngestError as exc:
        raise HTTPException(422, str(exc)) from exc
    reference = ReferenceRecord(
        id=new_id("ref"),
        canonical_url=canonical,
        source_id=inspected.source_id,
        title=inspected.title,
        creator=inspected.creator,
        duration_ms=inspected.duration_ms,
        rights_basis=payload.rights_basis,
        allow_generation_input=payload.allow_generation_input,
        allow_direct_asset_use=payload.allow_direct_asset_use,
        status="ready",
        metadata_json={
            **payload.metadata.model_dump(mode="json"),
            "inspected": inspected.__dict__,
        },
    )
    db.add(reference)
    artifacts = [
        create_artifact(
            db,
            "ReferenceOriginal",
            metadata={
                "access_scope": "reference-analyzer-only",
                "reference_id": reference.id,
            },
            content=downloaded.video,
            content_type=downloaded.video_content_type,
            filename="original.mp4",
        ),
        create_artifact(
            db,
            "ProxyVideo",
            metadata={"width": 540, "height": 960, "reference_id": reference.id},
            content=proxy,
            content_type="video/mp4",
            filename="proxy.mp4",
        ),
        create_artifact(
            db,
            "Thumbnail",
            metadata={"reference_id": reference.id},
            content=downloaded.thumbnail,
            content_type=downloaded.thumbnail_content_type,
            filename=f"thumbnail.{downloaded.thumbnail_content_type.split('/')[-1]}",
        ),
    ]
    if downloaded.subtitle:
        artifacts.append(
            create_artifact(
                db,
                "Subtitle",
                schema_id="subtitle.source.v1",
                metadata={"reference_id": reference.id},
                content=downloaded.subtitle,
                content_type=(
                    downloaded.subtitle_content_type or "application/x-subrip"
                ),
                filename="subtitle.srt",
            )
        )
    audit(db, "reference.imported", reference.id, {"rights_basis": payload.rights_basis})
    db.commit()
    return {
        "reference_id": reference.id,
        "deduplicated": False,
        "artifact_ids": [artifact.id for artifact in artifacts],
    }


@router.get("/references")
def list_references(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(ReferenceRecord).order_by(ReferenceRecord.created_at.desc())
    ).all()
    thumbnails = db.scalars(
        select(ArtifactRecord).where(ArtifactRecord.type == "Thumbnail")
    ).all()
    thumbnail_by_reference = {
        str(artifact.metadata_json.get("reference_id")): artifact.id
        for artifact in thumbnails
        if artifact.metadata_json.get("reference_id")
    }
    return [
        {
            "id": row.id,
            "created_at": row.created_at,
            "title": row.title,
            "creator": row.creator,
            "duration_ms": row.duration_ms,
            "rights_basis": row.rights_basis,
            "allow_generation_input": row.allow_generation_input,
            "status": row.status,
            "metadata": row.metadata_json,
            "thumbnail_url": (
                artifact_content_url(thumbnail_by_reference[row.id])
                if row.id in thumbnail_by_reference
                else None
            ),
        }
        for row in rows
    ]


@router.post("/reference-sets", status_code=201)
def create_reference_set(
    payload: ReferenceSetRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    known = set(
        db.scalars(
            select(ReferenceRecord.id).where(
                ReferenceRecord.id.in_(payload.reference_ids)
            )
        ).all()
    )
    missing = set(payload.reference_ids) - known
    if missing:
        raise HTTPException(404, f"unknown references: {sorted(missing)}")
    record = ReferenceSetRecord(
        id=new_id("refset"),
        name=payload.name,
        reference_ids=payload.reference_ids,
    )
    db.add(record)
    db.commit()
    return {
        "id": record.id,
        "name": record.name,
        "reference_ids": record.reference_ids,
    }
