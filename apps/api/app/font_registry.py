from __future__ import annotations

import hashlib
import re
import struct
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import ArtifactRecord, FontRecord
from .domain import utc_now
from .service import audit, create_artifact, new_id
from .storage import artifact_content_url


FONT_MAX_BYTES = 24 * 1024 * 1024
FONT_MIME_TYPES = {
    "font/ttf": "font/ttf",
    "font/otf": "font/otf",
    "application/font-sfnt": "application/font-sfnt",
    "application/x-font-ttf": "font/ttf",
    "application/x-font-opentype": "font/otf",
    "application/octet-stream": "application/octet-stream",
}


@dataclass(frozen=True)
class InspectedFont:
    family_name: str
    subfamily_name: str
    postscript_name: str
    weight: int
    style: str
    metrics: dict[str, int | float | None]


def _u16(data: bytes, offset: int) -> int:
    if offset < 0 or offset + 2 > len(data):
        raise ValueError("font table is truncated")
    return struct.unpack_from(">H", data, offset)[0]


def _i16(data: bytes, offset: int) -> int:
    if offset < 0 or offset + 2 > len(data):
        raise ValueError("font table is truncated")
    return struct.unpack_from(">h", data, offset)[0]


def _u32(data: bytes, offset: int) -> int:
    if offset < 0 or offset + 4 > len(data):
        raise ValueError("font table is truncated")
    return struct.unpack_from(">I", data, offset)[0]


def _font_tables(content: bytes) -> dict[str, bytes]:
    if len(content) < 12 or content[:4] not in {b"\x00\x01\x00\x00", b"OTTO", b"true", b"typ1"}:
        if content[:4] == b"ttcf":
            raise ValueError("font collections are not supported; upload one TTF/OTF face at a time")
        raise ValueError("file is not a supported TTF or OTF font")
    count = _u16(content, 4)
    if count < 1 or count > 256 or 12 + count * 16 > len(content):
        raise ValueError("font table directory is invalid")
    tables: dict[str, bytes] = {}
    for index in range(count):
        record = 12 + index * 16
        try:
            tag = content[record:record + 4].decode("ascii")
        except UnicodeDecodeError as exc:
            raise ValueError("font contains an invalid table tag") from exc
        offset = _u32(content, record + 8)
        length = _u32(content, record + 12)
        if offset + length > len(content):
            raise ValueError(f"font table {tag!r} is truncated")
        tables[tag] = content[offset:offset + length]
    if "name" not in tables or "head" not in tables:
        raise ValueError("font must contain name and head tables")
    return tables


def _decode_name(platform: int, raw: bytes) -> str:
    try:
        value = raw.decode("utf-16-be" if platform in {0, 3} else "mac_roman")
    except (UnicodeDecodeError, LookupError):
        return ""
    return re.sub(r"[\x00-\x1f\x7f]+", " ", value).strip()


def _name_values(table: bytes) -> dict[int, str]:
    if len(table) < 6:
        raise ValueError("font name table is truncated")
    count = _u16(table, 2)
    string_offset = _u16(table, 4)
    if 6 + count * 12 > len(table) or string_offset > len(table):
        raise ValueError("font name table is invalid")
    candidates: dict[int, list[tuple[int, str]]] = {}
    for index in range(count):
        record = 6 + index * 12
        platform = _u16(table, record)
        language = _u16(table, record + 4)
        name_id = _u16(table, record + 6)
        length = _u16(table, record + 8)
        offset = string_offset + _u16(table, record + 10)
        if offset + length > len(table):
            continue
        value = _decode_name(platform, table[offset:offset + length])
        if not value:
            continue
        priority = (
            0 if platform == 3 and language in {0x0409, 0x0412} else
            1 if platform == 0 else
            2 if platform == 3 else
            3
        )
        candidates.setdefault(name_id, []).append((priority, value))
    return {name_id: sorted(values, key=lambda item: item[0])[0][1] for name_id, values in candidates.items()}


