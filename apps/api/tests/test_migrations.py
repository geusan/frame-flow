from __future__ import annotations

import os
from pathlib import Path
import sqlite3
import subprocess
import sys


def test_alembic_upgrade_head_supports_the_default_sqlite_installation(tmp_path):
    database_path = tmp_path / "migration.db"
    environment = os.environ.copy()
    environment["DATABASE_URL"] = f"sqlite:///{database_path}"
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=Path(__file__).parents[1],
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    with sqlite3.connect(database_path) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        version = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    assert {"skill_definitions", "skill_versions", "skill_installations", "workflow_versions"} <= tables
    assert version == "0009"

