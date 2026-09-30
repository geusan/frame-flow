"""YouTube-only Netscape sessions; cookie contents must never enter artifacts or logs."""
from __future__ import annotations

import time
from urllib.parse import urlparse

MAX_COOKIE_BYTES = 256 * 1024
AUTH_COOKIES = {"SID", "HSID", "SSID", "APISID", "SAPISID", "LOGIN_INFO", "__Secure-1PSID", "__Secure-3PSID"}


def is_youtube_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower().rstrip(".")
    return host == "youtu.be" or host == "youtube.com" or host.endswith(".youtube.com")


def normalize_youtube_cookies(value: str) -> str:
    if len(value.encode("utf-8")) > MAX_COOKIE_BYTES:
        raise ValueError("cookies.txt must be at most 256 KB")
    lines = value.lstrip("\ufeff").splitlines()
    if not lines or lines[0].strip() not in {"# Netscape HTTP Cookie File", "# HTTP Cookie File"}:
        raise ValueError("Upload a Netscape cookies.txt export from YouTube")
    selected = []
    authenticated = False
    for line in lines[1:]:
        if not line.strip() or (line.startswith("#") and not line.startswith("#HttpOnly_")):
            continue
        fields = line.removeprefix("#HttpOnly_").split("\t")
        if len(fields) != 7:
            raise ValueError("Invalid Netscape cookie row; export cookies.txt again")
        domain, include_subdomains, path, secure, expiry, name, content = fields
        if domain.lstrip(".").lower() != "youtube.com" and not domain.lstrip(".").lower().endswith(".youtube.com"):
            continue  # Never store unrelated accounts from a browser-wide export.
        if (include_subdomains not in {"TRUE", "FALSE"} or secure not in {"TRUE", "FALSE"}
                or not path.startswith("/") or not expiry.isdigit() or not name or not content
                or any(ord(c) < 32 or ord(c) == 127 for c in "".join(fields))):
            raise ValueError("Invalid YouTube cookie row; export cookies.txt again")
        authenticated |= name in AUTH_COOKIES
        selected.append(line)
    if not authenticated:
        raise ValueError("No YouTube login cookies found; export cookies.txt after signing in")
    return "# Netscape HTTP Cookie File\n" + "\n".join(selected) + "\n"


def session_expired(value: str) -> bool:
    expiries = [int(row.removeprefix("#HttpOnly_").split("\t")[4])
                for row in value.splitlines() if "\t" in row
                and row.removeprefix("#HttpOnly_").split("\t")[5] in AUTH_COOKIES]
    return bool(expiries) and all(expiry != 0 and expiry <= time.time() for expiry in expiries)


def load_youtube_cookies() -> str:
    # Read each operation: replacements/disconnects also reach long-running workers.
    from .database import SessionLocal
    from .provider_settings import get_provider_record

    with SessionLocal() as db:
        record = get_provider_record(db, "youtube")
        if record is None or not record.enabled:
            return ""
        value = (record.secrets or {}).get("cookies_txt", "")
    if not value:
        return ""
    normalized = normalize_youtube_cookies(value)
    if session_expired(normalized):
        raise ValueError("YouTube session expired. Replace cookies.txt in Settings → YouTube.")
    return normalized


def sanitize_download_metadata(value):
    if isinstance(value, dict):
        return {key: sanitize_download_metadata(item) for key, item in value.items()
                if key.lower() not in {"cookie", "cookies", "authorization", "set-cookie"}}
    if isinstance(value, list):
        return [sanitize_download_metadata(item) for item in value]
    return value