def inspect_font(content: bytes) -> InspectedFont:
    tables = _font_tables(content)
    names = _name_values(tables["name"])
    family = names.get(16) or names.get(1) or ""
    subfamily = names.get(17) or names.get(2) or "Regular"
    postscript = names.get(6) or re.sub(r"[^A-Za-z0-9-]+", "-", f"{family}-{subfamily}").strip("-")
    if not family or not postscript:
        raise ValueError("font family and PostScript names could not be read")

    head = tables["head"]
    units_per_em = _u16(head, 18) if len(head) >= 20 else 0
    if not 16 <= units_per_em <= 16384:
        raise ValueError("font units-per-em is invalid")
    hhea = tables.get("hhea", b"")
    os2 = tables.get("OS/2", b"")
    ascent = _i16(hhea, 4) if len(hhea) >= 10 else None
    descent = _i16(hhea, 6) if len(hhea) >= 10 else None
    line_gap = _i16(hhea, 8) if len(hhea) >= 10 else None
    weight = _u16(os2, 4) if len(os2) >= 6 else 400
    weight = min(1000, max(1, weight))
    lower_subfamily = subfamily.lower()
    style = "italic" if "italic" in lower_subfamily or "oblique" in lower_subfamily else "normal"
    typo_ascent = _i16(os2, 68) if len(os2) >= 74 else None
    typo_descent = _i16(os2, 70) if len(os2) >= 74 else None
    typo_line_gap = _i16(os2, 72) if len(os2) >= 74 else None
    x_height = _i16(os2, 86) if len(os2) >= 90 else None
    cap_height = _i16(os2, 88) if len(os2) >= 90 else None
    return InspectedFont(
        family_name=family[:160],
        subfamily_name=subfamily[:96],
        postscript_name=postscript[:160],
        weight=weight,
        style=style,
        metrics={
            "units_per_em": units_per_em,
            "ascent": ascent,
            "descent": descent,
            "line_gap": line_gap,
            "typo_ascent": typo_ascent,
            "typo_descent": typo_descent,
            "typo_line_gap": typo_line_gap,
            "x_height": x_height,
            "cap_height": cap_height,
        },
    )


def font_css_family(font_id: str) -> str:
    return f"ff-font-{re.sub(r'[^a-zA-Z0-9-]', '-', font_id)}"


def font_response(font: FontRecord, artifact: ArtifactRecord) -> dict[str, Any]:
    storage = artifact.metadata_json.get("storage") or {}
    return {
        "id": font.id,
        "artifact_id": font.artifact_id,
        "profile_version": font.profile_version,
        "supersedes_id": font.supersedes_id,
        "created_at": font.created_at,
        "updated_at": font.updated_at,
        "display_name": font.display_name,
        "family_name": font.family_name,
        "subfamily_name": font.subfamily_name,
        "postscript_name": font.postscript_name,
        "weight": font.weight,
        "style": font.style,
        "size_adjust": font.size_adjust,
        "baseline_shift": font.baseline_shift,
        "lifecycle": font.lifecycle,
        "license_name": font.license_name,
        "metrics": font.metrics_json,
        "sha256": artifact.sha256,
        "content_type": str(storage.get("content_type") or "application/octet-stream"),
        "size_bytes": int(storage.get("size_bytes") or 0),
        "css_family": font_css_family(font.id),
        "url": artifact_content_url(artifact.id),
    }


def list_fonts(db: Session, *, include_retired: bool = False) -> list[dict[str, Any]]:
    statement = select(FontRecord, ArtifactRecord).join(ArtifactRecord, ArtifactRecord.id == FontRecord.artifact_id)
    if not include_retired:
        statement = statement.where(FontRecord.lifecycle == "ACTIVE")
    rows = db.execute(statement.order_by(FontRecord.display_name, FontRecord.weight, FontRecord.created_at)).all()
    return [font_response(font, artifact) for font, artifact in rows]


def register_font(
    db: Session,
    *,
    content: bytes,
    filename: str,
    content_type: str,
    display_name: str | None,
    license_name: str,
    created_by: str,
) -> tuple[dict[str, Any], bool]:
    inspected = inspect_font(content)
    digest = hashlib.sha256(content).hexdigest()
    existing = db.execute(
        select(FontRecord, ArtifactRecord)
        .join(ArtifactRecord, ArtifactRecord.id == FontRecord.artifact_id)
        .where(ArtifactRecord.sha256 == digest, FontRecord.lifecycle == "ACTIVE")
        .order_by(FontRecord.profile_version.desc())
    ).first()
    if existing:
        return font_response(existing[0], existing[1]), False
    artifact = create_artifact(
        db,
        "Font",
        schema_id="font.face.v1",
        content=content,
        content_type=FONT_MIME_TYPES.get(content_type, content_type),
        filename=filename,
        metadata={
            "source": "font_registry",
            "filename": filename,
            "immutable": True,
            "font_family": inspected.family_name,
            "font_subfamily": inspected.subfamily_name,
            "postscript_name": inspected.postscript_name,
        },
    )
    font = FontRecord(
        id=new_id("font"),
        artifact_id=artifact.id,
        profile_version=1,
        supersedes_id=None,
        display_name=(display_name or f"{inspected.family_name} {inspected.subfamily_name}").strip()[:160],
        family_name=inspected.family_name,
        subfamily_name=inspected.subfamily_name,
        postscript_name=inspected.postscript_name,
        weight=inspected.weight,
        style=inspected.style,
        size_adjust=1.0,
        baseline_shift=0.0,
        lifecycle="ACTIVE",
        license_name=(license_name.strip() or "User provided")[:160],
        metrics_json=inspected.metrics,
    )
    db.add(font)
    db.flush()
    audit(db, "font.registered", font.id, {
        "artifact_id": artifact.id,
        "sha256": digest,
        "family_name": inspected.family_name,
        "created_by": created_by,
    })
    return font_response(font, artifact), True


