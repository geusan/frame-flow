from __future__ import annotations

import hashlib
import json
import struct

import httpx
import pytest
from sqlalchemy import select

from app import google_fonts
from app.caption_documents import canonical_caption_document
from app.contexts.administration.domain import AdministrationPayloadTooLargeError, AdministrationUpstreamError
from app.database import ArtifactRecord, FontRecord, SessionLocal
from test_font_registry_and_caption_documents import minimal_font


CATALOG = {"familyMetadataList": [
    {"family": "Frameflow Test Sans", "displayName": "Test Korean", "category": "Sans Serif", "subsets": ["latin", "korean"], "fonts": {"400": {}, "700i": {}}, "popularity": 2},
    {"family": "Roboto", "category": "Sans Serif", "subsets": ["latin"], "fonts": {"400": {}}, "popularity": 1},
    {"family": "Restricted Font", "fonts": {"400": {}}, "isOpenSource": False},
]}
FONT_URL = "https://fonts.gstatic.com/s/test/v1/regular.ttf"
CSS = f"@font-face {{font-family:'Frameflow Test Sans'; src: url({FONT_URL}) format('truetype');}}"


@pytest.fixture(autouse=True)
def clear_catalog(monkeypatch):
    monkeypatch.setattr(google_fonts, "_catalog", None)


@pytest.fixture()
def upstream(monkeypatch):
    requests = []
    state = {"css": CSS, "font": minimal_font(), "catalog": CATALOG, "status": 200}

    def handler(request):
        requests.append(request)
        if request.url.host == "fonts.google.com":
            return httpx.Response(state["status"], json=state["catalog"])
        if request.url.host == "fonts.googleapis.com":
            return httpx.Response(state["status"], text=state["css"])
        assert str(request.url) == FONT_URL
        return httpx.Response(state["status"], content=state["font"])

    client_class = httpx.Client
    monkeypatch.setattr(google_fonts.httpx, "Client", lambda **kwargs: client_class(transport=httpx.MockTransport(handler), **kwargs))
    return state, requests


def test_catalog_search_filters_pages_and_caches(client, upstream):
    _, requests = upstream
    result = client.get("/fonts/google", params={"limit": 1}).json()
    assert result["total"] == 2
    assert result["catalog_total"] == 2
    assert result["korean_total"] == 1
    assert result["items"][0]["family"] == "Roboto"
    assert client.get("/fonts/google", params={"offset": 1, "limit": 1}).json()["items"][0]["family"] == "Frameflow Test Sans"
    korean = client.get("/fonts/google", params={"korean_only": True}).json()
    assert korean["total"] == 1
    assert korean["catalog_total"] == 2
    assert korean["items"][0]["variants"] == ["400", "700i"]
    assert client.get("/fonts/google", params={"q": "frameflowtestsans"}).json()["total"] == 1
    assert client.get("/fonts/google", params={"q": "test korean"}).json()["total"] == 1
    assert client.get("/fonts/google", params={"q": "missing"}).json()["total"] == 0
    assert len(requests) == 1


def test_import_persists_original_face_provenance_and_deduplicates(client, upstream):
    state, requests = upstream
    payload = {"family": "Frameflow Test Sans", "variant": "400"}
    response = client.post("/fonts/google/import", json=payload)
    assert response.status_code == 201, response.text
    font = response.json()
    assert font["created"] is True
    assert font["lifecycle"] == "ACTIVE"
    assert font["sha256"] == hashlib.sha256(state["font"]).hexdigest()
    assert font["google_fonts"]["family"] == payload["family"]
    assert font["google_fonts"]["variant"] == "400"
    assert font["google_fonts"]["url"] == FONT_URL
    assert requests[1].url.params["family"] == "Frameflow Test Sans:ital,wght@0,400"
    assert requests[1].headers["User-Agent"] == "Frameflow-Fonts/1.0"
    repeated = client.post("/fonts/google/import", json=payload).json()
    assert repeated["created"] is False
    assert repeated["id"] == font["id"]
    assert client.get("/fonts").json()[0]["id"] == font["id"]
    assert client.get(f"/artifacts/{font['artifact_id']}/content").content == state["font"]
    with SessionLocal() as db:
        assert len(db.scalars(select(FontRecord)).all()) == 1
        artifact = db.get(ArtifactRecord, font["artifact_id"])
        assert artifact.schema_id == "font.face.v1"
        assert artifact.metadata_json["immutable"] is True
        assert artifact.metadata_json["google_fonts"]["url"] == FONT_URL
        caption = canonical_caption_document(db, {
            "schema_version": "caption.document.v1",
            "content": {"type": "doc", "content": [{"type": "paragraph", "content": [{
                "type": "text", "text": "[00:00-00:03] 자막",
                "marks": [{"type": "textStyle", "attrs": {"fontId": font["id"], "fontFamily": font["css_family"]}}],
            }]}]},
        })
        assert caption["fonts"][0]["sha256"] == font["sha256"]


