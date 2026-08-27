import socket

import pytest

from worker.ingest import DownloadPolicy, IngestError, YtDlpIngestProvider, validate_public_http_url


def test_local_and_credentialed_urls_are_rejected_without_launching_process():
    with pytest.raises(IngestError):
        validate_public_http_url("http://127.0.0.1/private")
    with pytest.raises(IngestError):
        validate_public_http_url("https://user:secret@example.com/video")


def test_download_requires_explicit_rights_policy(tmp_path):
    provider = YtDlpIngestProvider()
    with pytest.raises(IngestError, match="rights-approved"):
        provider.download("https://example.com/video", DownloadPolicy(allow_media_download=False), tmp_path)


def test_private_dns_resolution_is_rejected(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.1.2.3", 443))])
    with pytest.raises(IngestError, match="private"):
        validate_public_http_url("https://internal.example/video")

