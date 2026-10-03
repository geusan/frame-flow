from __future__ import annotations

import hashlib
import io
import json
import struct

import httpx
import pytest
from fontTools.ttLib import TTFont, newTable

from app import noonnu_fonts
from app.contexts.administration.domain import AdministrationPayloadTooLargeError, AdministrationValidationError, AdministrationUpstreamError
from app.font_registry import FONT_MAX_BYTES, inspect_font
from test_font_registry_and_caption_documents import minimal_font


FONT_URL = "https://cdn.jsdelivr.net/gh/projectnoonnu/fixture@1.0/regular.woff2"
CSS = f"@font-face {{font-family: 'TestFont';src: url('{FONT_URL}') format('woff2');font-weight: 400;}}"
CATALOG = {"fonts": [
    {"id": 694, "name": "테스트 글꼴", "name_en": "Test Font", "creator_description": "Test designer",
     "cdn_server_html": CSS, "font_variants_count": 1, "is_market": False},
    {"id": 999, "name": "Paid preview", "is_market": True},
], "total_count": 1, "is_last_page": True}


def detail_html(css=CSS, embedding="사용 가능", price="0", with_license=True):
    schema = {"@type": "SoftwareApplication", "name": "테스트 글꼴", "offers": {"price": price}, "creator": {"name": "Test designer"}}
    rows = "".join(f"<tr><td>{key}</td><td>Scope</td><td>{value}</td></tr>" for key, value in [("영상", "사용 가능"), ("웹사이트", "사용 가능"), ("임베딩", embedding)])
    return f'''<script type="application/ld+json">{json.dumps(schema)}</script>
      <a href="https://example.com/original">다운로드 페이지로 이동</a>
      {"<article>SIL 오픈 폰트 라이선스<br />Fixture license</article>" if with_license else ""}
      <table>{rows}</table><pre name="webfontSource">{css}</pre>'''


def webfont(flavor="woff2"):
    with TTFont(io.BytesIO(minimal_font()), recalcTimestamp=False, recalcBBoxes=False) as font:
        font.flavor = flavor
        output = io.BytesIO()
        font.save(output)
        return output.getvalue()


@pytest.fixture(autouse=True)
def clean_cache():
    noonnu_fonts._cache.clear()
    yield
    noonnu_fonts._cache.clear()


@pytest.fixture()
def upstream(monkeypatch):
    state = {"catalog": CATALOG, "detail": detail_html(), "font": webfont(), "status": 200}
    requests = []
    client_class = httpx.Client

    def handler(request):
        requests.append(request)
        if request.url.host == "noonnu.cc":
            if request.url.path.startswith("/font_page/"):
                return httpx.Response(state["status"], text=state["detail"])
            assert request.headers["accept"] == "application/json"
            return httpx.Response(state["status"], json=state["catalog"])
        assert str(request.url) == FONT_URL
        return httpx.Response(state["status"], content=state["font"])

    monkeypatch.setattr(noonnu_fonts.httpx, "Client", lambda **kwargs: client_class(transport=httpx.MockTransport(handler), **kwargs))
    return state, requests


def test_search_uses_korean_query_pagination_and_excludes_paid_previews(client, upstream):
    _, requests = upstream
    response = client.get("/fonts/noonnu", params={"q": "테스트 글꼴", "page": 2})
    assert response.status_code == 200, response.text
    result = response.json()
    assert len(result["items"]) == 1
    assert result["items"][0]["name"] == "테스트 글꼴"
    assert result["items"][0]["preview"]["url"] == FONT_URL
    assert result["page"] == 2 and result["has_more"] is False
    assert requests[0].url.path == "/search/테스트 글꼴"
    assert requests[0].url.params["page"] == "2"
    client.get("/fonts/noonnu", params={"q": "테스트 글꼴", "page": 2})
    assert len(requests) == 1


def test_detail_reads_published_source_and_license_without_executing_html(client, upstream):
    response = client.get("/fonts/noonnu/694")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["can_import"] is True
    assert data["variants"][0]["key"] == "400"
    assert data["permissions"]["임베딩"] == "사용 가능"
    assert data["download_page_url"] == "https://example.com/original"
    assert "Fixture license" in data["license_text"]


def test_import_converts_woff2_records_provenance_and_is_idempotent(client, upstream):
    state, _ = upstream
    first = client.post("/fonts/noonnu/import", json={"font_id": 694, "variant": "400"})
    assert first.status_code == 201, first.text
    font = first.json()
    assert font["created"] is True
    assert font["noonnu"]["id"] == 694
    assert font["noonnu"]["conversion"] == "woff2-to-sfnt.v1"
    assert font["noonnu"]["source_sha256"] == hashlib.sha256(state["font"]).hexdigest()
    assert "Fixture license" in font["noonnu"]["license"]["text"]
    content = client.get(f"/artifacts/{font['artifact_id']}/content").content
    assert content[:4] == b"\0\1\0\0"
    assert hashlib.sha256(content).hexdigest() == font["sha256"]
    assert inspect_font(content).family_name == "Frameflow Test Sans"
    second = client.post("/fonts/noonnu/import", json={"font_id": 694, "variant": "400"}).json()
    assert second["id"] == font["id"] and second["created"] is False