def test_import_italic_uses_selected_weight_and_style(client, upstream):
    state, requests = upstream
    content = bytearray(minimal_font().replace("Regular".encode("utf-16-be"), "Italic ".encode("utf-16-be")))
    for index in range(struct.unpack_from(">H", content, 4)[0]):
        record = 12 + index * 16
        if content[record:record + 4] == b"OS/2":
            offset = struct.unpack_from(">I", content, record + 8)[0]
            struct.pack_into(">H", content, offset + 4, 700)
    state["font"] = bytes(content)
    response = client.post("/fonts/google/import", json={"family": "Frameflow Test Sans", "variant": "700i"})
    assert response.status_code == 201, response.text
    assert response.json()["weight"] == 700
    assert response.json()["style"] == "italic"
    assert requests[1].url.params["family"] == "Frameflow Test Sans:ital,wght@1,700"


@pytest.mark.parametrize("payload,status", [
    ({"family": "Unknown", "variant": "400"}, 404),
    ({"family": "Restricted Font", "variant": "400"}, 404),
    ({"family": "Frameflow Test Sans", "variant": "900"}, 422),
    ({"family": "Frameflow Test Sans", "variant": "400&family=Roboto"}, 422),
])
def test_invalid_selection_never_downloads_a_font(client, upstream, payload, status):
    _, requests = upstream
    assert client.post("/fonts/google/import", json=payload).status_code == status
    assert all(request.url.host == "fonts.google.com" for request in requests)


@pytest.mark.parametrize("css", [
    "@font-face { src: url(http://localhost/private.ttf); }",
    "@font-face { src: url(https://fonts.gstatic.com.evil.test/s/font.ttf); }",
    "@font-face { src: url(https://fonts.gstatic.com@evil.test/s/font.ttf); }",
    "@font-face { src: url(https://fonts.gstatic.com/s/font.woff2); }",
    CSS + CSS,
    CSS + " /* unicode-range: U+0000-00FF */",
])
def test_invalid_or_subset_downloads_are_rejected_before_fetch(client, upstream, css):
    state, requests = upstream
    state["css"] = css
    response = client.post("/fonts/google/import", json={"family": "Frameflow Test Sans"})
    assert response.status_code == 502
    assert len(requests) == 2
    assert client.get("/fonts").json() == []


def test_invalid_binary_and_wrong_style_are_not_registered(client, upstream):
    state, _ = upstream
    state["font"] = b"not a font"
    assert client.post("/fonts/google/import", json={"family": "Frameflow Test Sans"}).status_code == 502
    state["font"] = minimal_font()
    assert client.post("/fonts/google/import", json={"family": "Frameflow Test Sans", "variant": "700i"}).status_code == 502
    assert client.get("/fonts").json() == []


def test_catalog_outage_and_bad_format_are_retryable(client, upstream):
    state, _ = upstream
    state["status"] = 503
    assert client.get("/fonts/google").status_code == 502
    state["status"] = 200
    state["catalog"] = {"unexpected": []}
    assert client.get("/fonts/google").status_code == 502
    state["catalog"] = CATALOG
    assert client.get("/fonts/google").status_code == 200


def test_download_size_limit_is_enforced(upstream):
    with pytest.raises(AdministrationPayloadTooLargeError):
        google_fonts._download(FONT_URL, max_bytes=10)


def test_redirects_are_not_followed(monkeypatch):
    client_class = httpx.Client
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(302, headers={"location": "http://localhost/private.ttf"})

    monkeypatch.setattr(google_fonts.httpx, "Client", lambda **kwargs: client_class(transport=httpx.MockTransport(handler), **kwargs))
    with pytest.raises(AdministrationUpstreamError):
        google_fonts._download(FONT_URL, max_bytes=100)
    assert len(requests) == 1


def test_catalog_accepts_google_xssi_prefix(monkeypatch):
    monkeypatch.setattr(google_fonts, "_download", lambda *args, **kwargs: (")]}'\n" + json.dumps(CATALOG)).encode())
    assert google_fonts.search_google_fonts("Roboto", False, 0, 6)["total"] == 1
