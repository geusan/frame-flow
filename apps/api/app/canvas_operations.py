from __future__ import annotations

import hashlib
import io
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from .database import ArtifactRecord
from .domain import ExperimentRunRequest
from .providers_localization import SpeechSegment, SynthesizedSpeech, get_localization_services, get_speech_recognizer
from .reference_analysis import REFERENCE_ANALYSIS_REVISION, analyze_reference_video
from .service import create_artifact
from .storage import get_storage, storage_location


LOCAL_EXECUTOR_REVISION = "local-media.v1"
LOCALIZATION_EXECUTOR_REVISION = "google-localization.v1"
LOCAL_MODELS: dict[str, tuple[str, str]] = {
    "generation.resolve": ("local.policy", "generation-policy.v1"),
    "script.fit_duration": ("local.script-fit", "script-fit.v1"),
    "shot.plan": ("local.shot-plan", "shot-plan.v1"),
    "reference.decompose": ("reference-analysis.pipeline", "reference-analysis.v1"),
    "video.edit": ("local.ffmpeg", "ffmpeg"),
    "video.change_voice": ("local.ffmpeg", "ffmpeg"),
    "video.translate": ("google.localization.pipeline", "chirp_3+gemini-3.1-pro-preview+gemini-2.5-flash-tts"),
    "subtitle.align": ("google.stt.default", "chirp_3"),
    "timeline.compose": ("local.timeline", "timeline.v1"),
    "video.render": ("local.ffmpeg", "ffmpeg"),
    "media.qc": ("local.ffprobe", "ffprobe"),
}


@dataclass(frozen=True)
class CanvasOperationResult:
    output: dict[str, object]
    artifact_type: str
    schema_id: str | None
    provider_request_id: str
    content: bytes
    content_type: str
    filename: str
    input_artifact_ids: list[str]
    metadata: dict[str, Any] = field(default_factory=dict)
    input_artifact_roles: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ArtifactData:
    record: ArtifactRecord
    data: bytes
    content_type: str


def is_local_operation(node_key: str) -> bool:
    return node_key in LOCAL_MODELS


def resolve_local_model(node_key: str) -> tuple[str, str]:
    return LOCAL_MODELS[node_key]


def executor_revision(node_key: str) -> str:
    if node_key == "reference.decompose":
        mode = os.getenv("REFERENCE_ANALYSIS_MODE", "live").strip().lower()
        separator = os.getenv("REFERENCE_AUDIO_SEPARATOR", "demucs").strip().lower()
        return f"{REFERENCE_ANALYSIS_REVISION}:{mode}:{separator}"
    if node_key == "video.translate":
        return LOCALIZATION_EXECUTOR_REVISION
    if node_key == "subtitle.align" and os.getenv("SUBTITLE_ALIGNMENT_MODE", "live").lower() == "live":
        return "google-speech.v1"
    return LOCAL_EXECUTOR_REVISION


