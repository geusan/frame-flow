import pytest

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
