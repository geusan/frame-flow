from __future__ import annotations

import ipaddress
import json
import os
import socket
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import parse_qs, urlparse


class VideoDownloaderError(RuntimeError):
    pass


@dataclass(frozen=True)
class InspectedVideo:
    canonical_url: str
    source_id: str
    title: str
    creator: str
    duration_ms: int
    width: int
    height: int
    has_subtitles: bool
    estimated_bytes: int
    thumbnail_url: str | None


@dataclass(frozen=True)
class DownloadedVideo:
    video: bytes
    video_content_type: str
    thumbnail: bytes
    thumbnail_content_type: str
    subtitle: bytes | None
    subtitle_content_type: str | None
    info: dict


class VideoDownloaderAdapter(Protocol):
    """Provider-neutral contract used by Reference and Canvas URL ingestion."""

    provider_name: str

    def inspect(self, url: str) -> InspectedVideo: ...

    def download(
        self,
        url: str,
        *,
        max_duration_seconds: int = 600,
        max_filesize_bytes: int | None = None,
    ) -> DownloadedVideo: ...


VideoDownloaderFactory = Callable[[], VideoDownloaderAdapter]
_VIDEO_DOWNLOADER_FACTORIES: dict[str, VideoDownloaderFactory] = {}
_PROVIDER_ALIASES = {"ytdlp": "yt-dlp", "yt_dlp": "yt-dlp"}


def normalize_video_downloader_name(value: str) -> str:
    normalized = value.strip().lower()
    return _PROVIDER_ALIASES.get(normalized, normalized)


def configured_video_downloader_name() -> str:
    return normalize_video_downloader_name(os.getenv("VIDEO_DOWNLOADER_PROVIDER", "yt-dlp"))


def register_video_downloader(
    name: str,
    factory: VideoDownloaderFactory,
    *,
    replace: bool = False,
) -> None:
    normalized = normalize_video_downloader_name(name)
    if not normalized:
        raise ValueError("video downloader provider name cannot be empty")
    if normalized in _VIDEO_DOWNLOADER_FACTORIES and not replace:
        raise ValueError(f"video downloader provider is already registered: {normalized}")
    _VIDEO_DOWNLOADER_FACTORIES[normalized] = factory


def available_video_downloaders() -> tuple[str, ...]:
    return tuple(sorted(_VIDEO_DOWNLOADER_FACTORIES))


def get_video_downloader(provider_name: str | None = None) -> VideoDownloaderAdapter:
    name = normalize_video_downloader_name(provider_name) if provider_name else configured_video_downloader_name()
    factory = _VIDEO_DOWNLOADER_FACTORIES.get(name)
    if not factory:
        available = ", ".join(available_video_downloaders()) or "none"
        raise VideoDownloaderError(f"unknown video downloader provider '{name}' (available: {available})")
    if name == "fixture" and os.getenv("APP_ENV") != "test":
        raise VideoDownloaderError("VIDEO_DOWNLOADER_PROVIDER=fixture is only allowed when APP_ENV=test")
    adapter = factory()
    if normalize_video_downloader_name(adapter.provider_name) != name:
        raise VideoDownloaderError(
            f"video downloader adapter identity mismatch: requested '{name}', got '{adapter.provider_name}'"
        )
    return adapter


def validate_public_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise VideoDownloaderError("only absolute HTTP(S) URLs are accepted")
    if parsed.username or parsed.password:
        raise VideoDownloaderError("URLs containing credentials are not accepted")
    try:
        addresses = {
            item[4][0]
            for item in socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
        }
    except socket.gaierror as exc:
        raise VideoDownloaderError("source hostname could not be resolved") from exc
    if any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise VideoDownloaderError("private, loopback, link-local, and reserved destinations are blocked")
    return value