def _run(command: list[str], *, timeout: int = 180) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(command, check=True, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise RuntimeError(f"required media tool is not installed: {command[0]}") from exc
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        detail = (getattr(exc, "stderr", "") or str(exc))[-1600:]
        raise RuntimeError(f"media operation failed: {detail}") from exc


def _artifact_ids(inputs: list[dict[str, Any]]) -> list[str]:
    result: list[str] = []
    for item in inputs:
        values = item.get("artifact_ids") or []
        if item.get("artifact_id"):
            values = [item["artifact_id"], *values]
        for value in values:
            artifact_id = str(value)
            if artifact_id and artifact_id not in result:
                result.append(artifact_id)
    return result


def _read_artifacts(db: Session, inputs: list[dict[str, Any]]) -> list[ArtifactData]:
    artifacts: list[ArtifactData] = []
    storage = get_storage()
    for artifact_id in _artifact_ids(inputs):
        record = db.get(ArtifactRecord, artifact_id)
        if not record:
            raise ValueError(f"input artifact does not exist: {artifact_id}")
        bucket, key = storage_location(record.uri, record.metadata_json)
        content_type = str((record.metadata_json.get("storage") or {}).get("content_type") or "application/octet-stream")
        artifacts.append(ArtifactData(record, storage.get_bytes(bucket=bucket, key=key), content_type))
    return artifacts


def _of_type(artifacts: list[ArtifactData], *types: str) -> list[ArtifactData]:
    allowed = set(types)
    return [artifact for artifact in artifacts if artifact.record.type in allowed]


def _require(artifacts: list[ArtifactData], label: str, *types: str) -> ArtifactData:
    matches = _of_type(artifacts, *types)
    if not matches:
        raise ValueError(f"{label} input artifact is required")
    return matches[0]


def _suffix(content_type: str) -> str:
    return {
        "video/mp4": ".mp4",
        "audio/wav": ".wav",
        "audio/mpeg": ".mp3",
        "audio/mp4": ".m4a",
        "text/plain": ".txt",
        "application/json": ".json",
        "application/x-subrip": ".srt",
    }.get(content_type.split(";", 1)[0].lower(), ".bin")


def _write_artifact(directory: Path, artifact: ArtifactData, index: int) -> Path:
    path = directory / f"input-{index}{_suffix(artifact.content_type)}"
    path.write_bytes(artifact.data)
    return path


def _probe(path: Path) -> dict[str, Any]:
    result = _run([
        "ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path),
    ])
    return json.loads(result.stdout)


def _duration_seconds(metadata: dict[str, Any]) -> float:
    duration = float((metadata.get("format") or {}).get("duration") or 0)
    if duration <= 0:
        raise ValueError("input media has no positive duration")
    return duration


def _video_stream(metadata: dict[str, Any]) -> dict[str, Any]:
    stream = next((item for item in metadata.get("streams", []) if item.get("codec_type") == "video"), None)
    if not stream:
        raise ValueError("input artifact does not contain a video stream")
    return stream


def _has_audio(metadata: dict[str, Any]) -> bool:
    return any(item.get("codec_type") == "audio" for item in metadata.get("streams", []))


def _fps(stream: dict[str, Any]) -> float:
    numerator, _, denominator = str(stream.get("avg_frame_rate") or "24/1").partition("/")
    try:
        value = float(numerator) / float(denominator or 1)
    except (TypeError, ValueError, ZeroDivisionError):
        value = 24
    return value if value > 0 else 24


def _target_size(parameters: dict[str, Any], source_stream: dict[str, Any]) -> tuple[int, int]:
    aspect = str(parameters.get("aspect_ratio") or "source")
    resolution = str(parameters.get("resolution") or "source").lower()
    source_width = int(source_stream.get("width") or 360)
    source_height = int(source_stream.get("height") or 640)
    if resolution in {"source", "none", ""}:
        if aspect == "source":
            return source_width, source_height
        long_edge = max(source_width, source_height)
    else:
        named_resolutions = {"2k": 1440, "4k": 2160}
        match = re.search(r"(\d+)", resolution)
        short_edge = named_resolutions.get(resolution, int(match.group(1)) if match else min(source_width, source_height))
        long_edge = round(short_edge * 16 / 9)
        if aspect == "1:1":
            long_edge = short_edge
        if aspect == "16:9":
            return (long_edge // 2 * 2, short_edge // 2 * 2)
        return (short_edge // 2 * 2, long_edge // 2 * 2)
    if aspect == "1:1":
        return long_edge // 2 * 2, long_edge // 2 * 2
    if aspect == "16:9":
        return long_edge // 2 * 2, round(long_edge * 9 / 16) // 2 * 2
    if aspect == "9:16":
        return round(long_edge * 9 / 16) // 2 * 2, long_edge // 2 * 2
    return source_width // 2 * 2, source_height // 2 * 2


def _normalize_video(source: Path, output: Path, *, width: int, height: int, duration: float, metadata: dict[str, Any]) -> None:
    video_filter = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,fps=24,setsar=1,format=yuv420p"
    )
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source)]
    if _has_audio(metadata):
        command.extend([
            "-map", "0:v:0", "-map", "0:a:0", "-vf", video_filter,
            "-af", "aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo",
        ])
    else:
        command.extend([
            "-f", "lavfi", "-t", f"{duration:.3f}", "-i", "anullsrc=r=48000:cl=stereo",
            "-map", "0:v:0", "-map", "1:a:0", "-vf", video_filter,
        ])
    command.extend([
        "-t", f"{duration:.3f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2", "-movflags", "+faststart", str(output),
    ])
    _run(command, timeout=max(180, math.ceil(duration * 12)))


def _join_videos(paths: list[Path], durations: list[float], output: Path, transition: str, target_duration: float) -> None:
    if len(paths) == 1:
        shutil.copyfile(paths[0], output)
        return
    if transition in {"crossfade", "dip_to_black"}:
        fade_duration = min(0.35, min(durations) / 3)
        command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
        for path in paths:
            command.extend(["-i", str(path)])
        filters: list[str] = []
        video_label = "0:v"
        audio_label = "0:a"
        combined_duration = durations[0]
        xfade_transition = "fadeblack" if transition == "dip_to_black" else "fade"
        for index in range(1, len(paths)):
            video_output = f"v{index}"
            audio_output = f"a{index}"
            offset = max(0, combined_duration - fade_duration)
            filters.append(
                f"[{video_label}][{index}:v]xfade=transition={xfade_transition}:duration={fade_duration:.3f}:offset={offset:.3f}[{video_output}]"
            )
            filters.append(f"[{audio_label}][{index}:a]acrossfade=d={fade_duration:.3f}[{audio_output}]")
            video_label = video_output
            audio_label = audio_output
            combined_duration += durations[index] - fade_duration
        command.extend([
            "-filter_complex", ";".join(filters), "-map", f"[{video_label}]", "-map", f"[{audio_label}]",
            "-t", f"{target_duration:.3f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(output),
        ])
        _run(command, timeout=max(180, math.ceil(target_duration * 12)))
        return
    concat_file = output.parent / "concat.txt"
    concat_file.write_text("".join(f"file '{path.as_posix()}'\n" for path in paths))
    _run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0",
        "-i", str(concat_file), "-t", f"{target_duration:.3f}", "-c", "copy", "-movflags", "+faststart", str(output),
    ], timeout=max(180, math.ceil(target_duration * 5)))


