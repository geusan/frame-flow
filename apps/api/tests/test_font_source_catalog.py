from __future__ import annotations

import hashlib
import io
import re
import zipfile

import httpx
import pytest

from app import font_source_catalog as sources, noonnu_fonts
from app.contexts.administration.domain import AdministrationPayloadTooLargeError, AdministrationUpstreamError, AdministrationValidationError
from app.video_downloaders import VideoDownloaderError
from test_font_registry_and_caption_documents import minimal_font
from test_noonnu_fonts import detail_html


def archive(member="fonts/fixture.ttf", content=None):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as package:
        package.writestr(member, content if content is not None else minimal_font())
    return stream.getvalue()


def test_inventory_is_complete_and_each_style_has_a_checked_source():
    catalog = sources.source_catalog()
    assert catalog["summary"]["catalog_total"] == len(catalog["fonts"])
    assert catalog["summary"]["noonnu_pages_visited"] == len(catalog["fonts"])
    assert catalog["summary"]["verified_downloads"] == len(catalog["fonts"])
    for key, font in catalog["fonts"].items():
        assert str(font["id"]) == key
        assert font["name"] and font["variants"] and font["original_pages"]
        assert len({face["key"] for face in font["variants"]}) == len(font["variants"])
        for face in font["variants"]:
            assert face["url"].startswith("https://")
            assert face["checked_at"] and face["evidence_url"]
            assert re.fullmatch(r"([1-9][0-9]{0,2}|1000)i?(-[a-z0-9_-]{1,64})?", face["key"])


def test_archive_registration_uses_audited_member_and_preserves_source_hashes(client, monkeypatch):
    zipped = archive()
    entry = {"id": 694, "name": "테스트 글꼴", "name_en": "Test", "checked_at": "2026-10-03", "status": "verified",
             "variants": [{"key": "400-file", "weight": 400, "style": "normal", "label": "Regular", "url": "https://publisher.example/font.zip", "archive_member": "fonts/fixture.ttf", "checked_at": "2026-10-03"}]}
    monkeypatch.setattr(sources, "source_catalog", lambda: {"fonts": {"694": entry}})
    monkeypatch.setattr(noonnu_fonts, "_download", lambda *args, **kwargs: detail_html().encode())
    monkeypatch.setattr(sources, "_public_bytes", lambda *args, **kwargs: zipped)
    noonnu_fonts._cache.clear()
    response = client.post("/fonts/noonnu/import", json={"font_id": 694, "variant": "400-file"})
    assert response.status_code == 201, response.text
    font = response.json()
    assert font["sha256"] == hashlib.sha256(minimal_font()).hexdigest()
    assert font["noonnu"]["archive_member"] == "fonts/fixture.ttf"
    assert font["noonnu"]["archive_sha256"] == hashlib.sha256(zipped).hexdigest()
    assert font["noonnu"]["selected_weight"] == 400
    assert client.get(f"/artifacts/{font['artifact_id']}/content").content == minimal_font()
    noonnu_fonts._cache.clear()


@pytest.mark.parametrize("member", ["../font.ttf", "/font.ttf", "..\\font.ttf", "setup.exe"])
def test_archive_member_must_be_a_font_inside_the_archive(member):
    with pytest.raises(AdministrationValidationError):
        sources.unpack_font_archive(archive(member), member)


def test_archive_rejects_missing_corrupt_and_oversize_members(monkeypatch):
    with pytest.raises(AdministrationValidationError):
        sources.unpack_font_archive(archive(), "missing.ttf")
    with pytest.raises(AdministrationValidationError):
        sources.unpack_font_archive(b"not a zip", "font.ttf")
    monkeypatch.setattr(sources, "FONT_MAX_BYTES", 10)
    with pytest.raises(AdministrationPayloadTooLargeError):
        sources.unpack_font_archive(archive(), "fonts/fixture.ttf")


def test_download_does_not_accept_an_unknown_style_or_reused_id(monkeypatch):
    monkeypatch.setattr(sources, "source_catalog", lambda: {"fonts": {"1": {"name": "Original", "variants": []}}})
    with pytest.raises(AdministrationValidationError):
        sources.download_audited_face(1, "Changed name", "400")
    with pytest.raises(AdministrationValidationError):
        sources.download_audited_face(1, "Original", "400")


def test_publisher_redirect_revalidates_destination_before_fetch(monkeypatch):
    requests, checked = [], []
    def validate(url):
        checked.append(url)
        if "127.0.0.1" in url:
            raise VideoDownloaderError("private address")
    def handler(request):
        requests.append(request)
        return httpx.Response(302, headers={"location": "http://127.0.0.1/private.ttf"})
    client_class = httpx.Client
    monkeypatch.setattr(sources, "validate_public_url", validate)
    monkeypatch.setattr(sources.httpx, "Client", lambda **kwargs: client_class(transport=httpx.MockTransport(handler), **kwargs))
    with pytest.raises(AdministrationUpstreamError):
        sources._public_bytes("https://publisher.example/font.ttf", 100)
    assert len(requests) == 1
    assert len(checked) == 2


def test_publisher_size_limit_is_checked_before_body_read(monkeypatch):
    client_class = httpx.Client
    monkeypatch.setattr(sources, "validate_public_url", lambda url: url)
    monkeypatch.setattr(sources.httpx, "Client", lambda **kwargs: client_class(transport=httpx.MockTransport(lambda request: httpx.Response(200, headers={"content-length": "1000"}, content=b"font")), **kwargs))
    with pytest.raises(AdministrationPayloadTooLargeError):
        sources._public_bytes("https://publisher.example/font.ttf", 10)