@pytest.mark.parametrize("embedding", ["사용 불가", "조건부 허용", "", "알 수 없음"])
def test_restricted_or_unknown_embedding_has_original_link_and_cannot_import(client, upstream, embedding):
    state, requests = upstream
    state["detail"] = detail_html(embedding=embedding)
    detail = client.get("/fonts/noonnu/694").json()
    assert detail["can_import"] is False
    assert detail["download_page_url"]
    response = client.post("/fonts/noonnu/import", json={"font_id": 694})
    assert response.status_code == 422
    assert all(request.url.host == "noonnu.cc" for request in requests)
    assert client.get("/fonts").json() == []


def test_import_refreshes_license_instead_of_using_stale_detail(client, upstream):
    state, _ = upstream
    assert client.get("/fonts/noonnu/694").json()["can_import"] is True
    state["detail"] = detail_html(embedding="사용 불가")
    assert client.post("/fonts/noonnu/import", json={"font_id": 694}).status_code == 422


@pytest.mark.parametrize("html", [detail_html(price="10000"), detail_html(with_license=False), detail_html(css="")])
def test_paid_fonts_missing_license_or_missing_source_never_import(client, upstream, html):
    state, requests = upstream
    state["detail"] = html
    assert client.post("/fonts/noonnu/import", json={"font_id": 694}).status_code == 422
    assert all(request.url.host == "noonnu.cc" for request in requests)


@pytest.mark.parametrize("url", ["http://localhost/font.ttf", "https://cdn.jsdelivr.net.evil.test/font.woff2", "https://cdn.jsdelivr.net@evil.test/font.woff2", "https://cdn.jsdelivr.net:8443/font.woff2", "https://127.0.0.1/font.ttf", "data:font/woff2;base64,AAAA"])
def test_untrusted_download_urls_are_never_exposed_or_fetched(upstream, url):
    _, requests = upstream
    assert noonnu_fonts._variants(CSS.replace(FONT_URL, url)) == []
    with pytest.raises(AdministrationValidationError):
        noonnu_fonts._download(url)
    assert requests == []


@pytest.mark.parametrize("css", [CSS.replace("font-weight: 400", "font-weight: 400; unicode-range: U+0000-00FF"), CSS + CSS.replace("regular.woff2", "other.woff2")])
def test_subsets_and_ambiguous_faces_are_not_importable(css):
    assert noonnu_fonts._variants(css) == []


def test_variable_css_exposes_only_weights_in_declared_range():
    faces = noonnu_fonts._variants(CSS.replace("font-weight: 400", "font-weight: 300 700"))
    assert [face["weight"] for face in faces] == [300, 400, 500, 600, 700]


def test_protocol_relative_and_korean_space_urls_are_normalized():
    faces = noonnu_fonts._variants(CSS.replace(FONT_URL, "//cdn.jsdelivr.net/gh/projectnoonnu/release/한글 이름.woff2"))
    assert faces[0]["url"] == "https://cdn.jsdelivr.net/gh/projectnoonnu/release/%ED%95%9C%EA%B8%80%20%EC%9D%B4%EB%A6%84.woff2"


def test_google_stylesheet_import_resolves_full_font_and_ignores_unknown_css(monkeypatch):
    requested = []
    def download(url, **kwargs):
        requested.append(url)
        return CSS.replace(FONT_URL, "https://fonts.gstatic.com/ea/example/font.ttf").encode()
    monkeypatch.setattr(noonnu_fonts, "_download", download)
    faces = noonnu_fonts._resolve_variants("@import url('//fonts.googleapis.com/earlyaccess/example.css'); @import url('https://evil.invalid/css');")
    assert requested == ["https://fonts.googleapis.com/earlyaccess/example.css"]
    assert faces[0]["source_kind"] == "google_fonts"
    assert faces[0]["url"].endswith("font.ttf")


def test_shared_publisher_stylesheet_selects_family_and_normal_width():
    css = CSS.replace("TestFont", "Galmuri11").replace(FONT_URL, "./Regular.woff2")
    css += css.replace("./Regular.woff2", "./Condensed.woff2").replace("font-weight: 400", "font-weight: 400; font-stretch: condensed")
    css += CSS.replace("TestFont", "Galmuri9").replace(FONT_URL, "./Other.woff2")
    faces = noonnu_fonts._variants(css, base_url="https://cdn.jsdelivr.net/npm/font/dist/font.css", family_hints=["Galmuri 11"])
    assert len(faces) == 1
    assert faces[0]["url"] == "https://cdn.jsdelivr.net/npm/font/dist/Regular.woff2"