def _edit_videos(artifacts: list[ArtifactData], parameters: dict[str, Any]) -> bytes:
    videos = _of_type(artifacts, "Video", "FinalVideo", "ProxyVideo")
    if not videos:
        raise ValueError("at least one Video input artifact is required")
    with tempfile.TemporaryDirectory(prefix="frameflow-edit-") as temp_dir:
        directory = Path(temp_dir)
        source_paths = [_write_artifact(directory, video, index) for index, video in enumerate(videos)]
        metadata = [_probe(path) for path in source_paths]
        width, height = _target_size(parameters, _video_stream(metadata[0]))
        target_duration = float(parameters.get("target_duration_seconds") or sum(_duration_seconds(item) for item in metadata))
        if target_duration <= 0 or target_duration > 600:
            raise ValueError("target duration must be between 0 and 600 seconds")
        remaining = target_duration
        normalized: list[Path] = []
        durations: list[float] = []
        for index, (source, item) in enumerate(zip(source_paths, metadata, strict=True)):
            if remaining <= 0:
                break
            duration = min(_duration_seconds(item), remaining)
            normalized_path = directory / f"normalized-{index}.mp4"
            _normalize_video(source, normalized_path, width=width, height=height, duration=duration, metadata=item)
            normalized.append(normalized_path)
            durations.append(duration)
            remaining -= duration
        transition = str(parameters.get("transition") or "hard_cut")
        if transition not in {"hard_cut", "crossfade", "dip_to_black"}:
            raise ValueError(f"unsupported video transition: {transition}")
        output = directory / "edited.mp4"
        _join_videos(normalized, durations, output, transition, target_duration - max(0, remaining))
        return output.read_bytes()


def _replace_audio(video: ArtifactData, audio: ArtifactData, subtitle: ArtifactData | None = None, *, language: str = "und") -> bytes:
    with tempfile.TemporaryDirectory(prefix="frameflow-audio-replace-") as temp_dir:
        directory = Path(temp_dir)
        video_path = _write_artifact(directory, video, 0)
        audio_path = _write_artifact(directory, audio, 1)
        duration = _duration_seconds(_probe(video_path))
        output = directory / "localized.mp4"
        command = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(video_path), "-i", str(audio_path),
        ]
        if subtitle:
            subtitle_path = _write_artifact(directory, subtitle, 2)
            command.extend(["-i", str(subtitle_path)])
        command.extend([
            "-filter_complex", "[1:a]apad[a]", "-map", "0:v:0", "-map", "[a]",
        ])
        if subtitle:
            command.extend(["-map", "2:0"])
        command.extend([
            "-t", f"{duration:.3f}", "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
        ])
        if subtitle:
            command.extend(["-c:s", "mov_text", "-metadata:s:s:0", f"language={language}"])
        command.extend(["-movflags", "+faststart", str(output)])
        _run(command, timeout=max(180, math.ceil(duration * 6)))
        return output.read_bytes()


def _extract_speech_audio(video: ArtifactData) -> tuple[bytes, int]:
    with tempfile.TemporaryDirectory(prefix="frameflow-speech-extract-") as temp_dir:
        directory = Path(temp_dir)
        video_path = _write_artifact(directory, video, 0)
        metadata = _probe(video_path)
        if not _has_audio(metadata):
            raise ValueError("Translate Video requires a video with an audio stream")
        duration_ms = round(_duration_seconds(metadata) * 1000)
        if duration_ms > 60_000:
            raise ValueError("Translate Video currently supports videos up to 60 seconds")
        output = directory / "speech.wav"
        _run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(video_path),
            "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(output),
        ])
        return output.read_bytes(), duration_ms


def _synthesized_wav(speech: SynthesizedSpeech) -> bytes:
    mime_type = speech.mime_type.lower()
    if mime_type.startswith("audio/wav") or mime_type.startswith("audio/x-wav"):
        return speech.data
    if mime_type.startswith("audio/pcm") or mime_type.startswith("audio/l16"):
        rate_match = re.search(r"rate=(\d+)", mime_type)
        sample_rate = int(rate_match.group(1)) if rate_match else 24_000
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(sample_rate)
            output.writeframes(speech.data)
        return buffer.getvalue()
    with tempfile.TemporaryDirectory(prefix="frameflow-tts-convert-") as temp_dir:
        directory = Path(temp_dir)
        source = directory / f"speech{_suffix(speech.mime_type)}"
        output = directory / "speech.wav"
        source.write_bytes(speech.data)
        _run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
            "-ac", "1", "-ar", "24000", "-c:a", "pcm_s16le", str(output),
        ])
        return output.read_bytes()


