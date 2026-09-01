#!/usr/bin/env python3
"""Validate and expose the repository's time-bounded security exceptions."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any


REQUIRED_FIELDS = {"ecosystem", "advisory_id", "package", "reason", "owner", "expires"}


def load_exceptions(path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {path}: {exc}") from exc

    if payload.get("schema_version") != 1 or not isinstance(payload.get("exceptions"), list):
        raise ValueError(f"{path} must use schema_version 1 and contain an exceptions list")

    today = date.today()
    validated: list[dict[str, Any]] = []
    for index, item in enumerate(payload["exceptions"]):
        if not isinstance(item, dict):
            raise ValueError(f"exception #{index + 1} must be an object")
        missing = sorted(REQUIRED_FIELDS - item.keys())
        if missing:
            raise ValueError(f"exception #{index + 1} is missing: {', '.join(missing)}")
        if not all(isinstance(item[field], str) and item[field].strip() for field in REQUIRED_FIELDS):
            raise ValueError(f"exception #{index + 1} fields must be non-empty strings")
        try:
            expiry = date.fromisoformat(item["expires"])
        except ValueError as exc:
            raise ValueError(f"exception #{index + 1} has an invalid expires date") from exc
        if expiry < today:
            raise ValueError(
                f"exception #{index + 1} for {item['advisory_id']} expired on {expiry.isoformat()}"
            )
        validated.append(item)
    return validated


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--file",
        type=Path,
        default=Path("security/dependency-exceptions.json"),
    )
    parser.add_argument("--ecosystem")
    parser.add_argument("--print-advisory-ids", action="store_true")
    args = parser.parse_args()

    try:
        exceptions = load_exceptions(args.file)
    except ValueError as exc:
        print(f"security exception validation failed: {exc}")
        return 1

    if args.ecosystem:
        exceptions = [item for item in exceptions if item["ecosystem"] == args.ecosystem]
    if args.print_advisory_ids:
        for item in exceptions:
            print(item["advisory_id"])
    else:
        print(f"validated {len(exceptions)} active security exception(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