def test_variable_instancing_pins_weight_and_produces_stable_static_font():
    from fontTools.fontBuilder import FontBuilder
    from fontTools.pens.ttGlyphPen import TTGlyphPen
    builder = FontBuilder(1000, isTTF=True)
    builder.setupGlyphOrder([".notdef", "ga"])
    builder.setupCharacterMap({0xAC00: "ga"})
    pen = TTGlyphPen(None)
    pen.moveTo((100, 0)); pen.lineTo((600, 0)); pen.lineTo((600, 700)); pen.lineTo((100, 700)); pen.closePath()
    builder.setupGlyf({".notdef": TTGlyphPen(None).glyph(), "ga": pen.glyph()})
    builder.setupHorizontalMetrics({name: (1000, 0) for name in [".notdef", "ga"]})
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    builder.setupNameTable({"familyName": "Variable Test", "styleName": "Regular", "uniqueFontIdentifier": "VariableTest", "fullName": "Variable Test Regular", "psName": "VariableTest-Regular"})
    builder.setupOS2(sTypoAscender=800, sTypoDescender=-200, usWinAscent=800, usWinDescent=200)
    builder.setupPost()
    builder.setupFvar([("wght", 100, 400, 900, "Weight")], [])
    output = io.BytesIO(); builder.save(output)
    first, conversion = noonnu_fonts.normalize_noonnu_font(output.getvalue(), weight=700)
    second, _ = noonnu_fonts.normalize_noonnu_font(output.getvalue(), weight=700)
    assert first == second
    assert conversion == "variable-to-sfnt.v1"
    assert inspect_font(first).weight == 700
    regular, _ = noonnu_fonts.normalize_noonnu_font(output.getvalue(), weight=400)
    assert inspect_font(first).subfamily_name == "Bold"
    assert inspect_font(first).postscript_name != inspect_font(regular).postscript_name
    with TTFont(io.BytesIO(first)) as static:
        assert "fvar" not in static
    with pytest.raises(AdministrationValidationError, match="굵기"):
        noonnu_fonts.normalize_noonnu_font(output.getvalue(), weight=1000)


@pytest.mark.parametrize("flavor", ["woff", "woff2"])
def test_decompression_is_deterministic_and_preserves_font_metrics(flavor):
    source = webfont(flavor)
    first, _ = noonnu_fonts.normalize_noonnu_font(source)
    second, _ = noonnu_fonts.normalize_noonnu_font(source)
    assert first == second
    assert inspect_font(first) == inspect_font(minimal_font())


def test_decompression_rejects_oversized_sfnt_header_before_loading():
    content = bytearray(webfont())
    struct.pack_into(">I", content, 16, FONT_MAX_BYTES + 1)
    with pytest.raises(AdministrationPayloadTooLargeError):
        noonnu_fonts.normalize_noonnu_font(bytes(content))


def test_static_ttf_bytes_remain_unchanged():
    content, conversion = noonnu_fonts.normalize_noonnu_font(minimal_font())
    assert content == minimal_font()
    assert conversion == "none"


def test_variable_font_file_is_not_silently_registered_as_a_static_weight():
    with TTFont(io.BytesIO(minimal_font()), recalcTimestamp=False, recalcBBoxes=False) as font:
        axis_table = newTable("fvar")
        axis_table.axes = []
        axis_table.instances = []
        font["fvar"] = axis_table
        output = io.BytesIO()
        font.save(output)
    with pytest.raises(AdministrationValidationError, match="가변 폰트"):
        noonnu_fonts.normalize_noonnu_font(output.getvalue())


def test_streaming_download_size_limit(upstream):
    with pytest.raises(AdministrationPayloadTooLargeError):
        noonnu_fonts._download(FONT_URL, max_bytes=10)


def test_outage_malformed_detail_and_invalid_style_return_useful_errors(client, upstream):
    state, _ = upstream
    state["status"] = 503
    assert client.get("/fonts/noonnu").status_code == 502
    state["status"] = 200
    state["detail"] = "<html>Service unavailable</html>"
    assert client.get("/fonts/noonnu/694").status_code == 502
    state["detail"] = detail_html()
    assert client.post("/fonts/noonnu/import", json={"font_id": 694, "variant": "700"}).status_code == 422
    assert client.get("/fonts/noonnu/-1").status_code == 422
    assert client.get("/fonts/noonnu", params={"q": "a" * 41}).status_code == 422


def test_cdn_redirect_is_not_followed(monkeypatch):
    client_class = httpx.Client
    seen = []
    def redirect(request):
        seen.append(request)
        return httpx.Response(302, headers={"location": "http://127.0.0.1/private.ttf"})
    monkeypatch.setattr(noonnu_fonts.httpx, "Client", lambda **kwargs: client_class(transport=httpx.MockTransport(redirect), **kwargs))
    with pytest.raises(AdministrationUpstreamError):
        noonnu_fonts._download(FONT_URL)
    assert len(seen) == 1