def _text_from_artifact(artifact: ArtifactData) -> str:
    text = artifact.data.decode("utf-8", errors="replace").strip()
    if artifact.content_type == "application/json":
        try:
            payload = json.loads(text)
            if isinstance(payload, dict):
                return str(payload.get("text") or payload.get("script") or text)
        except json.JSONDecodeError:
            pass
    return text


def _format_srt_time(seconds: float) -> str:
    milliseconds = max(0, round(seconds * 1000))
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    secs, milliseconds = divmod(milliseconds, 1_000)
    return f"{hours:02}:{minutes:02}:{secs:02},{milliseconds:03}"


def _build_subtitles(script: str, duration: float) -> bytes:
    sentences = [item.strip() for item in re.split(r"(?<=[.!?。！？])\s+|\n+", script) if item.strip()]
    if not sentences:
        raise ValueError("Script input does not contain subtitle text")
    weights = [max(1, len(re.sub(r"\s+", "", sentence))) for sentence in sentences]
    total_weight = sum(weights)
    cursor = 0.0
    cues: list[str] = []
    for index, (sentence, weight) in enumerate(zip(sentences, weights, strict=True), start=1):
        end = duration if index == len(sentences) else cursor + duration * weight / total_weight
        cues.append(f"{index}\n{_format_srt_time(cursor)} --> {_format_srt_time(end)}\n{sentence}\n")
        cursor = end
    return "\n".join(cues).encode("utf-8")


def _segments_to_srt(segments: list[SpeechSegment]) -> bytes:
    cues = [
        f"{index}\n{_format_srt_time(segment.start_ms / 1000)} --> {_format_srt_time(segment.end_ms / 1000)}\n{segment.text}\n"
        for index, segment in enumerate(segments, start=1)
    ]
    return "\n".join(cues).encode("utf-8")


def _caption_style(parameters: dict[str, Any]) -> dict[str, Any]:
    def number(key: str, default: float, minimum: float, maximum: float) -> float:
        try:
            value = float(parameters.get(key, default))
        except (TypeError, ValueError):
            value = default
        return min(maximum, max(minimum, value))

    align = str(parameters.get("caption_align") or "center").lower()
    if align not in {"left", "center", "right"}:
        align = "center"
    return {
        "x": round(number("caption_x", 0.5, 0.0, 1.0), 4),
        "y": round(number("caption_y", 0.82, 0.0, 1.0), 4),
        "align": align,
        "font_size": round(number("caption_font_size", 54, 24, 96)),
        "font_family": "Noto Sans CJK KR",
        "color": "#FFFFFF",
        "outline_color": "#000000",
    }


def _ass_timestamp(value: str) -> str:
    match = re.fullmatch(r"(\d+):(\d{2}):(\d{2})[,.](\d{3})", value.strip())
    if not match:
        raise ValueError(f"invalid SRT timestamp: {value}")
    hours, minutes, seconds, milliseconds = (int(item) for item in match.groups())
    return f"{hours}:{minutes:02}:{seconds:02}.{milliseconds // 10:02}"


