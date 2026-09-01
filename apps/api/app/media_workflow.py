from __future__ import annotations

import json
import math
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


AUDIO_EXTRACT_REVISION = "audio-extract.v1"
AUDIO_EXTRACT_SCHEMA = "audio.extracted.v1"
VIDEO_SPLIT_REVISION = "video-split.v1"
VIDEO_CLIP_LIST_SCHEMA = "video.clip_list.v1"
VIDEO_CLIP_SCHEMA = "video.clip.v1"
VIDEO_CLIP_SELECT_REVISION = "video-clip-select.v1"


@dataclass(frozen=True)
class ExtractedAudio:
    data: bytes
    content_type: str
    filename: str
    codec: str
    duration_ms: int
    sample_rate: int
    channels: int


@dataclass(frozen=True)
class SplitVideoClip:
    data: bytes
    index: int
    start_ms: int
    duration_ms: int
    width: int
    height: int
    fps: int


@dataclass(frozen=True)
class SplitVideo:
    clips: tuple[SplitVideoClip, ...]
    source_duration_ms: int


def _run(command: list[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(f"{command[0]} is required for local media Nodes") from exc
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        detail = (getattr(exc, "stderr", "") or str(exc))[-1600:]
        raise RuntimeError(f"Local media command failed: {detail}") from exc


def _probe(path: Path) -> dict[str, Any]:
    result = _run(
        ["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
        timeout=90,
    )
    return json.loads(result.stdout)


def _duration_seconds(metadata: dict[str, Any], stream: dict[str, Any] | None = None) -> float:
    duration = float((stream or {}).get("duration") or (metadata.get("format") or {}).get("duration") or 0)
    if duration <= 0:
        raise ValueError("input media duration must be positive")
    return duration


def _fps(stream: dict[str, Any]) -> float:
    numerator, _, denominator = str(stream.get("avg_frame_rate") or stream.get("r_frame_rate") or "24/1").partition("/")
    try:
        value = float(numerator) / float(denominator or 1)
    except (TypeError, ValueError, ZeroDivisionError):
        value = 24
    return value if value > 0 else 24


def _source_suffix(content_type: str) -> str:
    normalized = content_type.split(";", 1)[0].strip().lower()
    return {
        "video/mp4": ".mp4",
        "video/quicktime": ".mov",
        "video/webm": ".webm",
    }.get(normalized, ".video")


def _audio_output(codec: str) -> tuple[str, str]:
    if codec in {"aac", "alac"}:
        return "extracted.m4a", "audio/mp4"
    if codec == "mp3":
        return "extracted.mp3", "audio/mpeg"
    if codec in {"opus", "vorbis"}:
        return "extracted.ogg", "audio/ogg"
    if codec == "flac":
        return "extracted.flac", "audio/flac"
    if codec.startswith("pcm_"):
        return "extracted.wav", "audio/wav"
    return "extracted.mka", "audio/x-matroska"


def extract_audio_stream(video_data: bytes, content_type: str) -> ExtractedAudio:
    """Extract the first audio stream without transcoding its encoded packets."""
    with tempfile.TemporaryDirectory(prefix="frameflow-audio-extract-") as temp_dir:
        directory = Path(temp_dir)
        source = directory / f"source{_source_suffix(content_type)}"
        source.write_bytes(video_data)
        metadata = _probe(source)
        audio_stream = next((item for item in metadata.get("streams", []) if item.get("codec_type") == "audio"), None)
        if not audio_stream:
            raise ValueError("Audio Extract requires a Video with an audio stream")
        codec = str(audio_stream.get("codec_name") or "unknown").lower()
        filename, output_content_type = _audio_output(codec)
        output = directory / filename
        command = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
            "-map", "0:a:0", "-vn", "-c:a", "copy",
        ]
        if output.suffix == ".m4a":
            command.extend(["-movflags", "+faststart"])
        command.append(str(output))
        _run(command, timeout=max(180, math.ceil(_duration_seconds(metadata, audio_stream) * 4)))
        output_metadata = _probe(output)
        output_stream = next(item for item in output_metadata.get("streams", []) if item.get("codec_type") == "audio")
        return ExtractedAudio(
            data=output.read_bytes(),
            content_type=output_content_type,
            filename=filename,
            codec=str(output_stream.get("codec_name") or codec),
            duration_ms=round(_duration_seconds(output_metadata, output_stream) * 1000),
            sample_rate=int(output_stream.get("sample_rate") or 0),
            channels=int(output_stream.get("channels") or 0),
        )


def split_video(
    video_data: bytes,
    content_type: str,
    *,
    segment_duration_seconds: float,
    remainder_policy: str,
    output_fps: int,
    max_segments: int,
) -> SplitVideo:
    with tempfile.TemporaryDirectory(prefix="frameflow-video-split-") as temp_dir:
        directory = Path(temp_dir)
        source = directory / f"source{_source_suffix(content_type)}"
        source.write_bytes(video_data)
        metadata = _probe(source)
        video_stream = next((item for item in metadata.get("streams", []) if item.get("codec_type") == "video"), None)
        if not video_stream:
            raise ValueError("Video Split requires a video stream")
        source_duration = _duration_seconds(metadata, video_stream)
        if segment_duration_seconds <= 0:
            raise ValueError("segment duration must be positive")
        if remainder_policy not in {"keep", "drop"}:
            raise ValueError("remainder policy must be keep or drop")
        ratio = source_duration / segment_duration_seconds
        clip_count = math.floor(ratio + 1e-6) if remainder_policy == "drop" else math.ceil(ratio - 1e-6)
        if clip_count < 1:
            raise ValueError("Video Split produced no clips; use keep for a short remainder")
        if clip_count > max_segments:
            raise ValueError(f"Video Split requires {clip_count} clips, exceeding max_segments={max_segments}")

        clips: list[SplitVideoClip] = []
        for index in range(clip_count):
            start = index * segment_duration_seconds
            requested_duration = min(segment_duration_seconds, source_duration - start)
            if requested_duration <= 0:
                break
            output = directory / f"clip-{index + 1:02d}.mp4"
            _run(
                [
                    "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    "-ss", f"{start:.8f}", "-i", str(source), "-t", f"{requested_duration:.8f}",
                    "-map", "0:v:0", "-an", "-vf", f"fps={output_fps},setpts=PTS-STARTPTS,format=yuv420p",
                    "-c:v", "libx264", "-profile:v", "high", "-preset", "veryfast", "-crf", "18",
                    "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(output),
                ],
                timeout=max(180, math.ceil(requested_duration * 12)),
            )
            output_metadata = _probe(output)
            output_stream = next(item for item in output_metadata.get("streams", []) if item.get("codec_type") == "video")
            clips.append(SplitVideoClip(
                data=output.read_bytes(),
                index=index,
                start_ms=round(start * 1000),
                duration_ms=round(_duration_seconds(output_metadata, output_stream) * 1000),
                width=int(output_stream.get("width") or video_stream.get("width") or 0),
                height=int(output_stream.get("height") or video_stream.get("height") or 0),
                fps=round(_fps(output_stream)),
            ))
        return SplitVideo(tuple(clips), round(source_duration * 1000))
