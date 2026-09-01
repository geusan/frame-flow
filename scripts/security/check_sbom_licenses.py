#!/usr/bin/env python3
"""Compare SPDX package licenses with Frameflow's review policy."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


SPDX_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9.+-]*")
OPERATORS = {"AND", "OR", "WITH"}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def license_ids(package: dict[str, Any]) -> set[str]:
    concluded = str(package.get("licenseConcluded", "NOASSERTION"))
    declared = str(package.get("licenseDeclared", "NOASSERTION"))
    expressions = {declared if concluded in {"", "NOASSERTION"} else concluded}
    identifiers = {
        token
        for expression in expressions
        for token in SPDX_TOKEN.findall(expression)
        if token not in OPERATORS
    }
    return identifiers or {"NOASSERTION"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("sbom", type=Path)
    parser.add_argument(
        "--policy",
        type=Path,
        default=Path("security/license-policy.json"),
    )
    parser.add_argument("--max-findings", type=int, default=50)
    args = parser.parse_args()

    try:
        policy = load_json(args.policy)
        sbom = load_json(args.sbom)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"license policy check failed: {exc}")
        return 1

    if policy.get("schema_version") != 1 or policy.get("enforcement") not in {"report", "block"}:
        print("license policy check failed: unsupported policy schema or enforcement mode")
        return 1

    allowed = set(policy.get("allowed", []))
    review_required = set(policy.get("review_required", []))
    blocked = set(policy.get("blocked", []))
    review: list[str] = []
    denied: list[str] = []

    for package in sbom.get("packages", []):
        name = package.get("name", "<unknown>")
        version = package.get("versionInfo", "<unknown>")
        identifiers = license_ids(package)
        if identifiers & blocked:
            denied.append(f"{name}@{version}: {', '.join(sorted(identifiers))}")
        elif identifiers - allowed or identifiers & review_required:
            review.append(f"{name}@{version}: {', '.join(sorted(identifiers))}")

    print(f"license inventory: {len(review)} review-required, {len(denied)} blocked")
    findings = [*(f"BLOCKED {item}" for item in denied), *(f"REVIEW {item}" for item in review)]
    for finding in findings[: args.max_findings]:
        print(finding)
    if len(findings) > args.max_findings:
        print(f"... {len(findings) - args.max_findings} additional finding(s) omitted")

    if denied or (review and policy["enforcement"] == "block"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
