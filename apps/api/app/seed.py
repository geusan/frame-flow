from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import ArtifactRecord, SessionLocal, create_all
from .project_skills import parse_project_skill_file, register_project_skill
from .service import audit, create_artifact
from .storage import get_storage


MAX_SEED_FILES = 10_000
MAX_SEED_TOTAL_BYTES = 5 * 1024 * 1024 * 1024
MAX_ASSET_BYTES = 250 * 1024 * 1024
ALLOWED_ASSET_TYPES = frozenset({"Image", "Video", "Audio", "Text"})


def _safe_root(value: str | Path) -> Path:
    root = Path(value).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"Seed root is not a directory: {root}")
    if root in {Path("/"), Path.home().resolve()}:
        raise ValueError("Seed root must be a dedicated import directory, not / or the user home")
    return root


def _visible_files(root: Path) -> list[Path]:
    files: list[Path] = []
    total_bytes = 0
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if any(part.startswith(".") for part in relative.parts):
            continue
        if path.is_symlink():
            raise ValueError(f"Seed paths cannot be symlinks: {relative}")
        if not path.is_file():
            continue
        resolved = path.resolve()
        if root not in resolved.parents:
            raise ValueError(f"Seed path escapes the import root: {relative}")
        files.append(path)
        total_bytes += path.stat().st_size
        if len(files) > MAX_SEED_FILES:
            raise ValueError(f"Seed root contains more than {MAX_SEED_FILES} files")
        if total_bytes > MAX_SEED_TOTAL_BYTES:
            raise ValueError("Seed root exceeds the 5 GB scan limit")
    return files


def _artifact_type(content_type: str) -> str | None:
    if content_type.startswith("image/"):
        return "Image"
    if content_type.startswith("video/"):
        return "Video"
    if content_type.startswith("audio/"):
        return "Audio"
    if content_type.startswith("text/") or content_type in {"application/json", "application/x-subrip"}:
        return "Text"
    return None