def _srt_to_ass(content: bytes, *, width: int, height: int, style: dict[str, Any]) -> str:
    source = content.decode("utf-8-sig", errors="replace").strip()
    blocks = re.split(r"\r?\n\s*\r?\n", source) if source else []
    events: list[str] = []
    alignment = {"left": 4, "center": 5, "right": 6}[str(style.get("align") or "center")]
    x = round(float(style.get("x", 0.5)) * width)
    y = round(float(style.get("y", 0.82)) * height)
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        timing_index = next((index for index, line in enumerate(lines) if "-->" in line), -1)
        if timing_index < 0:
            continue
        start, end = (item.strip().split(" ", 1)[0] for item in lines[timing_index].split("-->", 1))
        text = r"\N".join(re.sub(r"<[^>]+>", "", line).replace("{", "(").replace("}", ")") for line in lines[timing_index + 1:])
        if not text:
            continue
        events.append(
            f"Dialogue: 0,{_ass_timestamp(start)},{_ass_timestamp(end)},Caption,,0,0,0,,"
            f"{{\\an{alignment}\\pos({x},{y})\\q2}}{text}"
        )
    if not events:
        raise ValueError("Subtitle input does not contain valid SRT cues")
    font_size = max(14, round(float(style.get("font_size") or 54) * width / 1080))
    outline = max(2, round(4 * width / 1080))
    font_family = str(style.get("font_family") or "Noto Sans CJK KR").replace(",", " ")
    return "\n".join([
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {width}",
        f"PlayResY: {height}",
        "ScaledBorderAndShadow: yes",
        "WrapStyle: 2",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Caption,{font_family},{font_size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H78000000,-1,0,0,0,100,100,0,0,1,{outline},0,5,24,24,24,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        *events,
        "",
    ])


def _timeline(artifacts: list[ArtifactData], parameters: dict[str, Any]) -> dict[str, Any]:
    video = _require(artifacts, "Video", "Video", "FinalVideo")
    subtitle = next(iter(_of_type(artifacts, "Subtitle")), None)
    with tempfile.TemporaryDirectory(prefix="frameflow-timeline-") as temp_dir:
        path = _write_artifact(Path(temp_dir), video, 0)
        metadata = _probe(path)
    stream = _video_stream(metadata)
    duration_ms = round(_duration_seconds(metadata) * 1000)
    target_seconds = parameters.get("target_duration_seconds")
    if target_seconds:
        duration_ms = min(duration_ms, round(float(target_seconds) * 1000))
    return {
        "version": "timeline.v1",
        "width": int(stream.get("width") or 360),
        "height": int(stream.get("height") or 640),
        "fps": round(_fps(stream), 3),
        "duration_ms": duration_ms,
        "video_tracks": [{"id": "video-main", "clips": [{"artifact_id": video.record.id, "start_ms": 0, "trim_in_ms": 0, "duration_ms": duration_ms}]}],
        "audio_tracks": [{"id": "audio-main", "clips": [{"artifact_id": video.record.id, "start_ms": 0, "trim_in_ms": 0, "duration_ms": duration_ms}]}],
        "caption_tracks": [] if not subtitle else [{
            "id": "captions",
            "style": _caption_style(parameters),
            "clips": [{"artifact_id": subtitle.record.id, "start_ms": 0, "duration_ms": duration_ms}],
        }],
        "effects": [],
    }


def _render_timeline(db: Session, timeline_artifact: ArtifactData) -> bytes:
    try:
        timeline = json.loads(timeline_artifact.data)
        video_id = timeline["video_tracks"][0]["clips"][0]["artifact_id"]
    except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
        raise ValueError("Timeline artifact is invalid") from exc
    synthetic_inputs = [{"artifact_ids": [video_id]}]
    caption_tracks = timeline.get("caption_tracks") or []
    if caption_tracks:
        synthetic_inputs[0]["artifact_ids"].append(caption_tracks[0]["clips"][0]["artifact_id"])
    artifacts = _read_artifacts(db, synthetic_inputs)
    video = _require(artifacts, "Video", "Video", "FinalVideo")
    subtitle = next(iter(_of_type(artifacts, "Subtitle")), None)
    parameters = {
        "resolution": "source",
        "aspect_ratio": "source",
        "target_duration_seconds": float(timeline["duration_ms"]) / 1000,
    }
    rendered = _edit_videos([video], parameters)
    if not subtitle:
        return rendered
    rendered_artifact = ArtifactData(video.record, rendered, "video/mp4")
    caption_style = dict(caption_tracks[0].get("style") or _caption_style({}))
    width = int(timeline.get("width") or 1080)
    height = int(timeline.get("height") or 1920)
    ass_content = _srt_to_ass(subtitle.data, width=width, height=height, style=caption_style)
    # Burn the positioned caption into the image so social players render it consistently.
    with tempfile.TemporaryDirectory(prefix="frameflow-caption-mux-") as temp_dir:
        directory = Path(temp_dir)
        video_path = _write_artifact(directory, rendered_artifact, 0)
        subtitle_path = directory / "captions.ass"
        subtitle_path.write_text(ass_content, encoding="utf-8")
        output = directory / "final.mp4"
        _run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(video_path),
            "-vf", f"ass={subtitle_path}", "-map", "0:v:0", "-map", "0:a:0?",
            "-c:v", "libx264", "-profile:v", "high", "-level", "4.1", "-preset", "veryfast", "-crf", "18",
            "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart", str(output),
        ])
        return output.read_bytes()


