import json
import subprocess

import pytest

import app.video_downloaders as video_downloaders
from app.video_downloaders import (
    DownloadedVideo,
    InspectedVideo,
    VideoDownloaderError,
    YtDlpVideoDownloaderAdapter,
    available_video_downloaders,
    get_video_downloader,
    register_video_downloader,
)


def test_yt_dlp_is_the_configurable_default_adapter(monkeypatch):
    monkeypatch.setenv("VIDEO_DOWNLOADER_PROVIDER", "yt_dlp")
    monkeypatch.setenv("YT_DLP_EXECUTABLE", "/opt/bin/custom-yt-dlp")

    adapter = get_video_downloader()

    assert isinstance(adapter, YtDlpVideoDownloaderAdapter)
    assert adapter.provider_name == "yt-dlp"
    assert adapter.executable == "/opt/bin/custom-yt-dlp"


def test_yt_dlp_impersonation_is_scoped_to_configured_tiktok_domains(monkeypatch):
    monkeypatch.setenv("VIDEO_DOWNLOADER_PROVIDER", "yt-dlp")
    monkeypatch.setenv("YT_DLP_IMPERSONATE_TARGET", "chrome")
    monkeypatch.setenv("YT_DLP_IMPERSONATE_DOMAINS", "tiktok.com")
    adapter = get_video_downloader()

    tiktok_command = adapter._base("https://www.tiktok.com/@creator/video/123")
    short_link_command = adapter._base("https://vm.tiktok.com/example")
    youtube_command = adapter._base("https://www.youtube.com/watch?v=example")

    assert tiktok_command[-2:] == ["--impersonate", "chrome"]
    assert short_link_command[-2:] == ["--impersonate", "chrome"]
    assert "--impersonate" not in youtube_command


def test_yt_dlp_impersonation_can_be_disabled(monkeypatch):
    monkeypatch.setenv("VIDEO_DOWNLOADER_PROVIDER", "yt-dlp")
    monkeypatch.setenv("YT_DLP_IMPERSONATE_TARGET", "")
    adapter = get_video_downloader()

    assert "--impersonate" not in adapter._base("https://www.tiktok.com/@creator/video/123")


def test_tiktok_extraction_retries_the_whole_yt_dlp_process(monkeypatch):
    adapter = YtDlpVideoDownloaderAdapter(impersonate_attempts=2)
    calls = 0

    def fake_run(command, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise subprocess.CalledProcessError(1, command, stderr="TikTok challenge failed")
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps({"id": "123", "title": "Recovered", "duration": 1}),
            stderr="",
        )

    monkeypatch.setattr(video_downloaders, "validate_public_url", lambda url: url)
    monkeypatch.setattr(video_downloaders.subprocess, "run", fake_run)

    inspected = adapter.inspect("https://www.tiktok.com/@creator/video/123")

    assert inspected.title == "Recovered"
    assert calls == 2


def test_download_command_does_not_use_max_downloads_exit_code(monkeypatch):
    adapter = YtDlpVideoDownloaderAdapter(impersonate_attempts=1)
    captured_command: list[str] = []

    def fake_run(command, **kwargs):
        captured_command.extend(command)
        directory = kwargs["cwd"]
        (directory / "123.mp4").write_bytes(b"video")
        (directory / "123.jpg").write_bytes(b"thumbnail")
        (directory / "123.info.json").write_text('{"id":"123"}')
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(video_downloaders, "validate_public_url", lambda url: url)
    monkeypatch.setattr(video_downloaders.subprocess, "run", fake_run)

    adapter.download("https://www.tiktok.com/@creator/video/123")

    assert "--max-downloads" not in captured_command


def test_download_reuses_successful_inspection_metadata(monkeypatch):
    adapter = YtDlpVideoDownloaderAdapter(impersonate_attempts=1)
    commands: list[list[str]] = []

    def fake_run(command, **kwargs):
        commands.append(command)
        if "--dump-single-json" in command:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps({"id": "123", "title": "Cached", "duration": 1}),
                stderr="",
            )
        directory = kwargs["cwd"]
        (directory / "123.mp4").write_bytes(b"video")
        (directory / "123.jpg").write_bytes(b"thumbnail")
        (directory / "123.info.json").write_text('{"id":"123"}')
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(video_downloaders, "validate_public_url", lambda url: url)
    monkeypatch.setattr(video_downloaders.subprocess, "run", fake_run)
    url = "https://www.tiktok.com/@creator/video/123"

    adapter.inspect(url)
    adapter.download(url)

    assert "--load-info-json" in commands[1]
    assert url not in commands[1]


def test_a_new_video_downloader_can_be_registered_and_selected(monkeypatch):
    class CustomAdapter:
        provider_name = "custom-test"

        def inspect(self, url: str) -> InspectedVideo:
            return InspectedVideo(url, "custom", "Custom", "Test", 1000, 1, 1, False, 1, None)

        def download(
            self,
            url: str,
            *,
            max_duration_seconds: int = 600,
            max_filesize_bytes: int | None = None,
        ) -> DownloadedVideo:
            del url, max_duration_seconds, max_filesize_bytes
            return DownloadedVideo(b"video", "video/mp4", b"thumb", "image/jpeg", None, None, {})

    register_video_downloader("custom-test", CustomAdapter, replace=True)
    monkeypatch.setenv("VIDEO_DOWNLOADER_PROVIDER", "custom-test")

    assert "custom-test" in available_video_downloaders()
    assert isinstance(get_video_downloader(), CustomAdapter)


def test_unknown_video_downloader_is_a_configuration_error(monkeypatch):
    monkeypatch.setenv("VIDEO_DOWNLOADER_PROVIDER", "missing-provider")

    with pytest.raises(VideoDownloaderError, match="unknown video downloader provider"):
        get_video_downloader()
