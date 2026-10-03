"""Adapter for Noonnu's public free-font catalog and published webfont sources.

Catalog JSON and detail HTML are website interfaces, isolated here so changes do
not affect the immutable Font Registry. Paid-market previews are never imported.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import struct
import threading
import time
from collections import OrderedDict
from html.parser import HTMLParser
from typing import Any
from urllib.parse import quote, urlencode, urljoin, urlsplit, urlunsplit

import httpx
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

from .contexts.administration.domain import (
    AdministrationNotFoundError, AdministrationPayloadTooLargeError,
    AdministrationUpstreamError, AdministrationValidationError,
)
from .font_registry import FONT_MAX_BYTES, inspect_font, inspect_font_license
from .font_source_catalog import audited_font_source, download_audited_face, source_catalog


_cache: OrderedDict[str, tuple[float, Any]] = OrderedDict()
_cache_lock = threading.Lock()
_FONT_HOSTS = {"cdn.jsdelivr.net", "fastly.jsdelivr.net", "gcore.jsdelivr.net", "cdn.noonnu.cc", "hangeul.pstatic.net", "fonts.gstatic.com", "raw.githubusercontent.com", "cdn.df.nexon.com", "spoqa.github.io", "font.elice.io"}


def _normalize_source_url(url: str) -> str:
    url = url.strip()
    if url.startswith("//"):
        url = "https:" + url
    parsed = urlsplit(url)
    if parsed.scheme == "http" and parsed.netloc in _FONT_HOSTS | {"fonts.googleapis.com"}:
        parsed = parsed._replace(scheme="https")
    return urlunsplit(parsed._replace(path=quote(parsed.path, safe="/%:@-._~!$&'()*+,;=")))


def _css_urls(value: str, base_url: str = "") -> list[str]:
    matches = re.findall(r'''url\(\s*(?:'([^']*)'|"([^"]*)"|([^)]*?))\s*\)''', value, re.I)
    return [_normalize_source_url(urljoin(base_url, next(part for part in parts if part))) for parts in matches if any(parts)]


def _safe_stylesheet_url(url: str) -> bool:
    parsed = urlsplit(url)
    if parsed.scheme != "https":
        return False
    if parsed.netloc == "fonts.googleapis.com":
        return parsed.path in {"/css", "/css2"} or re.fullmatch(r"/earlyaccess/[a-z0-9]+\.css", parsed.path) is not None
    if parsed.netloc in {"cdn.jsdelivr.net", "fastly.jsdelivr.net", "gcore.jsdelivr.net", "spoqa.github.io"}:
        return parsed.path.endswith(".css")
    return parsed.netloc == "font.elice.io" and parsed.path == "/css"


def _safe_font_url(url: str) -> bool:
    parsed = urlsplit(url)
    return (parsed.scheme == "https" and parsed.netloc in _FONT_HOSTS
            and parsed.path.lower().endswith((".ttf", ".otf", ".woff", ".woff2")))


def _page_link(url: str) -> str | None:
    parsed = urlsplit(url)
    return url if parsed.scheme in {"http", "https"} and parsed.hostname and not parsed.username else None


def _download(url: str, *, max_bytes: int = 2 * 1024 * 1024) -> bytes:
    parsed = urlsplit(url)
    if not (parsed.scheme == "https" and parsed.netloc == "noonnu.cc") and not _safe_font_url(url) and not _safe_stylesheet_url(url):
        raise AdministrationValidationError("지원하지 않는 폰트 다운로드 주소입니다. 원본 페이지를 이용해 주세요.")
    try:
        with httpx.Client(timeout=httpx.Timeout(45, connect=10), follow_redirects=False,
                          headers={"User-Agent": "Frameflow-Fonts/1.0", "Accept": "application/json" if "format=json" in parsed.query else "*/*"}) as client:
            for _ in range(5):
                with client.stream("GET", url) as response:
                    if response.is_redirect:
                        destination = _normalize_source_url(urljoin(url, response.headers.get("location", "")))
                        if not (_safe_font_url(destination) or _safe_stylesheet_url(destination)):
                            raise AdministrationUpstreamError("폰트 다운로드가 지원하지 않는 주소로 이동했습니다.")
                        url = destination
                        continue
                    if response.status_code == 404:
                        raise AdministrationNotFoundError("눈누에서 해당 글꼴을 찾을 수 없습니다.")
                    response.raise_for_status()
                    content = bytearray()
                    for chunk in response.iter_bytes():
                        content.extend(chunk)
                        if len(content) > max_bytes:
                            raise AdministrationPayloadTooLargeError("눈누 폰트 응답이 허용 크기를 초과했습니다.")
                    return bytes(content)
            raise AdministrationUpstreamError("폰트 다운로드 주소의 이동이 너무 많습니다.")
    except httpx.HTTPError as exc:
        raise AdministrationUpstreamError("눈누 폰트를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.") from exc


def _cached(key: str, fetch: Any, *, refresh: bool = False) -> Any:
    with _cache_lock:
        entry = _cache.get(key)
        if not refresh and entry and time.monotonic() - entry[0] < 600:
            _cache.move_to_end(key)
            return entry[1]
    value = fetch()
    with _cache_lock:
        _cache[key] = (time.monotonic(), value)
        _cache.move_to_end(key)
        while len(_cache) > 128:
            _cache.popitem(last=False)
    return value


def _variants(css: str, *, base_url: str = "", family_hints: list[str] | None = None) -> list[dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    duplicates: set[str] = set()
    blocks = re.findall(r"@font-face\s*\{([^}]+)\}", css, re.I)
    normalize = lambda value: re.sub(r"[\W_]+", "", value.casefold())
    available_families = [match.group(1).strip().strip("'\"") for block in blocks if (match := re.search(r"font-family\s*:\s*([^;]+)", block, re.I))]
    matching = {family for family in available_families if normalize(family) in {normalize(hint) for hint in family_hints or []}}
    for block in blocks:
        declarations = dict((name.lower(), value.strip()) for name, value in re.findall(r"([\w-]+)\s*:\s*([^;]+)", block))
        family = declarations.get("font-family", "").strip("'\"")
        if matching and family not in matching:
            continue
        if "unicode-range" in declarations:
            continue
        if declarations.get("font-stretch", "normal") not in {"normal", "100%"}:
            continue
        weight = {"normal": "400", "bold": "700"}.get(declarations.get("font-weight", "normal"), declarations.get("font-weight", "400"))
        if re.fullmatch(r"[1-9][0-9]{0,2}|1000", weight):
            weights = [int(weight)]
        elif re.fullmatch(r"[0-9]{1,4}\s+[0-9]{1,4}", weight):
            low, high = map(int, weight.split())
            if not 1 <= low <= high <= 1000:
                continue
            weights = sorted({low, high, *[value for value in range(100, 901, 100) if low <= value <= high]})
        else:
            continue
        style = declarations.get("font-style", "normal")
        if style not in {"normal", "italic"}:
            continue
        urls = [url for url in _css_urls(declarations.get("src", ""), base_url) if _safe_font_url(url)]
        urls.sort(key=lambda url: not urlsplit(url).path.lower().endswith((".ttf", ".otf")))
        url = next(iter(urls), None)
        if not url:
            continue
        for weight in weights:
            key = str(weight) + ("i" if style == "italic" else "")
            if key in result and result[key]["url"] != url:
                duplicates.add(key)
            result[key] = {"key": key, "weight": weight, "style": style, "url": url,
                           "urls": urls, "font_family": family, "label": f"{weight}{' Italic' if style == 'italic' else ''}"}
    return [value for key, value in sorted(result.items(), key=lambda pair: (pair[0].endswith("i"), int(pair[0].rstrip("i")))) if key not in duplicates]


def _resolve_variants(css: str, *, family_hints: list[str] | None = None) -> list[dict[str, Any]]:
    faces = {face["key"]: face for face in _variants(css, family_hints=family_hints)}
    for stylesheet in dict.fromkeys(_css_urls(css)):
        if not _safe_stylesheet_url(stylesheet):
            continue
        try:
            content = _cached(stylesheet, lambda: _download(stylesheet, max_bytes=1024 * 1024).decode("utf-8"))
        except (AdministrationUpstreamError, AdministrationNotFoundError):
            continue
        for face in _variants(content, base_url=stylesheet, family_hints=family_hints):
            faces.setdefault(face["key"], {**face, "source_kind": "google_fonts" if urlsplit(stylesheet).hostname == "fonts.googleapis.com" else "publisher_stylesheet", "stylesheet_url": stylesheet})
    return sorted(faces.values(), key=lambda face: (face["style"] == "italic", face["weight"]))


def search_noonnu_fonts(query: str, page: int) -> dict[str, Any]:
    path = "/search/" + quote(query, safe="") if query else "/index"
    url = "https://noonnu.cc" + path + "?" + urlencode({"format": "json", "page": page})

    def fetch() -> dict[str, Any]:
        try:
            data = json.loads(_download(url))
            items = []
            for item in data["fonts"]:
                if item.get("is_market") or not isinstance(item["id"], int):
                    continue
                preview = _variants(item.get("cdn_server_html") or "")
                audited = audited_font_source(item["id"], item["name"])
                if audited and audited.get("variants"):
                    preview = [face for face in audited["variants"] if not face.get("archive_member")]
                    preview.sort(key=lambda face: (face["weight"] != 400, face["weight"]))
                items.append({"id": item["id"], "name": item["name"], "name_en": item.get("name_en", ""),
                              "designer": item.get("creator_description", ""),
                              "variant_count": len(audited["variants"]) if audited and audited.get("variants") else item.get("font_variants_count") or 1,
                              "page_url": f"https://noonnu.cc/font_page/{item['id']}",
                              "preview": preview[0] if preview else None})
            total = int(data["total_count"])
            return {"items": items, "total": total, "page": page,
                    "has_more": not bool(data.get("is_last_page", page * 24 >= total)) and bool(data["fonts"]),
                    "source_audit": source_catalog().get("summary", {})}
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise AdministrationUpstreamError("눈누 검색 목록 형식이 변경되었습니다. 원본 사이트를 이용해 주세요.") from exc

    return _cached(url, fetch)


class _DetailParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.schema: list[str] = []
        self.webfont: list[str] = []
        self.license: list[str] = []
        self.rows: list[list[str]] = []
        self.links: list[tuple[str, str]] = []
        self._script = self._pre = self._article = False
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._anchor: tuple[str, list[str]] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "script":
            self._script = values.get("type") == "application/ld+json"
        elif tag == "pre":
            self._pre = values.get("name") == "webfontSource"
        elif tag == "article":
            self._article = True
        elif tag == "br" and self._article:
            self.license.append("\n")
        elif tag == "tr":
            self._row = []
        elif tag == "td":
            self._cell = []
        elif tag == "a":
            self._anchor = (values.get("href") or "", [])

    def handle_data(self, data: str) -> None:
        if self._script:
            self.schema.append(data)
        if self._pre:
            self.webfont.append(data)
        if self._article:
            self.license.append(data)
        if self._cell is not None:
            self._cell.append(data)
        if self._anchor is not None:
            self._anchor[1].append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self._script = False
        elif tag == "pre":
            self._pre = False
        elif tag == "article":
            self._article = False
        elif tag == "td" and self._cell is not None:
            if self._row is not None:
                self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None
        elif tag == "a" and self._anchor is not None:
            self.links.append((self._anchor[0], " ".join("".join(self._anchor[1]).split())))
            self._anchor = None


def get_noonnu_font(font_id: int, *, refresh: bool = False) -> dict[str, Any]:
    url = f"https://noonnu.cc/font_page/{font_id}"

    def fetch() -> dict[str, Any]:
        try:
            parser = _DetailParser()
            parser.feed(_download(url).decode("utf-8"))
            schema = next(json.loads(part) for part in parser.schema if '"SoftwareApplication"' in part)
            if str(schema.get("offers", {}).get("price")) != "0":
                raise AdministrationValidationError("무료 폰트만 자동으로 가져올 수 있습니다.")
            permissions = {row[0]: row[2] for row in parser.rows if len(row) == 3}
            audited = audited_font_source(font_id, schema["name"])
            hints = [schema["name"], audited.get("name_en", "")] if audited else [schema["name"]]
            variants = audited["variants"] if audited and audited.get("variants") else _resolve_variants("".join(parser.webfont), family_hints=hints)
            license_text = "".join(parser.license).strip()
            allowed = all(permissions.get(key) == "사용 가능" for key in ("영상", "웹사이트", "임베딩"))
            reason = (None if allowed else "영상·웹사이트·서버 탑재 사용 범위를 원본 페이지에서 확인해 주세요.")
            if not variants:
                reason = "자동으로 가져올 수 있는 전체 웹폰트 파일이 없습니다. 원본 TTF/OTF를 받아 등록해 주세요."
            return {"id": font_id, "name": schema["name"], "page_url": url,
                    "designer": schema.get("creator", {}).get("name", ""),
                    "download_page_url": next((_page_link(href) for href, label in parser.links if "다운로드 페이지로 이동" in label), None),
                    "variants": variants, "permissions": permissions, "license_text": license_text,
                    "source_audit": {"checked_at": audited["checked_at"], "status": audited["status"]} if audited else None,
                    "download_sources": audited.get("downloads", []) if audited else [],
                    "can_import": bool(allowed and variants and license_text),
                    "unavailable_reason": reason or (None if license_text else "원본 라이선스를 확인해 주세요.")}
        except (ValueError, KeyError, TypeError, StopIteration) as exc:
            raise AdministrationUpstreamError("눈누 글꼴 상세 정보를 읽을 수 없습니다. 원본 페이지를 이용해 주세요.") from exc

    return _cached(url, fetch, refresh=refresh)


def normalize_noonnu_font(content: bytes, *, weight: int | None = None) -> tuple[bytes, str]:
    if len(content) > FONT_MAX_BYTES:
        raise AdministrationPayloadTooLargeError("폰트 파일이 24 MB를 초과합니다.")
    signature = content[:4]
    if signature not in {b"wOFF", b"wOF2"}:
        inspected = inspect_font(content)
        if inspected.family_name == "WebSubsetFont":
            raise AdministrationValidationError("일부 글자만 포함된 웹 미리보기 파일입니다. 전체 TTF/OTF 파일을 선택해 주세요.")
        with TTFont(io.BytesIO(content), lazy=True) as font:
            if "fvar" not in font:
                return content, "none"
    elif len(content) < 20 or not 12 <= struct.unpack_from(">I", content, 16)[0] <= FONT_MAX_BYTES:
        raise AdministrationPayloadTooLargeError("압축 해제한 폰트 크기가 허용 범위를 벗어납니다.")
    try:
        with TTFont(io.BytesIO(content), recalcTimestamp=False, recalcBBoxes=False) as font:
            variable = "fvar" in font
            if "fvar" in font:
                if weight is None:
                    raise AdministrationValidationError("가변 폰트는 적용할 굵기를 선택해 주세요.")
                axes = {axis.axisTag: axis.defaultValue for axis in font["fvar"].axes}
                weight_axis = next((axis for axis in font["fvar"].axes if axis.axisTag == "wght"), None)
                if weight_axis:
                    if not weight_axis.minValue <= weight <= weight_axis.maxValue:
                        raise AdministrationValidationError("가변 폰트가 지원하지 않는 굵기입니다.")
                    axes["wght"] = weight
                # Some published STAT tables reference names absent on one
                # platform (Wanted Sans 1.0.1). Pin the outlines independently
                # and give each static weight consistent, distinct face names.
                original_ps = font["name"].getDebugName(6) or "FontInstance"
                original_style = font["name"].getDebugName(17) or font["name"].getDebugName(2) or ""
                instantiateVariableFont(font, axes, inplace=True, updateFontNames=False)
                style_name = {100: "Thin", 200: "ExtraLight", 300: "Light", 400: "Regular", 500: "Medium", 600: "SemiBold", 700: "Bold", 800: "ExtraBold", 900: "Black", 1000: "ExtraBlack"}.get(weight, f"Weight{weight}")
                if "italic" in original_style.lower() or "oblique" in original_style.lower():
                    style_name += " Italic"
                family = font["name"].getDebugName(16) or font["name"].getDebugName(1) or "Font"
                postscript = re.sub(r"[^A-Za-z0-9-]", "", original_ps)[:48] + f"-w{weight}"
                values = {2: style_name, 17: style_name, 4: f"{family} {style_name}", 6: postscript}
                for record in list(font["name"].names):
                    if record.nameID in values:
                        value = values[record.nameID]
                        if record.platformID == 1 and not value.isascii():
                            value = postscript if record.nameID == 4 else style_name
                        font["name"].setName(value, record.nameID, record.platformID, record.platEncID, record.langID)
                for name_id, value in values.items():
                    font["name"].setName(value, name_id, 3, 1, 0x0409)
            font.flavor = None
            output = io.BytesIO()
            font.save(output, reorderTables=False)
            normalized = output.getvalue()
        if len(normalized) > FONT_MAX_BYTES:
            raise AdministrationPayloadTooLargeError("압축 해제한 폰트가 24 MB를 초과합니다.")
        inspected = inspect_font(normalized)
        if inspected.family_name == "WebSubsetFont":
            raise AdministrationValidationError("일부 글자만 포함된 웹 미리보기 파일입니다. 전체 TTF/OTF 파일을 선택해 주세요.")
        return normalized, "variable-to-sfnt.v1" if variable else "woff2-to-sfnt.v1" if signature == b"wOF2" else "woff-to-sfnt.v1"
    except (AdministrationValidationError, AdministrationPayloadTooLargeError):
        raise
    except Exception as exc:
        raise AdministrationValidationError("웹폰트를 자막용 파일로 변환하지 못했습니다. 원본 TTF/OTF를 등록해 주세요.") from exc


def download_noonnu_font(font_id: int, variant: str) -> dict[str, Any]:
    detail = get_noonnu_font(font_id, refresh=True)
    if not detail["can_import"]:
        raise AdministrationValidationError(detail["unavailable_reason"])
    face = next((item for item in detail["variants"] if item["key"] == variant), None)
    if face is None:
        raise AdministrationValidationError("지원하지 않는 글꼴 스타일입니다.")
    audited = audited_font_source(font_id, detail["name"])
    source_info: dict[str, Any] = {}
    if audited and any(item["key"] == variant for item in audited.get("variants", [])):
        source, source_info = download_audited_face(font_id, detail["name"], variant)
    else:
        source = b""
        last_error: Exception | None = None
        for url in face.get("urls", [face["url"]]):
            try:
                source = _download(url, max_bytes=FONT_MAX_BYTES)
                source_info = {"source_url": url}
                break
            except (AdministrationNotFoundError, AdministrationUpstreamError) as exc:
                last_error = exc
        if not source and last_error:
            raise last_error
    try:
        content, conversion = normalize_noonnu_font(source, weight=face["weight"])
    except ValueError as exc:
        raise AdministrationValidationError("유효한 글꼴 파일이 아닙니다.") from exc
    is_otf = content[:4] == b"OTTO"
    return {
        "content": content, "filename": f"noonnu-{font_id}-{variant}.{'otf' if is_otf else 'ttf'}",
        "content_type": "font/otf" if is_otf else "font/ttf",
        "display_name": f"{detail['name']} {face['label']}",
        "license_name": "SIL Open Font License 1.1" if "SIL" in detail["license_text"] and ("오픈" in detail["license_text"] or "Open" in detail["license_text"]) else f"{detail['name']} · 원본 라이선스",
        "source_metadata": {"noonnu": {
            "id": font_id, "name": detail["name"], "variant": variant, "page_url": detail["page_url"],
            "download_page_url": detail["download_page_url"], "source_url": face["url"],
            "source_sha256": hashlib.sha256(source).hexdigest(), "conversion": conversion,
            "selected_weight": face["weight"], "selected_style": face["style"],
            **source_info,
            "license": {"text": detail["license_text"], "permissions": detail["permissions"], "embedded": inspect_font_license(content)},
        }},
    }
