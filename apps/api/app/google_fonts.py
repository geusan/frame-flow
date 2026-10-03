"""Google Fonts catalog and complete, static font downloads (no API key).

The public fonts.google.com catalog is isolated here because its metadata endpoint
is not the versioned Developer API. Never accept a download URL from the caller.
"""
from __future__ import annotations

import json
import re
import threading
import time
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx

from .contexts.administration.domain import (
    AdministrationNotFoundError,
    AdministrationPayloadTooLargeError,
    AdministrationUpstreamError,
    AdministrationValidationError,
)
from .font_registry import FONT_MAX_BYTES, inspect_font, inspect_font_license


CATALOG_URL = "https://fonts.google.com/metadata/fonts"
CATALOG_TTL_SECONDS = 6 * 60 * 60
_catalog: tuple[float, list[dict[str, Any]]] | None = None
_catalog_lock = threading.Lock()
_VARIANT = re.compile(r"([1-9][0-9]{0,2}|1000)(i?)")


def _download(url: str, *, max_bytes: int) -> bytes:
    try:
        # A non-browser UA requests a complete static TTF instead of browser-
        # specific WOFF2/unicode subsets, which cannot be used by the renderer.
        with httpx.Client(timeout=httpx.Timeout(45, connect=10), follow_redirects=False,
                          headers={"User-Agent": "Frameflow-Fonts/1.0"}) as client:
            with client.stream("GET", url) as response:
                response.raise_for_status()
                content = bytearray()
                for chunk in response.iter_bytes():
                    content.extend(chunk)
                    if len(content) > max_bytes:
                        raise AdministrationPayloadTooLargeError("Google Fonts 응답이 허용 크기를 초과했습니다.")
                return bytes(content)
    except httpx.HTTPError as exc:
        raise AdministrationUpstreamError("Google Fonts에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.") from exc


def _get_catalog() -> list[dict[str, Any]]:
    global _catalog
    with _catalog_lock:
        if _catalog is not None and time.monotonic() - _catalog[0] < CATALOG_TTL_SECONDS:
            return _catalog[1]
        try:
            text = _download(CATALOG_URL, max_bytes=8 * 1024 * 1024).decode("utf-8")
            if text.startswith(")]}'"):
                text = text.split("\n", 1)[1]
            families = json.loads(text)["familyMetadataList"]
            result = []
            for item in families:
                if not item.get("isOpenSource", True):
                    continue
                variants = sorted(
                    (key for key in item["fonts"] if _VARIANT.fullmatch(key)),
                    key=lambda key: (key.endswith("i"), int(key.rstrip("i"))),
                )
                if not variants:
                    continue
                result.append({
                    "family": item["family"],
                    "display_name": item.get("displayName") or item["family"],
                    "category": item.get("category", ""),
                    "subsets": item.get("subsets", []),
                    "variants": variants,
                    "popularity": int(item.get("popularity", 100000)),
                })
            if not result:
                raise ValueError("empty catalog")
        except (KeyError, TypeError, ValueError, AttributeError, IndexError) as exc:
            raise AdministrationUpstreamError("Google Fonts 목록을 읽을 수 없습니다. 잠시 후 다시 시도해 주세요.") from exc
        _catalog = (time.monotonic(), result)
        return result


def search_google_fonts(query: str, korean_only: bool, offset: int, limit: int) -> dict[str, Any]:
    def normalized(value: str) -> str:
        return re.sub(r"[\s_-]+", "", value.casefold())

    needle = normalized(query)
    catalog = _get_catalog()
    families = [item for item in catalog
                if (not korean_only or "korean" in item["subsets"])
                and (needle in normalized(item["family"]) or needle in normalized(item["display_name"]))]
    families.sort(key=lambda item: (normalized(item["family"]) != needle, item["popularity"], item["family"]))
    return {
        "items": families[offset:offset + limit], "total": len(families), "offset": offset, "limit": limit,
        "catalog_total": len(catalog), "korean_total": sum("korean" in item["subsets"] for item in catalog),
    }


def download_google_font(family: str, variant: str) -> dict[str, Any]:
    entry = next((item for item in _get_catalog() if item["family"] == family), None)
    if entry is None:
        raise AdministrationNotFoundError("Google Fonts에서 해당 글꼴을 찾을 수 없습니다.")
    if variant not in entry["variants"]:
        raise AdministrationValidationError("이 글꼴에서 지원하지 않는 굵기 또는 스타일입니다.")
    weight = int(variant.rstrip("i"))
    italic = variant.endswith("i")
    selection = f"{family}:ital,wght@{int(italic)},{weight}"
    css_url = "https://fonts.googleapis.com/css2?" + urlencode({"family": selection})
    try:
        css = _download(css_url, max_bytes=256 * 1024).decode("utf-8")
        urls = re.findall(r"url\(\s*['\"]?([^)'\"\s]+)['\"]?\s*\)", css)
        # Do not silently install only one script out of a subsetted font.
        if len(urls) != 1 or "unicode-range" in css.lower():
            raise ValueError("expected a complete static font")
        url = urls[0]
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or parsed.netloc != "fonts.gstatic.com"
                or not parsed.path.startswith("/s/") or not parsed.path.endswith((".ttf", ".otf"))):
            raise ValueError("unexpected font URL")
        content = _download(url, max_bytes=FONT_MAX_BYTES)
        inspected = inspect_font(content)
        if inspected.weight != weight or inspected.style != ("italic" if italic else "normal"):
            raise ValueError("downloaded face does not match the selected style")
        license_info = inspect_font_license(content)
    except (ValueError, UnicodeError) as exc:
        raise AdministrationUpstreamError("선택한 스타일의 전체 TTF/OTF 파일을 가져올 수 없습니다. 다른 스타일을 선택해 주세요.") from exc
    license_url = license_info.get("url", "")
    license_name = (
        "SIL Open Font License 1.1" if "sil.org" in license_url or "openfontlicense.org" in license_url else
        "Apache License 2.0" if "apache.org" in license_url else
        "Ubuntu Font Licence 1.0" if "ubuntu" in license_url.lower() else
        "Google Fonts (see embedded license)"
    )
    return {
        "content": content,
        "filename": re.sub(r"[^A-Za-z0-9_-]", "", family) + f"-{variant}" + parsed.path[-4:],
        "content_type": "font/otf" if parsed.path.endswith(".otf") else "font/ttf",
        "display_name": f"{family} {weight}{' Italic' if italic else ''}",
        "license_name": license_name,
        "source_metadata": {"google_fonts": {
            "family": family, "variant": variant, "url": url, "license": license_info,
        }},
    }