def update_font_profile(
    db: Session,
    font: FontRecord,
    *,
    display_name: str | None = None,
    size_adjust: float | None = None,
    baseline_shift: float | None = None,
    lifecycle: str | None = None,
    license_name: str | None = None,
) -> dict[str, Any]:
    if display_name is not None:
        if not display_name.strip():
            raise ValueError("font display name cannot be empty")
    next_display_name = display_name.strip()[:160] if display_name is not None else font.display_name
    next_size_adjust = font.size_adjust
    if size_adjust is not None:
        if not 0.5 <= size_adjust <= 2:
            raise ValueError("font size adjustment must be between 0.5 and 2")
        next_size_adjust = round(size_adjust, 4)
    next_baseline_shift = font.baseline_shift
    if baseline_shift is not None:
        if not -0.5 <= baseline_shift <= 0.5:
            raise ValueError("font baseline shift must be between -0.5 and 0.5")
        next_baseline_shift = round(baseline_shift, 4)
    next_license_name = (license_name.strip() or "User provided")[:160] if license_name is not None else font.license_name
    artifact = db.get(ArtifactRecord, font.artifact_id)
    if not artifact:
        raise ValueError("font file artifact is missing")
    profile_changed = next_size_adjust != font.size_adjust or next_baseline_shift != font.baseline_shift
    if profile_changed:
        if db.scalar(select(FontRecord).where(FontRecord.supersedes_id == font.id)):
            raise ValueError("font profile was already superseded; refresh before editing it again")
        successor_lifecycle = lifecycle or font.lifecycle
        font.lifecycle = "RETIRED"
        font.updated_at = utc_now()
        successor = FontRecord(
            id=new_id("font"),
            artifact_id=font.artifact_id,
            profile_version=font.profile_version + 1,
            supersedes_id=font.id,
            display_name=next_display_name,
            family_name=font.family_name,
            subfamily_name=font.subfamily_name,
            postscript_name=font.postscript_name,
            weight=font.weight,
            style=font.style,
            size_adjust=next_size_adjust,
            baseline_shift=next_baseline_shift,
            lifecycle=successor_lifecycle,
            license_name=next_license_name,
            metrics_json=dict(font.metrics_json or {}),
        )
        db.add(successor)
        db.flush()
        audit(db, "font.profile_version_created", successor.id, {
            "supersedes_id": font.id,
            "profile_version": successor.profile_version,
            "size_adjust": successor.size_adjust,
            "baseline_shift": successor.baseline_shift,
        })
        return font_response(successor, artifact)
    if lifecycle is not None:
        if lifecycle not in {"ACTIVE", "RETIRED"}:
            raise ValueError("font lifecycle must be ACTIVE or RETIRED")
        if lifecycle == "ACTIVE" and db.scalar(select(FontRecord).where(FontRecord.supersedes_id == font.id)):
            raise ValueError("a superseded font profile cannot be restored")
        font.lifecycle = lifecycle
    font.display_name = next_display_name
    font.license_name = next_license_name
    font.updated_at = utc_now()
    audit(db, "font.profile_updated", font.id, {"lifecycle": font.lifecycle})
    return font_response(font, artifact)


def font_snapshots(db: Session, font_ids: set[str]) -> list[dict[str, Any]]:
    if not font_ids:
        return []
    rows = db.execute(
        select(FontRecord, ArtifactRecord)
        .join(ArtifactRecord, ArtifactRecord.id == FontRecord.artifact_id)
        .where(FontRecord.id.in_(font_ids))
    ).all()
    by_id = {font.id: (font, artifact) for font, artifact in rows}
    missing = sorted(font_ids - set(by_id))
    if missing:
        raise ValueError(f"caption document references missing fonts: {', '.join(missing)}")
    return [
        {
            "font_id": font.id,
            "artifact_id": artifact.id,
            "css_family": font_css_family(font.id),
            "family_name": font.family_name,
            "subfamily_name": font.subfamily_name,
            "postscript_name": font.postscript_name,
            "weight": font.weight,
            "style": font.style,
            "size_adjust": font.size_adjust,
            "baseline_shift": font.baseline_shift,
            "sha256": artifact.sha256,
        }
        for font, artifact in sorted(by_id.values(), key=lambda value: value[0].id)
    ]
