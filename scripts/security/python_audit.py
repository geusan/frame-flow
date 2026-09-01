#!/usr/bin/env python3
"""Run pip-audit with validated, expiring repository exceptions."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from dependency_exceptions import load_exceptions


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--requirements",
        type=Path,
        default=Path("apps/api/requirements.lock.txt"),
    )
    parser.add_argument(
        "--exceptions",
        type=Path,
        default=Path("security/dependency-exceptions.json"),
    )
    args = parser.parse_args()

    try:
        exceptions = load_exceptions(args.exceptions)
    except ValueError as exc:
        print(f"security exception validation failed: {exc}", file=sys.stderr)
        return 1

    command = [
        sys.executable,
        "-m",
        "pip_audit",
        "--requirement",
        str(args.requirements),
        "--disable-pip",
        "--progress-spinner",
        "off",
        "--strict",
    ]
    for item in exceptions:
        if item["ecosystem"] == "python":
            command.extend(("--ignore-vuln", item["advisory_id"]))

    return subprocess.run(command, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
