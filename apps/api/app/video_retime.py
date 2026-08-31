from __future__ import annotations

import json
import math
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


VIDEO_RETIME_REVISION = "video-retime.v1"
VIDEO_RETIME_SCHEMA = "video.retime.v1"


@dataclass(frozen=True)
class RetimedVideo:
    data: bytes
    width: int
    height: int
    fps: int
    source_duration_ms: int
    duration_ms: int
    has_audio: bool


def _probe(path: Path) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            ["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
            check=True, capture_output=True, text=True, timeout=90,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("ffprobe is required to retime Video") from exc
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        detail = (getattr(exc, "stderr", "") or str(exc))[-1600:]
        raise RuntimeError(f"Video retime probe failed: {detail}") from exc
    return json.loads(completed.stdout)


def _atempo_chain(speed_multiplier: float) -> str:
    remaining = speed_multiplier
    factors: list[float] = []
    while remaining > 2.0:
        factors.append(2.0)
        remaining /= 2.0
    while remaining < 0.5:
        factors.append(0.5)
        remaining /= 0.5
    factors.append(remaining)
    return ",".join(f"atempo={factor:.8f}" for factor in factors)


def retime_video(
    video_data: bytes,
    content_type: str,
    *,
    speed_multiplier: float,
    output_fps: int,
    preserve_audio: bool,
) -> RetimedVideo:
    with tempfile.TemporaryDirectory(prefix="frameflow-video-retime-") as temp_dir:
        directory = Path(temp_dir)
        source_path = directory / ("source.mp4" if "mp4" in content_type else "source.video")
        source_path.write_bytes(video_data)
        metadata = _probe(source_path)
        stream = next((item for item in metadata.get("streams", []) if item.get("codec_type") == "video"), None)
        if not stream:
            raise ValueError("Video Retime requires a video stream")
        source_duration = float((metadata.get("format") or {}).get("duration") or 0)
        if source_duration <= 0:
            raise ValueError("Video Retime input duration must be positive")
        has_audio = preserve_audio and any(item.get("codec_type") == "audio" for item in metadata.get("streams", []))
        output_path = directory / "retimed.mp4"
        video_filter = f"setpts=PTS/{speed_multiplier:.8f},fps={output_fps},format=yuv420p"
        command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source_path)]
        if has_audio:
            command.extend([
                "-filter_complex", f"[0:v]{video_filter}[v];[0:a]{_atempo_chain(speed_multiplier)}[a]",
                "-map", "[v]", "-map", "[a]", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
            ])
        else:
            command.extend(["-map", "0:v:0", "-vf", video_filter, "-an"])
        command.extend([
            "-c:v", "libx264", "-profile:v", "high", "-level", "4.1", "-preset", "veryfast", "-crf", "18",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(output_path),
        ])
        try:
            subprocess.run(
                command, check=True, capture_output=True, text=True,
                timeout=max(180, math.ceil(source_duration * 12)),
            )
        except FileNotFoundError as exc:
            raise RuntimeError("ffmpeg is required to retime Video") from exc
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            detail = (getattr(exc, "stderr", "") or str(exc))[-1600:]
            raise RuntimeError(f"Video retime failed: {detail}") from exc
        output_metadata = _probe(output_path)
        output_duration = float((output_metadata.get("format") or {}).get("duration") or 0)
        return RetimedVideo(
            data=output_path.read_bytes(),
            width=int(stream.get("width") or 0), height=int(stream.get("height") or 0), fps=output_fps,
            source_duration_ms=round(source_duration * 1000), duration_ms=round(output_duration * 1000), has_audio=has_audio,
        )