def _magic_matches(content_type: str, sample: bytes) -> bool:
    if content_type == "image/png":
        return sample.startswith(b"\x89PNG\r\n\x1a\n")
    if content_type in {"image/jpeg", "image/jpg"}:
        return sample.startswith(b"\xff\xd8\xff")
    if content_type == "image/gif":
        return sample.startswith((b"GIF87a", b"GIF89a"))
    if content_type == "image/webp":
        return sample.startswith(b"RIFF") and sample[8:12] == b"WEBP"
    if content_type in {"video/mp4", "video/quicktime"}:
        return len(sample) >= 12 and sample[4:8] == b"ftyp"
    if content_type in {"video/webm", "video/x-matroska"}:
        return sample.startswith(b"\x1a\x45\xdf\xa3")
    if content_type in {"audio/wav", "audio/x-wav"}:
        return sample.startswith(b"RIFF") and sample[8:12] == b"WAVE"
    if content_type in {"audio/mpeg", "audio/mp3"}:
        return sample.startswith(b"ID3") or sample.startswith((b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"))
    if content_type.startswith("text/") or content_type in {"application/json", "application/x-subrip"}:
        try:
            sample.decode("utf-8")
            return True
        except UnicodeDecodeError:
            return False
    return False


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def seed_skills(
    db: Session,
    root_value: str | Path,
    *,
    dry_run: bool = False,
    created_by: str = "seed-cli",
) -> dict[str, Any]:
    root = _safe_root(root_value)
    files = _visible_files(root)
    skill_files = [path for path in files if path.name == "SKILL.md" and path.parent.parent == root]
    report: dict[str, Any] = {"kind": "skills", "root": str(root), "dry_run": dry_run, "registered": [], "unchanged": [], "errors": []}
    for path in skill_files:
        relative = str(path.relative_to(root))
        try:
            parsed = parse_project_skill_file(path, source="seed")
            if dry_run:
                report["registered"].append({"path": relative, "skill_id": parsed.id, "version": parsed.version})
                continue
            stored, created = register_project_skill(db, parsed, created_by=created_by)
            target = "registered" if created else "unchanged"
            report[target].append({
                "path": relative,
                "skill_id": stored.id,
                "version": stored.version,
                "version_number": stored.version_number,
            })
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            report["errors"].append({"path": relative, "error": str(exc)})
    ignored = [str(path.relative_to(root)) for path in files if path not in skill_files]
    report["ignored"] = ignored
    if not dry_run:
        audit(db, "skills.seeded", "skill-registry", {
            "root": str(root),
            "registered": len(report["registered"]),
            "unchanged": len(report["unchanged"]),
            "errors": len(report["errors"]),
        })
        db.commit()
    return report


def seed_assets(
    db: Session,
    root_value: str | Path,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    root = _safe_root(root_value)
    files = _visible_files(root)
    report: dict[str, Any] = {"kind": "assets", "root": str(root), "dry_run": dry_run, "registered": [], "duplicates": [], "errors": []}
    for path in files:
        relative = str(path.relative_to(root))
        size_bytes = path.stat().st_size
        try:
            if not size_bytes:
                raise ValueError("file is empty")
            if size_bytes > MAX_ASSET_BYTES:
                raise ValueError("file exceeds the 250 MB Asset limit")
            content_type = (mimetypes.guess_type(path.name)[0] or "").lower()
            artifact_type = _artifact_type(content_type)
            if artifact_type not in ALLOWED_ASSET_TYPES:
                raise ValueError("unsupported Asset MIME type")
            with path.open("rb") as source:
                sample = source.read(4096)
            if not _magic_matches(content_type, sample):
                raise ValueError(f"file content does not match {content_type}")
            digest = _file_sha256(path)
            existing = db.scalar(select(ArtifactRecord).where(ArtifactRecord.sha256 == digest))
            if existing:
                report["duplicates"].append({"path": relative, "artifact_id": existing.id, "sha256": digest})
                continue
            if dry_run:
                report["registered"].append({
                    "path": relative,
                    "type": artifact_type,
                    "content_type": content_type,
                    "size_bytes": size_bytes,
                    "sha256": digest,
                })
                continue
            content = path.read_bytes()
            artifact = create_artifact(
                db,
                artifact_type,
                schema_id=f"{artifact_type.lower()}.asset.v1",
                content=content,
                content_type=content_type,
                filename=path.name,
                metadata={
                    "source": "local_seed",
                    "relative_path": relative,
                    "filename": path.name,
                    "immutable": True,
                },
            )
            db.flush()
            report["registered"].append({
                "path": relative,
                "artifact_id": artifact.id,
                "type": artifact.type,
                "content_type": content_type,
                "size_bytes": size_bytes,
                "sha256": artifact.sha256,
            })
        except (OSError, ValueError) as exc:
            report["errors"].append({"path": relative, "error": str(exc)})
    if not dry_run:
        audit(db, "assets.seeded", "artifact-library", {
            "root": str(root),
            "registered": len(report["registered"]),
            "duplicates": len(report["duplicates"]),
            "errors": len(report["errors"]),
        })
        db.commit()
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Seed trusted local data into Frameflow")
    subparsers = parser.add_subparsers(dest="kind", required=True)
    for kind in ("skills", "assets"):
        command = subparsers.add_parser(kind)
        command.add_argument("--root", required=True, help="Dedicated read-only import directory")
        command.add_argument("--dry-run", action="store_true")
    subparsers.choices["skills"].add_argument("--created-by", default="seed-cli")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    create_all()
    if args.kind == "assets" and not args.dry_run:
        get_storage().initialize()
    with SessionLocal() as db:
        report = (
            seed_skills(db, args.root, dry_run=args.dry_run, created_by=args.created_by)
            if args.kind == "skills"
            else seed_assets(db, args.root, dry_run=args.dry_run)
        )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

