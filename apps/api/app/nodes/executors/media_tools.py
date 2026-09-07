from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Protocol


class MediaArtifact(Protocol):
    data: bytes
    content_type: str

    @property
    def type(self) -> str: ...


def artifacts_of_type(artifacts: list[Any], *artifact_types: str) -> list[Any]:
    allowed = set(artifact_types)
    return [artifact for artifact in artifacts if artifact.record.type in allowed]


def run_media_command(
    command: list[str],
    *,
    timeout: int = 180,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(f"required media tool is not installed: {command[0]}") from exc
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        detail = (getattr(exc, "stderr", "") or str(exc))[-1600:]
        raise RuntimeError(f"media operation failed: {detail}") from exc


def media_suffix(content_type: str) -> str:
    return {
        "video/mp4": ".mp4",
        "audio/wav": ".wav",
        "audio/mpeg": ".mp3",
        "audio/mp4": ".m4a",
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/webp": ".webp",
        "text/plain": ".txt",
        "application/json": ".json",
        "application/x-subrip": ".srt",
    }.get(content_type.split(";", 1)[0].lower(), ".bin")


def write_media_artifact(directory: Path, artifact: MediaArtifact, index: int) -> Path:
    path = directory / f"input-{index}{media_suffix(artifact.content_type)}"
    path.write_bytes(artifact.data)
    return path


def probe_media(path: Path) -> dict[str, Any]:
    result = run_media_command([
        "ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path),
    ])
    return json.loads(result.stdout)


def media_duration_seconds(metadata: dict[str, Any]) -> float:
    duration = float((metadata.get("format") or {}).get("duration") or 0)
    if duration <= 0:
        raise ValueError("input media has no positive duration")
    return duration


def video_stream(metadata: dict[str, Any]) -> dict[str, Any]:
    stream = next(
        (item for item in metadata.get("streams", []) if item.get("codec_type") == "video"),
        None,
    )
    if stream is None:
        raise ValueError("input artifact does not contain a video stream")
    return stream
