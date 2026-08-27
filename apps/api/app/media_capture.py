from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


class MediaCaptureError(RuntimeError):
    pass


@dataclass(frozen=True)
class CapturedVideoFrame:
    content: bytes
    content_type: str
    timestamp_ms: int
    source_duration_ms: int
    width: int
    height: int


def capture_video_frame(video: bytes, content_type: str, timestamp_ms: int) -> CapturedVideoFrame:
    if not video:
        raise MediaCaptureError("source video is empty")
    if timestamp_ms < 0:
        raise MediaCaptureError("capture timestamp cannot be negative")

    with tempfile.TemporaryDirectory(prefix="frameflow-frame-capture-") as temp_dir:
        directory = Path(temp_dir)
        suffix = {
            "video/mp4": ".mp4",
            "video/webm": ".webm",
            "video/quicktime": ".mov",
            "video/mkv": ".mkv",
            "video/x-matroska": ".mkv",
        }.get(content_type.split(";", 1)[0].lower(), ".video")
        source = directory / f"source{suffix}"
        output = directory / "captured-frame.jpg"
        source.write_bytes(video)

        probe = _run([
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,duration:format=duration",
            "-of",
            "json",
            str(source),
        ], timeout=60)
        try:
            metadata = json.loads(probe.stdout)
        except json.JSONDecodeError as exc:
            raise MediaCaptureError("ffprobe returned invalid video metadata") from exc
        stream = (metadata.get("streams") or [{}])[0]
        duration_seconds = float(stream.get("duration") or (metadata.get("format") or {}).get("duration") or 0)
        duration_ms = max(0, round(duration_seconds * 1000))
        if duration_ms and timestamp_ms > duration_ms:
            raise MediaCaptureError(
                f"capture timestamp {timestamp_ms}ms exceeds video duration {duration_ms}ms"
            )
        effective_timestamp_ms = min(timestamp_ms, max(0, duration_ms - 1)) if duration_ms else timestamp_ms

        _run([
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source),
            "-ss",
            f"{effective_timestamp_ms / 1000:.3f}",
            "-map",
            "0:v:0",
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(output),
        ], timeout=180)
        if not output.exists() or not output.stat().st_size:
            raise MediaCaptureError("frame capture did not produce an image")
        return CapturedVideoFrame(
            content=output.read_bytes(),
            content_type="image/jpeg",
            timestamp_ms=effective_timestamp_ms,
            source_duration_ms=duration_ms,
            width=int(stream.get("width") or 0),
            height=int(stream.get("height") or 0),
        )


def _run(command: list[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(command, check=True, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise MediaCaptureError(f"required media tool is not installed: {command[0]}") from exc
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        detail = (getattr(exc, "stderr", "") or str(exc))[-1200:]
        raise MediaCaptureError(f"frame capture failed: {detail}") from exc
