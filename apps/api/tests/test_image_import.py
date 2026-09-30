from functools import partial
import socket

import httpx
import pytest

from app.contexts.artifacts.domain import (
    ArtifactPayloadTooLargeError,
    ArtifactUnsupportedMediaError,
    ArtifactValidationError,
)
from app.image_import import download_image_url


PNG = b"\x89PNG\r\n\x1a\nimage-test"


@pytest.fixture(autouse=True)
def public_dns(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda host, *a, **kw: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1" if host == "internal.test" else "93.184.216.34", 443))
    ])


def test_extensionless_image_redirect_and_artifact_storage(client, monkeypatch):
    requested = []

    def handler(request):
        requested.append(str(request.url))
        if request.url.path == "/download":
            return httpx.Response(302, headers={"location": "/image?id=1"})
        return httpx.Response(200, headers={"content-type": "image/png; charset=binary"}, content=PNG)

    with httpx.Client(transport=httpx.MockTransport(handler)) as remote:
        monkeypatch.setattr(
            "app.infrastructure.persistence.artifact_operations.download_image_url",
            partial(download_image_url, client=remote),
        )
        monkeypatch.setattr(
            "app.infrastructure.persistence.artifact_operations.get_video_downloader",
            lambda: pytest.fail("images must not reach the video downloader"),
        )
        response = client.post("/artifacts/import-url", json={"url": "https://cdn.test/download"})
    assert response.status_code == 201, response.text
    imported = response.json()
    assert imported["type"] == "Image"
    assert imported["content_type"] == "image/png"
    assert imported["filename"] == "image.png"
    assert imported["size_bytes"] == len(PNG)
    assert requested == ["https://cdn.test/download", "https://cdn.test/image?id=1"]
    assert client.get(f"/artifacts/{imported['artifact_id']}/content").content == PNG
    artifact = client.get(f"/artifacts/{imported['artifact_id']}").json()
    assert artifact["metadata"]["source"] == "canvas_url_import"
    assert artifact["metadata"]["immutable"] is True
    assert artifact["metadata"]["source_url"] == "https://cdn.test/image?id=1"
    listed = client.get("/artifacts", params={"types": "Image"}).json()
    assert next(item for item in listed if item["id"] == imported["artifact_id"])["filename"] == "image.png"


@pytest.mark.parametrize("content_type", ["image/jpeg", "application/octet-stream"])
def test_jpeg_url_with_query_preserves_filename(content_type):
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(
        200, headers={"content-type": content_type}, content=b"\xff\xd8\xffjpeg",
    ))) as remote:
        image = download_image_url("https://cdn.test/93105077.2.jpg?size=large", max_bytes=100, client=remote)
    assert image.filename == "93105077.2.jpg"
    assert image.content_type == "image/jpeg"


@pytest.mark.parametrize("headers", [{"content-length": "999"}, {}])
def test_download_size_limit_checks_headers_and_stream(headers):
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(
        200, headers={"content-type": "image/png", **headers}, stream=httpx.ByteStream(PNG),
    ))) as remote:
        with pytest.raises(ArtifactPayloadTooLargeError):
            download_image_url("https://cdn.test/photo", max_bytes=5, client=remote)


def test_redirect_to_private_destination_is_rejected_before_request():
    requested = []

    def handler(request):
        requested.append(str(request.url))
        return httpx.Response(302, headers={"location": "http://internal.test/secret.png"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as remote:
        with pytest.raises(ArtifactValidationError, match="private"):
            download_image_url("https://cdn.test/photo", max_bytes=100, client=remote)
    assert requested == ["https://cdn.test/photo"]


@pytest.mark.parametrize("content_type", ["text/html", "video/mp4"])
def test_video_or_page_response_is_not_consumed(content_type):
    class UnreadBody(httpx.SyncByteStream):
        def __iter__(self):
            pytest.fail("video/page probe must not read the body")
            yield b""

    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(
        200, headers={"content-type": content_type}, stream=UnreadBody(),
    ))) as remote:
        assert download_image_url("https://video.test/watch", max_bytes=100, client=remote) is None


@pytest.mark.parametrize("status,content_type,body,error", [
    (403, "image/png", b"", ArtifactValidationError),
    (200, "image/png", b"", ArtifactValidationError),
    (200, "text/html", b"<html>error</html>", ArtifactUnsupportedMediaError),
])
def test_invalid_image_downloads_are_rejected(status, content_type, body, error):
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(
        status, headers={"content-type": content_type}, content=body,
    ))) as remote:
        with pytest.raises(error):
            download_image_url("https://cdn.test/photo.png", max_bytes=100, client=remote)


def test_video_site_http_rejection_preserves_downloader_fallback():
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(403))) as remote:
        assert download_image_url("https://video.test/watch", max_bytes=100, client=remote) is None


def test_video_import_still_uses_registered_downloader(client, monkeypatch):
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(
        200, headers={"content-type": "text/html"}, content=b"video page",
    ))) as remote:
        monkeypatch.setattr(
            "app.infrastructure.persistence.artifact_operations.download_image_url",
            partial(download_image_url, client=remote),
        )
        response = client.post("/artifacts/import-url", json={"url": "https://youtube.com/watch?v=image-probe"})
    assert response.status_code == 201, response.text
    assert response.json()["type"] == "Video"
    assert response.json()["downloader_provider"] == "fixture"


def test_image_import_error_does_not_create_an_artifact(client, monkeypatch):
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(404))) as remote:
        monkeypatch.setattr(
            "app.infrastructure.persistence.artifact_operations.download_image_url",
            partial(download_image_url, client=remote),
        )
        response = client.post("/artifacts/import-url", json={"url": "https://cdn.test/missing.jpg"})
    assert response.status_code == 422
    assert "HTTP 404" in response.json()["detail"]
    assert client.get("/artifacts", params={"types": "Image"}).json() == []