class YtDlpVideoDownloaderAdapter:
    provider_name = "yt-dlp"

    def __init__(
        self,
        executable: str = "yt-dlp",
        *,
        impersonate_target: str | None = "chrome",
        impersonate_domains: tuple[str, ...] = ("tiktok.com",),
        impersonate_attempts: int = 6,
    ) -> None:
        self.executable = executable
        self.impersonate_target = (impersonate_target or "").strip() or None
        self.impersonate_domains = tuple(domain.strip().lower().lstrip(".") for domain in impersonate_domains if domain.strip())
        self.impersonate_attempts = max(1, impersonate_attempts)
        self._inspection_info: dict[str, dict] = {}

    def _base(self, url: str | None = None) -> list[str]:
        command = [
            self.executable,
            "--ignore-config",
            "--no-playlist",
            "--restrict-filenames",
            "--socket-timeout",
            "15",
            "--retries",
            "2",
        ]
        if url and self.impersonate_target and self._should_impersonate(url):
            command.extend(["--impersonate", self.impersonate_target])
        return command

    def _should_impersonate(self, url: str) -> bool:
        hostname = (urlparse(url).hostname or "").lower().rstrip(".")
        return any(hostname == domain or hostname.endswith(f".{domain}") for domain in self.impersonate_domains)

    def _run(
        self,
        command: list[str],
        *,
        url: str,
        timeout: int,
        failure_message: str,
        cwd: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        attempts = self.impersonate_attempts if self.impersonate_target and self._should_impersonate(url) else 1
        last_error: subprocess.CalledProcessError[str] | None = None
        for _ in range(attempts):
            try:
                return subprocess.run(
                    command,
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    cwd=cwd,
                )
            except FileNotFoundError as exc:
                raise VideoDownloaderError("yt-dlp is not installed") from exc
            except subprocess.TimeoutExpired as exc:
                detail = (exc.stderr or str(exc))[-1200:]
                raise VideoDownloaderError(f"{failure_message}: {detail}") from exc
            except subprocess.CalledProcessError as exc:
                last_error = exc
        assert last_error is not None
        detail = (last_error.stderr or str(last_error))[-1200:]
        raise VideoDownloaderError(f"{failure_message}: {detail}") from last_error

    def inspect(self, url: str) -> InspectedVideo:
        safe_url = validate_public_url(url)
        result = self._run(
            [*self._base(safe_url), "--skip-download", "--dump-single-json", "--", safe_url],
            url=safe_url,
            timeout=60,
            failure_message="metadata inspection failed",
        )
        try:
            info = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise VideoDownloaderError("yt-dlp returned invalid metadata") from exc
        canonical_url = str(info.get("webpage_url") or safe_url)
        self._inspection_info[safe_url] = info
        self._inspection_info[canonical_url] = info
        formats = info.get("formats") or []
        estimated = max(
            (item.get("filesize") or item.get("filesize_approx") or 0 for item in formats),
            default=0,
        )
        subtitles = info.get("subtitles") or info.get("automatic_captions") or {}
        return InspectedVideo(
            canonical_url=canonical_url,
            source_id=str(info.get("id") or _source_id(safe_url)),
            title=str(info.get("title") or "Untitled video")[:512],
            creator=str(info.get("channel") or info.get("uploader") or "Unknown")[:255],
            duration_ms=max(0, round(float(info.get("duration") or 0) * 1000)),
            width=int(info.get("width") or 0),
            height=int(info.get("height") or 0),
            has_subtitles=bool(subtitles),
            estimated_bytes=int(estimated or 0),
            thumbnail_url=info.get("thumbnail"),
        )

    def download(
        self,
        url: str,
        *,
        max_duration_seconds: int = 600,
        max_filesize_bytes: int | None = None,
    ) -> DownloadedVideo:
        safe_url = validate_public_url(url)
        with tempfile.TemporaryDirectory(prefix="frameflow-video-download-") as temp_dir:
            directory = Path(temp_dir)
            template = str(directory / "%(id).80s.%(ext)s")
            inspected_info = self._inspection_info.get(safe_url)
            command = [
                *self._base(safe_url),
                "--match-filter",
                f"duration <=? {max_duration_seconds}",
                "--format",
                "bv*+ba/b/bv*",
                "--format-sort",
                "res:1080",
                "--merge-output-format",
                "mp4",
                "--write-info-json",
                "--write-thumbnail",
                "--write-subs",
                "--write-auto-subs",
                "--sub-langs",
                "ko.*,en.*",
                "--convert-subs",
                "srt",
                "--output",
                template,
            ]
            if max_filesize_bytes is not None:
                command.extend(["--max-filesize", str(max_filesize_bytes)])
            if inspected_info:
                info_input = directory / "inspected-metadata.json"
                info_input.write_text(json.dumps(inspected_info))
                command.extend(["--load-info-json", str(info_input)])
            else:
                command.extend(["--", safe_url])
            self._run(
                command,
                url=safe_url,
                timeout=900,
                failure_message="video download failed",
                cwd=directory,
            )
            files = [path for path in directory.iterdir() if path.is_file()]
            video_path = next(
                (path for path in files if path.suffix.lower() in {".mp4", ".mov", ".mkv", ".webm"}),
                None,
            )
            if not video_path:
                raise VideoDownloaderError("video downloader did not produce a video")
            duration_seconds = _probe_video_duration_seconds(video_path)
            if duration_seconds > max_duration_seconds:
                raise VideoDownloaderError(
                    f"video duration exceeds the {max_duration_seconds} second limit"
                )
            info_path = next((path for path in files if path.name.endswith(".info.json")), None)
            info = json.loads(info_path.read_text()) if info_path else {}
            thumbnail_path = next(
                (path for path in files if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}),
                None,
            )
            if thumbnail_path:
                thumbnail = thumbnail_path.read_bytes()
                thumbnail_content_type = _image_content_type(thumbnail_path.suffix)
            else:
                thumbnail, thumbnail_content_type = _extract_thumbnail(video_path)
            subtitle_path = next(
                (path for path in files if path.suffix.lower() in {".srt", ".vtt", ".ass"}),
                None,
            )
            return DownloadedVideo(
                video=video_path.read_bytes(),
                video_content_type=(
                    "video/mp4"
                    if video_path.suffix.lower() == ".mp4"
                    else f"video/{video_path.suffix.lower().lstrip('.')}"
                ),
                thumbnail=thumbnail,
                thumbnail_content_type=thumbnail_content_type,
                subtitle=subtitle_path.read_bytes() if subtitle_path else None,
                subtitle_content_type="application/x-subrip" if subtitle_path else None,
                info=info,
            )