def _qc_report(video: ArtifactData, parameters: dict[str, Any]) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="frameflow-qc-") as temp_dir:
        path = _write_artifact(Path(temp_dir), video, 0)
        metadata = _probe(path)
    stream = _video_stream(metadata)
    audio_present = _has_audio(metadata)
    duration_ms = round(_duration_seconds(metadata) * 1000)
    expected_width = parameters.get("target_width")
    expected_height = parameters.get("target_height")
    checks: dict[str, dict[str, Any]] = {
        "playable": {"passed": True, "actual": True},
        "video_codec": {"passed": stream.get("codec_name") == "h264", "actual": stream.get("codec_name"), "expected": "h264"},
        "pixel_format": {"passed": stream.get("pix_fmt") == "yuv420p", "actual": stream.get("pix_fmt"), "expected": "yuv420p"},
        "audio_present": {"passed": audio_present, "actual": audio_present},
        "duration": {"passed": duration_ms > 0, "actual_ms": duration_ms},
    }
    if expected_width and expected_height:
        checks["resolution"] = {
            "passed": int(stream.get("width") or 0) == int(expected_width) and int(stream.get("height") or 0) == int(expected_height),
            "actual": [stream.get("width"), stream.get("height")],
            "expected": [int(expected_width), int(expected_height)],
        }
    return {
        "version": "qc.report.v1",
        "passed": all(check["passed"] for check in checks.values()),
        "checks": checks,
        "media": {"width": stream.get("width"), "height": stream.get("height"), "duration_ms": duration_ms},
        "sha256": hashlib.sha256(video.data).hexdigest(),
    }


def _json_result(title: str, artifact_type: str, schema_id: str, payload: dict[str, Any], digest: str, input_ids: list[str]) -> CanvasOperationResult:
    content = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2).encode()
    return CanvasOperationResult(
        {"kind": "json", "title": title, "text": content.decode()}, artifact_type, schema_id,
        f"local_{digest[:20]}", content, "application/json", f"{artifact_type.lower()}.json", input_ids,
    )


