from __future__ import annotations

from pathlib import Path

from sqlalchemy import func, select
import pytest

from app.database import ArtifactRecord, SessionLocal, SkillVersionRecord
from app.seed import seed_assets, seed_skills


def _write_skill(root: Path, skill_id: str, body: str) -> Path:
    directory = root / skill_id
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "SKILL.md"
    path.write_text(f"""---
name: {skill_id}
description: Seeded test skill
---

{body}
""")
    return path


def test_skill_seed_supports_dry_run_idempotency_and_new_versions(client, tmp_path):
    del client
    root = tmp_path / "skill-imports"
    root.mkdir()
    _write_skill(root, "seeded-skill", "Return the seeded result.")
    (root / ".hidden").mkdir()
    _write_skill(root / ".hidden", "ignored-skill", "Ignore this.")
    (root / "README.txt").write_text("ignored")

    with SessionLocal() as db:
        before = int(db.scalar(select(func.count()).select_from(SkillVersionRecord)) or 0)
        dry_run = seed_skills(db, root, dry_run=True)
        assert [item["skill_id"] for item in dry_run["registered"]] == ["seeded-skill"]
        assert dry_run["errors"] == []
        assert int(db.scalar(select(func.count()).select_from(SkillVersionRecord)) or 0) == before

        seeded = seed_skills(db, root)
        assert [item["skill_id"] for item in seeded["registered"]] == ["seeded-skill"]
        assert seed_skills(db, root)["unchanged"][0]["version_number"] == 1

        _write_skill(root, "seeded-skill", "Return the revised seeded result.")
        revised = seed_skills(db, root)
        assert revised["registered"][0]["version_number"] == 2


def test_asset_seed_validates_mime_deduplicates_and_records_relative_paths(client, tmp_path):
    del client
    root = tmp_path / "asset-imports"
    root.mkdir()
    (root / "images").mkdir()
    (root / "images" / "sample.png").write_bytes(b"\x89PNG\r\n\x1a\n-seeded-image")
    (root / "notes.txt").write_text("seeded notes")
    (root / "fake.jpg").write_text("not a jpeg")

    with SessionLocal() as db:
        dry_run = seed_assets(db, root, dry_run=True)
        assert {item["path"] for item in dry_run["registered"]} == {"images/sample.png", "notes.txt"}
        assert dry_run["errors"] == [{"path": "fake.jpg", "error": "file content does not match image/jpeg"}]
        assert db.scalar(select(func.count()).select_from(ArtifactRecord)) == 0

        seeded = seed_assets(db, root)
        assert {item["type"] for item in seeded["registered"]} == {"Image", "Text"}
        records = db.scalars(select(ArtifactRecord).order_by(ArtifactRecord.type)).all()
        assert {record.metadata_json["relative_path"] for record in records} == {"images/sample.png", "notes.txt"}

        repeated = seed_assets(db, root)
        assert len(repeated["duplicates"]) == 2
        assert repeated["errors"] == [{"path": "fake.jpg", "error": "file content does not match image/jpeg"}]


def test_seed_rejects_symlinks_and_broad_roots(client, tmp_path):
    del client
    root = tmp_path / "safe-imports"
    root.mkdir()
    source = tmp_path / "outside.txt"
    source.write_text("outside")
    (root / "link.txt").symlink_to(source)
    with SessionLocal() as db, pytest.raises(ValueError, match="cannot be symlinks"):
        seed_assets(db, root, dry_run=True)
    with SessionLocal() as db, pytest.raises(ValueError, match="dedicated import directory"):
        seed_assets(db, Path.home(), dry_run=True)