class FixtureVideoDownloaderAdapter:
    provider_name = "fixture"

    def inspect(self, url: str) -> InspectedVideo:
        source_id = _source_id(url)
        return InspectedVideo(
            url,
            source_id,
            f"Reference preview {source_id}",
            "Fixture provider",
            35_000,
            1080,
            1920,
            True,
            18_400_000,
            None,
        )

    def download(
        self,
        url: str,
        *,
        max_duration_seconds: int = 600,
        max_filesize_bytes: int | None = None,
    ) -> DownloadedVideo:
        del url, max_duration_seconds, max_filesize_bytes
        from .media_preview import render_video_mp4

        video = render_video_mp4("abcdef123456", duration_seconds=1)
        thumbnail, thumbnail_type = _extract_thumbnail_bytes(video)
        return DownloadedVideo(
            video,
            "video/mp4",
            thumbnail,
            thumbnail_type,
            b"1\n00:00:00,000 --> 00:00:01,000\nFixture\n",
            "application/x-subrip",
            {},
        )


def _probe_video_duration_seconds(video_path: Path) -> float:
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                str(video_path),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
        duration = float((json.loads(result.stdout).get("format") or {}).get("duration") or 0)
    except FileNotFoundError as exc:
        raise VideoDownloaderError("ffprobe is not installed") from exc
    except (json.JSONDecodeError, TypeError, ValueError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        detail = (getattr(exc, "stderr", "") or str(exc))[-1200:]
        raise VideoDownloaderError(f"could not determine downloaded video duration: {detail}") from exc
    if duration <= 0:
        raise VideoDownloaderError("could not determine downloaded video duration")
    return duration


def _source_id(url: str) -> str:
    parsed = urlparse(url)
    return parse_qs(parsed.query).get("v", [None])[0] or parsed.path.rstrip("/").split("/")[-1] or "video"


def _extract_thumbnail(video_path: Path) -> tuple[bytes, str]:
    output = video_path.parent / "extracted-thumbnail.jpg"
    _run_ffmpeg([
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        "0",
        "-i",
        str(video_path),
        "-frames:v",
        "1",
        "-q:v",
        "3",
        str(output),
    ])
    return output.read_bytes(), "image/jpeg"


def _extract_thumbnail_bytes(video: bytes) -> tuple[bytes, str]:
    with tempfile.TemporaryDirectory(prefix="frameflow-thumbnail-") as temp_dir:
        path = Path(temp_dir) / "video.mp4"
        path.write_bytes(video)
        return _extract_thumbnail(path)


def _image_content_type(suffix: str) -> str:
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }.get(suffix.lower(), "application/octet-stream")


def _run_ffmpeg(command: list[str], *, timeout: int = 120) -> None:
    try:
        subprocess.run(command, check=True, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise VideoDownloaderError("ffmpeg is not installed") from exc
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        detail = (getattr(exc, "stderr", "") or str(exc))[-1200:]
        raise VideoDownloaderError(f"video media processing failed: {detail}") from exc


register_video_downloader(
    "yt-dlp",
    lambda: YtDlpVideoDownloaderAdapter(
        os.getenv("YT_DLP_EXECUTABLE", "yt-dlp"),
        impersonate_target=os.getenv("YT_DLP_IMPERSONATE_TARGET", "chrome"),
        impersonate_domains=tuple(
            value.strip()
            for value in os.getenv("YT_DLP_IMPERSONATE_DOMAINS", "tiktok.com").split(",")
            if value.strip()
        ),
        impersonate_attempts=int(os.getenv("YT_DLP_IMPERSONATE_ATTEMPTS", "6")),
    ),
)
register_video_downloader("fixture", FixtureVideoDownloaderAdapter)