def execute_canvas_operation(db: Session, payload: ExperimentRunRequest, digest: str) -> CanvasOperationResult:
    artifacts = _read_artifacts(db, payload.inputs)
    input_ids = [artifact.record.id for artifact in artifacts]
    node_key = payload.node_key

    if node_key == "generation.resolve":
        source_text = [str(item.get("config_text") or item.get("output_text") or item.get("description") or item.get("label") or "").strip() for item in payload.inputs]
        spec = {
            "version": "generation.spec.v1",
            "brief": next((text for text in source_text if text), payload.prompt),
            "target_duration_seconds": int(payload.parameters.get("target_duration_seconds") or 38),
            "aspect_ratio": payload.parameters.get("aspect_ratio") or "9:16",
            "input_artifact_ids": input_ids,
        }
        return _json_result("Generation specification", "GenerationSpec", "generation.spec.v1", spec, digest, input_ids)

    if node_key == "reference.decompose":
        video = _require(artifacts, "Video", "Video", "FinalVideo", "ProxyVideo", "ReferenceOriginal")
        separate_music = payload.parameters.get("separate_music")
        bundle = analyze_reference_video(
            video.data,
            video.content_type,
            language_code=str(payload.parameters.get("source_language") or "auto"),
            separate_music=True if separate_music is None else bool(separate_music),
            scene_threshold=float(payload.parameters.get("scene_threshold") or 0.28),
        )
        metadata = {
            "access_scope": "reference-analyzer-only",
            "storage_scope": "reference",
            "source_artifact_id": video.record.id,
            "immutable": True,
        }
        source_roles = {video.record.id: "source_video"}
        derived: dict[str, ArtifactRecord] = {}
        if bundle.audio_mix is not None:
            derived["audio_mix"] = create_artifact(
                db,
                "ReferenceAudioMix",
                schema_id="reference.audio.mix.v1",
                input_artifact_ids=[video.record.id],
                input_artifact_roles=source_roles,
                metadata=metadata,
                content=bundle.audio_mix,
                content_type="audio/wav",
                filename="reference-audio.wav",
            )
        transcript_parent = derived.get("audio_mix")
        if bundle.transcript is not None:
            transcript_input = transcript_parent.id if transcript_parent else video.record.id
            derived["transcript"] = create_artifact(
                db,
                "ReferenceTranscript",
                schema_id="transcript.v1",
                input_artifact_ids=[transcript_input],
                input_artifact_roles={transcript_input: "source_audio"},
                metadata=metadata,
                content=bundle.transcript,
                content_type="application/json",
                filename="transcript.json",
            )
        if bundle.subtitles is not None:
            subtitle_parent = derived.get("transcript")
            subtitle_input = subtitle_parent.id if subtitle_parent else video.record.id
            derived["subtitle"] = create_artifact(
                db,
                "ReferenceSubtitle",
                schema_id="subtitle.srt.v1",
                input_artifact_ids=[subtitle_input],
                input_artifact_roles={subtitle_input: "timed_transcript"},
                metadata=metadata,
                content=bundle.subtitles,
                content_type="application/x-subrip",
                filename="transcript.srt",
            )
        for key, artifact_type, content, filename in (
            ("vocals", "ReferenceVocals", bundle.vocals, "vocals.wav"),
            ("accompaniment", "ReferenceAccompaniment", bundle.accompaniment, "accompaniment.wav"),
        ):
            if content is None:
                continue
            stem_parent = derived.get("audio_mix")
            stem_input = stem_parent.id if stem_parent else video.record.id
            derived[key] = create_artifact(
                db,
                artifact_type,
                schema_id="reference.audio.stem.v1",
                input_artifact_ids=[stem_input],
                input_artifact_roles={stem_input: "source_mix"},
                metadata={**metadata, "stem": key, "contains_sound_effects_possible": key == "accompaniment"},
                content=content,
                content_type="audio/wav",
                filename=filename,
            )
        db.flush()
        bundle.manifest["artifacts"] = {key: artifact.id for key, artifact in derived.items()}
        manifest_content = json.dumps(bundle.manifest, ensure_ascii=False, sort_keys=True, indent=2).encode()
        manifest_inputs = [video.record.id, *(artifact.id for artifact in derived.values())]
        manifest_roles = {
            video.record.id: "source_video",
            **{artifact.id: key for key, artifact in derived.items()},
        }
        visual = bundle.manifest["visual"]
        audio = bundle.manifest["audio"]
        title = (
            f"Reference analysis · {len(visual['shots'])} shots · "
            f"{len(visual['actions'])} actions · {len(audio['sound_effects'])} SFX"
        )
        return CanvasOperationResult(
            {"kind": "json", "title": title, "text": manifest_content.decode()},
            "ReferenceAnalysis",
            "reference.decomposition.v1",
            bundle.provider_request_id,
            manifest_content,
            "application/json",
            "reference-analysis.json",
            manifest_inputs,
            metadata={**metadata, "component_artifact_ids": bundle.manifest["artifacts"]},
            input_artifact_roles=manifest_roles,
        )

    if node_key in {"script.fit_duration", "shot.plan"}:
        script_artifact = _require(artifacts, "Script", "Script", "TimedScript")
        script = _text_from_artifact(script_artifact)
        target_seconds = int(payload.parameters.get("target_duration_seconds") or 38)
        if node_key == "script.fit_duration":
            target_chars = max(20, round(target_seconds * 4.7))
            fitted = script if len(script) <= target_chars else script[:target_chars].rsplit(" ", 1)[0].rstrip() + "…"
            return CanvasOperationResult(
                {"kind": "text", "title": f"Timed script · {target_seconds}s", "text": fitted},
                "TimedScript", "script.timed.v1", f"local_{digest[:20]}", fitted.encode(), "text/plain", "script.txt", input_ids,
            )
        shot_duration = 6
        shot_count = max(1, math.ceil(target_seconds / shot_duration))
        shots = [{"index": index + 1, "start_ms": index * shot_duration * 1000, "duration_ms": min(shot_duration, target_seconds - index * shot_duration) * 1000} for index in range(shot_count)]
        return _json_result("Shot plan", "ShotPlan", "shot.plan.v1", {"version": "shot.plan.v1", "shots": shots}, digest, input_ids)

    if node_key == "video.edit":
        content = _edit_videos(artifacts, payload.parameters)
        return CanvasOperationResult(
            {"kind": "video", "title": "Edited video", "mimeType": "video/mp4"}, "Video", "video.edited.v1",
            f"local_{digest[:20]}", content, "video/mp4", "edited.mp4", input_ids,
        )

    if node_key == "video.change_voice":
        video = _require(artifacts, "Video", "Video", "FinalVideo")
        audio = _require(artifacts, "Audio", "Audio")
        content = _replace_audio(video, audio)
        return CanvasOperationResult(
            {"kind": "video", "title": "Video with replaced audio", "mimeType": "video/mp4"}, "Video", "video.localized.v1",
            f"local_{digest[:20]}", content, "video/mp4", "localized.mp4", input_ids,
        )

    if node_key == "video.translate":
        video = _require(artifacts, "Video", "Video", "FinalVideo")
        source_language = str(payload.parameters.get("source_language") or "auto")
        target_language = str(payload.parameters.get("target_language") or "ko-KR")
        voice_name = str(payload.parameters.get("voice_name") or "Kore")
        speech_audio, duration_ms = _extract_speech_audio(video)
        services = get_localization_services()
        transcript = services.recognizer.transcribe(
            speech_audio,
            language_code=source_language,
            duration_ms=duration_ms,
        )
        translation = services.translator.translate(transcript, target_language=target_language)
        speech = services.synthesizer.synthesize(
            translation.text,
            language_code=target_language,
            voice_name=voice_name,
        )
        translated_audio = _synthesized_wav(speech)
        subtitles = _segments_to_srt(translation.segments)
        transcript_payload = {
            "version": "transcript.v1",
            "language_code": transcript.language_code,
            "text": transcript.text,
            "segments": [segment.__dict__ for segment in transcript.segments],
        }
        translation_payload = {
            "version": "translation.v1",
            "source_language": transcript.language_code,
            "target_language": target_language,
            "text": translation.text,
            "segments": [segment.__dict__ for segment in translation.segments],
        }
        transcript_content = json.dumps(transcript_payload, ensure_ascii=False, indent=2).encode()
        translation_content = json.dumps(translation_payload, ensure_ascii=False, indent=2).encode()
        common_metadata = {"experiment_node_id": payload.node_id, "immutable": True}
        transcript_artifact = create_artifact(
            db, "Transcript", schema_id="transcript.v1", content=transcript_content,
            content_type="application/json", filename="transcript.json", metadata=common_metadata,
        )
        translation_artifact = create_artifact(
            db, "TranslatedTranscript", schema_id="translation.v1", content=translation_content,
            content_type="application/json", filename="translation.json",
            metadata={**common_metadata, "provider_request_id": translation.provider_request_id},
        )
        audio_artifact = create_artifact(
            db, "Audio", content=translated_audio, content_type="audio/wav", filename="translated.wav",
            metadata={**common_metadata, "provider_request_id": speech.provider_request_id, "voice_name": voice_name},
        )
        subtitle_artifact = create_artifact(
            db, "Subtitle", schema_id="subtitle.srt.v1", content=subtitles,
            content_type="application/x-subrip", filename="translated.srt",
            metadata={**common_metadata, "language_code": target_language},
        )
        db.flush()
        translated_audio_data = ArtifactData(audio_artifact, translated_audio, "audio/wav")
        translated_subtitle_data = ArtifactData(subtitle_artifact, subtitles, "application/x-subrip")
        content = _replace_audio(video, translated_audio_data, translated_subtitle_data, language=target_language)
        derived_ids = [transcript_artifact.id, translation_artifact.id, audio_artifact.id, subtitle_artifact.id]
        return CanvasOperationResult(
            {
                "kind": "video",
                "title": f"Translated video · {target_language}",
                "mimeType": "video/mp4",
                "sourceLanguage": transcript.language_code,
                "targetLanguage": target_language,
                "transcriptArtifactId": transcript_artifact.id,
                "translationArtifactId": translation_artifact.id,
                "audioArtifactId": audio_artifact.id,
                "subtitleArtifactId": subtitle_artifact.id,
                "ttsProviderRequestId": speech.provider_request_id,
            },
            "Video", "video.translation.v1", translation.provider_request_id,
            content, "video/mp4", "translated.mp4", [*input_ids, *derived_ids],
        )

    if node_key == "subtitle.align":
        audio = _require(artifacts, "Audio", "Audio")
        with tempfile.TemporaryDirectory(prefix="frameflow-subtitle-") as temp_dir:
            audio_path = _write_artifact(Path(temp_dir), audio, 0)
            duration = _duration_seconds(_probe(audio_path))
        alignment_mode = os.getenv("SUBTITLE_ALIGNMENT_MODE", "live").strip().lower()
        if alignment_mode == "live":
            transcript = get_speech_recognizer().transcribe(
                audio.data,
                language_code=str(payload.parameters.get("source_language") or payload.parameters.get("language") or "auto"),
                duration_ms=round(duration * 1000),
            )
            content = _segments_to_srt(transcript.segments)
            title = f"Speech subtitles · {transcript.language_code}"
        elif alignment_mode == "heuristic":
            if os.getenv("APP_ENV") != "test":
                raise ValueError("SUBTITLE_ALIGNMENT_MODE=heuristic is only allowed when APP_ENV=test")
            script_artifact = _require(artifacts, "Script", "Script", "TimedScript")
            content = _build_subtitles(_text_from_artifact(script_artifact), duration)
            title = "Timed subtitles"
        else:
            raise ValueError("SUBTITLE_ALIGNMENT_MODE must be live or heuristic")
        return CanvasOperationResult(
            {"kind": "text", "title": title, "text": content.decode()}, "Subtitle", "subtitle.srt.v1",
            f"local_{digest[:20]}", content, "application/x-subrip", "subtitles.srt", input_ids,
        )

    if node_key == "timeline.compose":
        timeline = _timeline(artifacts, payload.parameters)
        return _json_result("Timeline", "Timeline", "timeline.v1", timeline, digest, input_ids)

    if node_key == "video.render":
        timeline = _require(artifacts, "Timeline", "Timeline")
        content = _render_timeline(db, timeline)
        return CanvasOperationResult(
            {"kind": "video", "title": "Rendered final MP4", "mimeType": "video/mp4"}, "FinalVideo", None,
            f"local_{digest[:20]}", content, "video/mp4", "final.mp4", input_ids,
        )

    if node_key == "media.qc":
        video = _require(artifacts, "Video", "Video", "FinalVideo")
        report = _qc_report(video, payload.parameters)
        title = "QC passed" if report["passed"] else "QC failed"
        return _json_result(title, "QCReport", "qc.report.v1", report, digest, input_ids)

    raise ValueError(f"unsupported local Canvas operation: {node_key}")
