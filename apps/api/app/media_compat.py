from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


class BrowserVideoError(RuntimeError):
    pass


@dataclass(frozen=True)
class BrowserVideoResult:
    content: bytes
    content_type: str
    video_codec: str
    audio_codec: str | None
    duration_ms: int
    width: int
    height: int
    transcoded: bool


BROWSER_VIDEO_CODECS = {"h264", "av1", "vp8", "vp9"}
BROWSER_AUDIO_CODECS = {"aac", "mp3", "opus", "vorbis"}


def ensure_browser_video(video: bytes, content_type: str) -> BrowserVideoResult:
    if not video:
        raise BrowserVideoError("source video is empty")
    with tempfile.TemporaryDirectory(prefix="frameflow-browser-video-") as temp_dir:
        directory = Path(temp_dir)
        source = directory / _source_name(content_type)
        output = directory / "browser.mp4"
        source.write_bytes(video)
        metadata = _probe(source)
        streams = metadata.get("streams") or []
        video_stream = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
        audio_stream = next((stream for stream in streams if stream.get("codec_type") == "audio"), None)
        if not video_stream:
            raise BrowserVideoError("uploaded media does not contain a video stream")
        video_codec = str(video_stream.get("codec_name") or "unknown").lower()
        audio_codec = str(audio_stream.get("codec_name") or "unknown").lower() if audio_stream else None
        duration_ms = max(0, round(float((metadata.get("format") or {}).get("duration") or 0) * 1000))
        width = int(video_stream.get("width") or 0)
        height = int(video_stream.get("height") or 0)
        compatible = video_codec in BROWSER_VIDEO_CODECS and (audio_codec is None or audio_codec in BROWSER_AUDIO_CODECS)
        if compatible:
            return BrowserVideoResult(video, content_type, video_codec, audio_codec, duration_ms, width, height, False)

        command = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
            "-map", "0:v:0", "-map", "0:a?",
            "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
            "-c:v", "libx264", "-preset", "fast", "-crf", "21", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(output),
        ]
        _run(command, timeout=900)
        if not output.exists() or not output.stat().st_size:
            raise BrowserVideoError("browser video conversion produced no output")
        converted = _probe(output)
        converted_streams = converted.get("streams") or []
        converted_video = next(stream for stream in converted_streams if stream.get("codec_type") == "video")
        converted_audio = next((stream for stream in converted_streams if stream.get("codec_type") == "audio"), None)
        return BrowserVideoResult(
            output.read_bytes(),
            "video/mp4",
            str(converted_video.get("codec_name") or "h264"),
            str(converted_audio.get("codec_name") or "aac") if converted_audio else None,
            max(0, round(float((converted.get("format") or {}).get("duration") or 0) * 1000)),
            int(converted_video.get("width") or width),
            int(converted_video.get("height") or height),
            True,
        )


def _source_name(content_type: str) -> str:
    suffix = {
        "video/mp4": ".mp4",
        "video/webm": ".webm",
        "video/quicktime": ".mov",
        "video/mkv": ".mkv",
        "video/x-matroska": ".mkv",
    }.get(content_type.split(";", 1)[0].lower(), ".video")
    return f"source{suffix}"


def _probe(path: Path) -> dict[str, object]:
    result = _run([
        "ffprobe", "-v", "error", "-show_entries",
        "stream=codec_name,codec_type,width,height:format=duration", "-of", "json", str(path),
    ], timeout=90)
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise BrowserVideoError("ffprobe returned invalid video metadata") from exc


def _run(command: list[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(command, check=True, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise BrowserVideoError(f"required media tool is not installed: {command[0]}") from exc
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        detail = (getattr(exc, "stderr", "") or str(exc))[-1600:]
        raise BrowserVideoError(f"browser video conversion failed: {detail}") from exc
