from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from .canonical_motion import BONE_NAMES, REQUIRED_RETARGET_BONES


@lru_cache(maxsize=1)
def load_bone_map_profiles() -> dict[str, dict[str, str]]:
    path = Path(__file__).with_name("bone_maps.v1.json")
    payload = json.loads(path.read_text())
    if payload.get("schema_version") != "humanoid.bone_maps.v1":
        raise ValueError("unsupported humanoid bone map registry")
    profiles = payload.get("profiles")
    if not isinstance(profiles, dict):
        raise ValueError("humanoid bone map registry is missing profiles")
    return {name: validate_bone_map(mapping) for name, mapping in profiles.items()}


def validate_bone_map(mapping: Any) -> dict[str, str]:
    if not isinstance(mapping, dict):
        raise ValueError("Humanoid bone map must be an object")
    normalized = {str(key): str(value).strip() for key, value in mapping.items() if str(value).strip()}
    unknown = sorted(set(normalized) - set(BONE_NAMES))
    if unknown:
        raise ValueError(f"Humanoid bone map has unknown semantic bones: {', '.join(unknown)}")
    missing = [name for name in REQUIRED_RETARGET_BONES if name not in normalized]
    if missing:
        raise ValueError(f"Missing required bone mapping: {', '.join(missing)}")
    if len(set(normalized.values())) != len(normalized):
        raise ValueError("Humanoid bone map cannot map two semantic bones to the same target bone")
    return normalized


def resolve_bone_map(profile: str, custom_json: str = "") -> dict[str, str]:
    if profile == "custom":
        if not custom_json.strip():
            raise ValueError("Custom rig profile requires bone_map_json")
        try:
            return validate_bone_map(json.loads(custom_json))
        except json.JSONDecodeError as exc:
            raise ValueError("bone_map_json is not valid JSON") from exc
    profiles = load_bone_map_profiles()
    try:
        return dict(profiles[profile])
    except KeyError as exc:
        raise ValueError(f"Unknown humanoid rig profile: {profile}") from exc
