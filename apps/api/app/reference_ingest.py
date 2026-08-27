from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from .video_downloaders import (
    DownloadedVideo,
    FixtureVideoDownloaderAdapter,
    InspectedVideo,
    VideoDownloaderAdapter,
    VideoDownloaderError,
    YtDlpVideoDownloaderAdapter,
    get_video_downloader,
)


# Compatibility names for the Reference ingestion boundary. Concrete
# implementations live behind VideoDownloaderAdapter.
ReferenceIngestError = VideoDownloaderError
InspectedReference = InspectedVideo
DownloadedReference = DownloadedVideo
YtDlpReferenceProvider = YtDlpVideoDownloaderAdapter
FixtureReferenceProvider = FixtureVideoDownloaderAdapter


def get_reference_provider() -> VideoDownloaderAdapter:
    mode = os.getenv("REFERENCE_PROVIDER_MODE", "live").strip().lower()
    if mode == "live":
        return get_video_downloader()
    if mode == "fixture":
        return get_video_downloader("fixture")
    raise ReferenceIngestError("REFERENCE_PROVIDER_MODE must be live or fixture")


def render_proxy(video: bytes) -> bytes:
    with tempfile.TemporaryDirectory(prefix="frameflow-proxy-") as temp_dir:
        directory = Path(temp_dir)
        source = directory / "source.mp4"
        output = directory / "proxy.mp4"
        source.write_bytes(video)
        _run_ffmpeg([
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source),
            "-vf",
            "scale=540:960:force_original_aspect_ratio=decrease,pad=540:960:(ow-iw)/2:(oh-ih)/2:color=black,format=yuv420p",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "28",
            "-c:a",
            "aac",
            "-b:a",
            "96k",
            "-movflags",
            "+faststart",
            str(output),
        ], timeout=600)
        return output.read_bytes()


def _run_ffmpeg(command: list[str], *, timeout: int = 120) -> None:
    try:
        subprocess.run(command, check=True, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise ReferenceIngestError("ffmpeg is not installed") from exc
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        detail = (getattr(exc, "stderr", "") or str(exc))[-1200:]
        raise ReferenceIngestError(f"reference media processing failed: {detail}") from exc
