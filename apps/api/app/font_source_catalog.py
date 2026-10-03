"""Checked font-source inventory; public downloads never accept a caller URL."""
from __future__ import annotations

import hashlib
import io
import json
import zipfile
from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urljoin

import httpx

from .contexts.administration.domain import (
    AdministrationPayloadTooLargeError, AdministrationUpstreamError, AdministrationValidationError,
)
from .font_registry import FONT_MAX_BYTES
from .video_downloaders import VideoDownloaderError, validate_public_url


SOURCE_CATALOG = Path(__file__).with_name("noonnu_sources.v1.json")
ARCHIVE_MAX_BYTES = 96 * 1024 * 1024


@lru_cache(maxsize=1)
def source_catalog() -> dict[str, Any]:
    if not SOURCE_CATALOG.exists():
        return {"fonts": {}, "summary": {}}
    return json.loads(SOURCE_CATALOG.read_text())


def audited_font_source(font_id: int, name: str | None = None) -> dict[str, Any] | None:
    entry = source_catalog()["fonts"].get(str(font_id))
    if entry and (name is None or entry["name"].strip() == name.strip()):
        return entry
    return None


def _public_bytes(url: str, max_bytes: int) -> bytes:
    try:
        with httpx.Client(timeout=httpx.Timeout(60, connect=10), follow_redirects=False,
                          headers={"User-Agent": "Frameflow-Fonts/1.0"}) as client:
            for _ in range(6):
                validate_public_url(url)
                with client.stream("GET", url) as response:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            break
                        url = urljoin(url, location)
                        continue
                    response.raise_for_status()
                    size = response.headers.get("content-length", "")
                    if size.isdigit() and int(size) > max_bytes:
                        raise AdministrationPayloadTooLargeError("제작사 폰트 파일이 자동 등록 크기 제한을 초과합니다.")
                    content = bytearray()
                    for chunk in response.iter_bytes(chunk_size=65536):
                        if len(content) + len(chunk) > max_bytes:
                            raise AdministrationPayloadTooLargeError("제작사 폰트 파일이 자동 등록 크기 제한을 초과합니다.")
                        content.extend(chunk)
                    return bytes(content)
    except (VideoDownloaderError, httpx.HTTPError, ValueError) as exc:
        raise AdministrationUpstreamError("확인된 제작사 파일을 가져오지 못했습니다. 원본 다운로드 링크를 이용해 주세요.") from exc
    raise AdministrationUpstreamError("제작사 파일의 다운로드 주소 이동을 확인하지 못했습니다.")


def unpack_font_archive(content: bytes, member_name: str) -> bytes:
    """Read one audited member in memory; never extract files to disk."""
    member_path = PurePosixPath(member_name.replace("\\", "/"))
    if member_path.is_absolute() or ".." in member_path.parts or not member_name.lower().endswith((".ttf", ".otf", ".woff", ".woff2")):
        raise AdministrationValidationError("유효한 폰트 압축파일 항목이 아닙니다.")
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as package:
            if len(package.infolist()) > 512:
                raise AdministrationPayloadTooLargeError("압축파일의 항목 수가 너무 많습니다.")
            member = package.getinfo(member_name)
            if member.flag_bits & 1:
                raise AdministrationValidationError("암호화된 폰트 압축파일은 자동 등록할 수 없습니다.")
            if member.file_size > FONT_MAX_BYTES:
                raise AdministrationPayloadTooLargeError("압축파일의 폰트가 24 MB를 초과합니다.")
            with package.open(member) as stream:
                font = stream.read(FONT_MAX_BYTES + 1)
            if len(font) > FONT_MAX_BYTES:
                raise AdministrationPayloadTooLargeError("압축 해제한 폰트가 24 MB를 초과합니다.")
            return font
    except (zipfile.BadZipFile, KeyError, RuntimeError) as exc:
        raise AdministrationValidationError("확인된 폰트를 압축파일에서 찾지 못했습니다. 원본 파일을 확인해 주세요.") from exc


def download_audited_face(font_id: int, name: str, variant: str) -> tuple[bytes, dict[str, Any]]:
    entry = audited_font_source(font_id, name)
    face = next((face for face in entry.get("variants", []) if face["key"] == variant), None) if entry else None
    if face is None:
        raise AdministrationValidationError("확인되지 않은 제작사 다운로드 경로입니다.")
    archive_member = face.get("archive_member")
    source = _public_bytes(face["url"], ARCHIVE_MAX_BYTES if archive_member else FONT_MAX_BYTES)
    metadata = {"source_url": face["url"], "evidence_url": face.get("evidence_url"), "source_checked_at": face.get("checked_at")}
    if archive_member:
        metadata.update({"archive_member": archive_member, "archive_sha256": hashlib.sha256(source).hexdigest()})
        source = unpack_font_archive(source, archive_member)
    return source, metadata
