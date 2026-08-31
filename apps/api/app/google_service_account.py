from __future__ import annotations

import json
import os
from typing import Any


GOOGLE_SERVICE_ACCOUNT_ENV = "GOOGLE_SERVICE_ACCOUNT_JSON"
GOOGLE_CLOUD_PLATFORM_SCOPE = "https://www.googleapis.com/auth/cloud-platform"
REQUIRED_SERVICE_ACCOUNT_FIELDS = (
    "type",
    "project_id",
    "private_key_id",
    "private_key",
    "client_email",
    "client_id",
    "token_uri",
)


def parse_service_account_json(raw: str) -> dict[str, Any]:
    value = raw.strip()
    if not value:
        raise ValueError("Google Service Account JSON is empty")
    if len(value) > 100_000:
        raise ValueError("Google Service Account JSON is unexpectedly large")
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError("Google Service Account JSON is invalid") from exc
    if not isinstance(payload, dict):
        raise ValueError("Google Service Account JSON must contain an object")
    if payload.get("type") != "service_account":
        raise ValueError("Google credential type must be service_account")
    missing = [key for key in REQUIRED_SERVICE_ACCOUNT_FIELDS if not str(payload.get(key) or "").strip()]
    if missing:
        raise ValueError(f"Google Service Account JSON is missing: {', '.join(missing)}")
    if not str(payload["private_key"]).startswith("-----BEGIN PRIVATE KEY-----"):
        raise ValueError("Google Service Account private_key is not a PEM private key")
    return payload


def validate_service_account_json(raw: str) -> dict[str, Any]:
    payload = parse_service_account_json(raw)
    try:
        from google.oauth2 import service_account

        service_account.Credentials.from_service_account_info(
            payload,
            scopes=[GOOGLE_CLOUD_PLATFORM_SCOPE],
        )
    except Exception as exc:
        raise ValueError("Google Service Account private key could not be loaded") from exc
    return payload


def service_account_info_from_env() -> dict[str, Any] | None:
    raw = os.getenv(GOOGLE_SERVICE_ACCOUNT_ENV, "").strip()
    return parse_service_account_json(raw) if raw else None


def google_credentials_from_env(*, scopes: list[str] | None = None) -> Any | None:
    payload = service_account_info_from_env()
    if not payload:
        return None
    from google.oauth2 import service_account

    return service_account.Credentials.from_service_account_info(
        payload,
        scopes=scopes or [GOOGLE_CLOUD_PLATFORM_SCOPE],
    )


def google_project_from_env() -> str:
    configured = os.getenv("GOOGLE_CLOUD_PROJECT", "").strip()
    if configured:
        return configured
    payload = service_account_info_from_env()
    return str((payload or {}).get("project_id") or "").strip()
