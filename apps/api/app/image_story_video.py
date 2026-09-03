from __future__ import annotations

import json
import hashlib
import math
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Sequence


IMAGE_STORY_VIDEO_REVISION = "image-story-video.v1"
IMAGE_STORY_VIDEO_SCHEMA = "video.image_story.v1"
MEDIA_STORY_VIDEO_REVISION = "media-story-video.v1"
MEDIA_STORY_VIDEO_SCHEMA = "video.media_story.v1"
MAX_STORY_IMAGES = 32


@dataclass(frozen=True)
class SubtitleCue:
    start_ms: int
    end_ms: int
    text: str


@dataclass(frozen=True)
class StoryMedia:
    data: bytes
    content_type: str
    kind: str = "image"


@dataclass(frozen=True)
class RenderedImageStory:
    data: bytes
    width: int
    height: int
    fps: int
    duration_ms: int
    scene_count: int
    cue_count: int
    has_audio: bool
    motion_plan: tuple[dict[str, Any], ...] = ()
    renderer_environment: dict[str, Any] = field(default_factory=dict)


@lru_cache(maxsize=32)
def renderer_environment(font_family: str) -> dict[str, Any]:
    ffmpeg = _run(["ffmpeg", "-version"], timeout=30).stdout.splitlines()
    try:
        font_result = subprocess.run(
            ["fc-match", "-f", "%{file}\n%{family}\n", font_family],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("fontconfig is required for reproducible caption rendering") from exc
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        detail = (getattr(exc, "stderr", "") or str(exc))[-1600:]
        raise RuntimeError(f"Caption font resolution failed: {detail}") from exc
    font_lines = [line.strip() for line in font_result.stdout.splitlines() if line.strip()]
    font_path = Path(font_lines[0]) if font_lines else None
    if not font_path or not font_path.is_file():
        raise RuntimeError(f"Caption font could not be resolved: {font_family}")
    payload = {
        "ffmpeg_version": ffmpeg[0] if ffmpeg else "unknown",
        "ffmpeg_libraries": ffmpeg[3:11],
        "font_family_requested": font_family,
        "font_family_resolved": font_lines[1] if len(font_lines) > 1 else font_family,
        "font_file_sha256": hashlib.sha256(font_path.read_bytes()).hexdigest(),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return {**payload, "fingerprint": f"sha256:{hashlib.sha256(canonical.encode()).hexdigest()}"}


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
        raise RuntimeError(f"{command[0]} is required for Image Story Video") from exc
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        detail = (getattr(exc, "stderr", "") or str(exc))[-1600:]
        raise RuntimeError(f"Image Story Video media command failed: {detail}") from exc


def _probe(path: Path) -> dict[str, Any]:
    result = _run(
        ["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
        timeout=90,
    )
    return json.loads(result.stdout)


def _timestamp_ms(value: str) -> int:
    match = re.fullmatch(r"(\d+):(\d{2}):(\d{2})[,.](\d{3})", value.strip())
    if not match:
        raise ValueError(f"invalid SRT timestamp: {value}")
    hours, minutes, seconds, milliseconds = (int(item) for item in match.groups())
    if minutes >= 60 or seconds >= 60:
        raise ValueError(f"invalid SRT timestamp: {value}")
    return ((hours * 60 + minutes) * 60 + seconds) * 1000 + milliseconds


def parse_srt_cues(content: bytes) -> tuple[SubtitleCue, ...]:
    source = content.decode("utf-8-sig", errors="replace").strip()
    blocks = re.split(r"\r?\n\s*\r?\n", source) if source else []
    cues: list[SubtitleCue] = []
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        timing_index = next((index for index, line in enumerate(lines) if "-->" in line), -1)
        if timing_index < 0:
            continue
        start_raw, end_raw = (item.strip().split(" ", 1)[0] for item in lines[timing_index].split("-->", 1))
        start_ms, end_ms = _timestamp_ms(start_raw), _timestamp_ms(end_raw)
        text = "\n".join(re.sub(r"<[^>]+>", "", line) for line in lines[timing_index + 1:]).strip()
        if not text:
            continue
        if end_ms <= start_ms:
            raise ValueError("Subtitle cues must have a positive duration")
        cues.append(SubtitleCue(start_ms=start_ms, end_ms=end_ms, text=text))
    if not cues:
        raise ValueError("Timed Subtitle input does not contain valid SRT cues")
    cues.sort(key=lambda cue: (cue.start_ms, cue.end_ms))
    return tuple(cues)


def output_dimensions(aspect_ratio: str, resolution: str) -> tuple[int, int]:
    short_edge = {"720p": 720, "1080p": 1080}.get(resolution)
    if short_edge is None:
        raise ValueError("Image Story Video resolution must be 720p or 1080p")
    dimensions = {
        "9:16": (short_edge, short_edge * 16 // 9),
        "16:9": (short_edge * 16 // 9, short_edge),
        "1:1": (short_edge, short_edge),
    }
    if aspect_ratio not in dimensions:
        raise ValueError("Image Story Video aspect ratio must be 9:16, 16:9 or 1:1")
    return dimensions[aspect_ratio]


def _scene_frames(
    cues: Sequence[SubtitleCue],
    *,
    image_count: int,
    total_duration_ms: int,
    fps: int,
    scene_timing: str,
) -> tuple[int, ...]:
    total_frames = max(1, math.ceil(total_duration_ms * fps / 1000))
    if scene_timing == "subtitle_cues":
        if image_count != len(cues):
            raise ValueError(
                "subtitle_cues timing requires exactly one Story Image per Subtitle cue "
                f"({image_count} images, {len(cues)} cues)"
            )
        boundaries = [0, *(round(cue.start_ms * fps / 1000) for cue in cues[1:]), total_frames]
    elif scene_timing == "equal":
        boundaries = [round(index * total_frames / image_count) for index in range(image_count + 1)]
    else:
        raise ValueError("Image Story Video scene timing must be subtitle_cues or equal")
    frames = tuple(boundaries[index + 1] - boundaries[index] for index in range(image_count))
    if any(value < 1 for value in frames):
        raise ValueError("Image Story Video contains a scene shorter than one output frame")
    return frames


def _ass_timestamp(milliseconds: int) -> str:
    centiseconds = max(0, milliseconds // 10)
    hours, remainder = divmod(centiseconds, 360_000)
    minutes, remainder = divmod(remainder, 6_000)
    seconds, value = divmod(remainder, 100)
    return f"{hours}:{minutes:02}:{seconds:02}.{value:02}"


def _ass_color(value: str) -> str:
    match = re.fullmatch(r"#([0-9A-Fa-f]{2})([0-9A-Fa-f]{2})([0-9A-Fa-f]{2})", value)
    if not match:
        raise ValueError(f"invalid RGB color: {value}")
    red, green, blue = match.groups()
    return f"&H00{blue}{green}{red}".upper()


def _ass_text(value: str) -> str:
    return value.replace("\\", "／").replace("{", "(").replace("}", ")").replace("\n", r"\N")


def _wrap_caption_text(value: str, max_units: float) -> str:
    def units(text: str) -> float:
        return sum(1.0 if ord(character) > 127 else 0.55 for character in text)

    lines: list[str] = []
    for paragraph in value.splitlines() or [value]:
        current = ""
        for word in paragraph.split():
            candidate = f"{current} {word}".strip()
            if current and units(candidate) > max_units:
                lines.append(current)
                current = word
            else:
                current = candidate
            while units(current) > max_units and len(current) > 1:
                split_at = max(1, round(len(current) * max_units / units(current)))
                lines.append(current[:split_at])
                current = current[split_at:]
        if current:
            lines.append(current)
    return "\n".join(lines)


def _subtitle_ass(
    cues: Sequence[SubtitleCue],
    *,
    width: int,
    height: int,
    caption_top: int,
    caption_left: int = 0,
    caption_right: int | None = None,
    caption_bottom: int | None = None,
    font_family: str,
    font_size: int,
    color: str,
    outline_color: str,
    align: str,
) -> str:
    alignment = {"left": 4, "center": 5, "right": 6}.get(align)
    if alignment is None:
        raise ValueError("Image Story Video caption alignment must be left, center or right")
    caption_right = width if caption_right is None else caption_right
    caption_bottom = height if caption_bottom is None else caption_bottom
    horizontal_margin = max(12, round((caption_right - caption_left) * 0.07))
    x = {
        "left": caption_left + horizontal_margin,
        "center": caption_left + (caption_right - caption_left) // 2,
        "right": caption_right - horizontal_margin,
    }[align]
    y = caption_top + (caption_bottom - caption_top) // 2
    scale_edge = min(width, height)
    scaled_font_size = max(12, round(font_size * scale_edge / 1080))
    outline = max(1, round(3 * scale_edge / 1080))
    safe_font = re.sub(r"[,\r\n]", " ", font_family).strip()
    if not safe_font:
        raise ValueError("Image Story Video caption font cannot be empty")
    max_line_units = max(
        8.0,
        (caption_right - caption_left - horizontal_margin * 2) / max(1, scaled_font_size * 0.82),
    )
    events = [
        "Dialogue: 0,"
        f"{_ass_timestamp(cue.start_ms)},{_ass_timestamp(cue.end_ms)},Caption,,0,0,0,,"
        f"{{\\an{alignment}\\pos({x},{y})"
        f"\\clip({caption_left},{caption_top},{caption_right},{caption_bottom})\\q1}}"
        f"{_ass_text(_wrap_caption_text(cue.text, max_line_units))}"
        for cue in cues
    ]
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
        f"Style: Caption,{safe_font},{scaled_font_size},{_ass_color(color)},{_ass_color(color)},{_ass_color(outline_color)},&H00000000,-1,0,0,0,100,100,0,0,1,{outline},0,5,{horizontal_margin},{horizontal_margin},0,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        *events,
        "",
    ])


def _motion_name(preset: str, index: int) -> str:
    if preset == "alternate":
        return ("zoom_in", "pan_right", "zoom_out", "pan_left")[index % 4]
    if preset not in {"zoom_in", "zoom_out", "pan_left", "pan_right", "pan_up", "pan_down", "custom", "still"}:
        raise ValueError("Image Story Video motion preset is invalid")
    return preset


def _resolved_motion(
    motion: str,
    amount: float,
    *,
    motion_start_scale: float,
    motion_end_scale: float,
    motion_start_x: float,
    motion_start_y: float,
    motion_end_x: float,
    motion_end_y: float,
) -> dict[str, float | str]:
    zoom_max = 1 + amount
    presets: dict[str, tuple[float, float, float, float, float, float]] = {
        "zoom_in": (1, zoom_max, 0.5, 0.5, 0.5, 0.5),
        "zoom_out": (zoom_max, 1, 0.5, 0.5, 0.5, 0.5),
        "pan_left": (zoom_max, zoom_max, 1, 0.5, 0, 0.5),
        "pan_right": (zoom_max, zoom_max, 0, 0.5, 1, 0.5),
        "pan_up": (zoom_max, zoom_max, 0.5, 1, 0.5, 0),
        "pan_down": (zoom_max, zoom_max, 0.5, 0, 0.5, 1),
        "still": (1, 1, 0.5, 0.5, 0.5, 0.5),
        "custom": (
            motion_start_scale,
            motion_end_scale,
            motion_start_x,
            motion_start_y,
            motion_end_x,
            motion_end_y,
        ),
    }
    if motion not in presets:
        raise ValueError(f"Media Story motion is invalid: {motion}")
    start_scale, end_scale, start_x, start_y, end_x, end_y = presets[motion]
    return {
        "motion": motion,
        "start_scale": start_scale,
        "end_scale": end_scale,
        "start_x": start_x,
        "start_y": start_y,
        "end_x": end_x,
        "end_y": end_y,
    }


def _motion_filter(
    *,
    motion: str,
    amount: float,
    frames: int,
    width: int,
    height: int,
    fps: int,
    media_fit: str = "cover",
    crop_focus_x: float = 0.5,
    crop_focus_y: float = 0.5,
    motion_start_scale: float = 1.0,
    motion_end_scale: float = 1.12,
    motion_start_x: float = 0.5,
    motion_start_y: float = 0.5,
    motion_end_x: float = 0.5,
    motion_end_y: float = 0.5,
    background_color: str = "#000000",
    still_image: bool = True,
) -> str:
    progress = f"on/{max(1, frames - 1)}"
    resolved = _resolved_motion(
        motion,
        amount,
        motion_start_scale=motion_start_scale,
        motion_end_scale=motion_end_scale,
        motion_start_x=motion_start_x,
        motion_start_y=motion_start_y,
        motion_end_x=motion_end_x,
        motion_end_y=motion_end_y,
    )
    start_scale = float(resolved["start_scale"])
    end_scale = float(resolved["end_scale"])
    start_x = float(resolved["start_x"])
    start_y = float(resolved["start_y"])
    end_x = float(resolved["end_x"])
    end_y = float(resolved["end_y"])
    zoom = f"{start_scale:.8f}+({end_scale - start_scale:.8f})*{progress}"
    focus_x = f"{start_x:.8f}+({end_x - start_x:.8f})*{progress}"
    focus_y = f"{start_y:.8f}+({end_y - start_y:.8f})*{progress}"
    x = f"(iw-iw/zoom)*({focus_x})"
    y = f"(ih-ih/zoom)*({focus_y})"
    zoom_max = max(start_scale, end_scale)
    pre_width = math.ceil(width * zoom_max / 2) * 2
    pre_height = math.ceil(height * zoom_max / 2) * 2
    if media_fit == "cover":
        fit_filter = (
            f"scale={pre_width}:{pre_height}:force_original_aspect_ratio=increase:flags=lanczos,"
            f"crop={pre_width}:{pre_height}:"
            f"x='(iw-ow)*{crop_focus_x:.8f}':y='(ih-oh)*{crop_focus_y:.8f}'"
        )
    elif media_fit == "contain":
        background = background_color.removeprefix("#")
        fit_filter = (
            f"scale={pre_width}:{pre_height}:force_original_aspect_ratio=decrease:flags=lanczos,"
            f"pad={pre_width}:{pre_height}:(ow-iw)/2:(oh-ih)/2:color=0x{background}"
        )
    else:
        raise ValueError("Media Story fit must be cover or contain")
    return (
        f"{fit_filter},"
        f"zoompan=z='{zoom}':x='{x}':y='{y}':d={frames if still_image else 1}:s={width}x{height}:fps={fps},"
        "setsar=1,format=yuv420p"
    )


def _suffix(content_type: str, *, media_kind: str) -> str:
    normalized = content_type.split(";", 1)[0].strip().lower()
    mapping = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/webp": ".webp",
        "image/gif": ".gif",
        "video/mp4": ".mp4",
        "video/quicktime": ".mov",
        "video/webm": ".webm",
        "audio/wav": ".wav",
        "audio/x-wav": ".wav",
        "audio/mpeg": ".mp3",
        "audio/mp4": ".m4a",
        "audio/aac": ".aac",
        "audio/ogg": ".ogg",
        "audio/flac": ".flac",
    }
    suffix = mapping.get(normalized)
    if suffix is None:
        raise ValueError(f"unsupported {media_kind} content type: {content_type}")
    return suffix


def _media_duration_ms(path: Path) -> int:
    metadata = _probe(path)
    duration = float((metadata.get("format") or {}).get("duration") or 0)
    if duration <= 0:
        raise ValueError("Narration Audio duration must be positive")
    return round(duration * 1000)


def render_image_story(
    images: Sequence[StoryMedia],
    subtitle_content: bytes,
    *,
    audio: StoryMedia | None,
    aspect_ratio: str,
    resolution: str,
    fps: int,
    scene_timing: str,
    motion_preset: str,
    motion_amount: float,
    image_region_height_ratio: float,
    image_margin_ratio: float,
    background_color: str,
    caption_font_family: str,
    caption_font_size: int,
    caption_color: str,
    caption_outline_color: str,
    caption_align: str,
    output_size_override: tuple[int, int] | None = None,
    frame_x: float | None = None,
    frame_y: float | None = None,
    frame_width: float | None = None,
    frame_height: float | None = None,
    media_fit: str = "cover",
    crop_focus_x: float = 0.5,
    crop_focus_y: float = 0.5,
    motion_start_scale: float = 1.0,
    motion_end_scale: float = 1.12,
    motion_start_x: float = 0.5,
    motion_start_y: float = 0.5,
    motion_end_x: float = 0.5,
    motion_end_y: float = 0.5,
    caption_frame_x: float | None = None,
    caption_frame_y: float | None = None,
    caption_frame_width: float | None = None,
    caption_frame_height: float | None = None,
) -> RenderedImageStory:
    if not images:
        raise ValueError("Image Story Video requires at least one Story Image")
    if len(images) > MAX_STORY_IMAGES:
        raise ValueError(f"Image Story Video supports at most {MAX_STORY_IMAGES} Story Images")
    cues = parse_srt_cues(subtitle_content)
    width, height = output_size_override or output_dimensions(aspect_ratio, resolution)
    if width < 64 or height < 64 or width % 2 or height % 2:
        raise ValueError("Image Story Video output dimensions must be even and at least 64 pixels")
    if fps not in {24, 30}:
        raise ValueError("Image Story Video FPS must be 24 or 30")
    if not 0 <= motion_amount <= 0.3:
        raise ValueError("Image Story Video motion amount must be between 0 and 0.3")
    if not 0.3 <= image_region_height_ratio <= 0.78:
        raise ValueError("Image Story Video image region height ratio must be between 0.3 and 0.78")
    if not 0 <= image_margin_ratio <= 0.15:
        raise ValueError("Image Story Video image margin ratio must be between 0 and 0.15")
    for key, value in {
        "crop_focus_x": crop_focus_x,
        "crop_focus_y": crop_focus_y,
        "motion_start_x": motion_start_x,
        "motion_start_y": motion_start_y,
        "motion_end_x": motion_end_x,
        "motion_end_y": motion_end_y,
    }.items():
        if not 0 <= value <= 1:
            raise ValueError(f"Media Story {key} must be between 0 and 1")
    if not 1 <= motion_start_scale <= 2 or not 1 <= motion_end_scale <= 2:
        raise ValueError("Media Story motion scale must be between 1 and 2")
    environment = renderer_environment(caption_font_family)

    with tempfile.TemporaryDirectory(prefix="frameflow-image-story-") as temp_dir:
        directory = Path(temp_dir)
        audio_path: Path | None = None
        total_duration_ms = max(cue.end_ms for cue in cues)
        if audio is not None:
            audio_path = directory / f"narration{_suffix(audio.content_type, media_kind='Audio')}"
            audio_path.write_bytes(audio.data)
            total_duration_ms = max(total_duration_ms, _media_duration_ms(audio_path))
        scene_frames = _scene_frames(
            cues,
            image_count=len(images),
            total_duration_ms=total_duration_ms,
            fps=fps,
            scene_timing=scene_timing,
        )
        total_frames = sum(scene_frames)
        image_margin = round(width * image_margin_ratio / 2) * 2
        if frame_x is None:
            image_left = image_margin
            image_top = image_margin
            image_width = width - image_margin * 2
            image_height = round(height * image_region_height_ratio / 2) * 2
        else:
            if None in {frame_y, frame_width, frame_height}:
                raise ValueError("Media Story frame requires x, y, width and height")
            image_left = round(width * frame_x / 2) * 2
            image_top = round(height * float(frame_y) / 2) * 2
            image_width = round(width * float(frame_width) / 2) * 2
            image_height = round(height * float(frame_height) / 2) * 2
        caption_top = image_top + image_height
        if caption_frame_x is None:
            caption_left = 0
            caption_right = width
            caption_bottom = height
        else:
            if None in {caption_frame_y, caption_frame_width, caption_frame_height}:
                raise ValueError("Media Story caption frame requires x, y, width and height")
            caption_left = round(width * caption_frame_x / 2) * 2
            caption_top = round(height * float(caption_frame_y) / 2) * 2
            caption_right = caption_left + round(width * float(caption_frame_width) / 2) * 2
            caption_bottom = caption_top + round(height * float(caption_frame_height) / 2) * 2
        if min(image_width, image_height, caption_right - caption_left, caption_bottom - caption_top) < 32:
            raise ValueError("Image Story Video image region leaves no usable caption panel")
        if image_left < 0 or image_top < 0 or image_left + image_width > width or image_top + image_height > height:
            raise ValueError("Media Story media frame must stay inside the output Canvas")
        if caption_left < 0 or caption_top < 0 or caption_right > width or caption_bottom > height:
            raise ValueError("Media Story caption frame must stay inside the output Canvas")
        overlaps = not (
            image_left + image_width <= caption_left
            or caption_right <= image_left
            or image_top + image_height <= caption_top
            or caption_bottom <= image_top
        )
        if frame_x is not None and overlaps:
            raise ValueError("Media Story media and caption frames must not overlap")

        scene_paths: list[Path] = []
        motion_plan: list[dict[str, Any]] = []
        for index, (image, frames) in enumerate(zip(images, scene_frames, strict=True)):
            media_kind = image.kind.strip().lower()
            if media_kind not in {"image", "video"}:
                raise ValueError(f"Media Story source kind is unsupported: {image.kind}")
            image_path = directory / f"media-{index:02d}{_suffix(image.content_type, media_kind=media_kind.title())}"
            image_path.write_bytes(image.data)
            scene_path = directory / f"scene-{index:02d}.mp4"
            motion = _motion_name(motion_preset, index)
            resolved_motion = _resolved_motion(
                motion,
                motion_amount,
                motion_start_scale=motion_start_scale,
                motion_end_scale=motion_end_scale,
                motion_start_x=motion_start_x,
                motion_start_y=motion_start_y,
                motion_end_x=motion_end_x,
                motion_end_y=motion_end_y,
            )
            motion_plan.append({
                "scene_index": index,
                "source_kind": media_kind,
                "frame_count": frames,
                "frame": {"x": image_left, "y": image_top, "width": image_width, "height": image_height},
                "media_fit": media_fit,
                "crop_focus": {"x": crop_focus_x, "y": crop_focus_y},
                **resolved_motion,
            })
            filter_graph = _motion_filter(
                motion=motion,
                amount=motion_amount,
                frames=frames,
                width=image_width,
                height=image_height,
                fps=fps,
                media_fit=media_fit,
                crop_focus_x=crop_focus_x,
                crop_focus_y=crop_focus_y,
                motion_start_scale=motion_start_scale,
                motion_end_scale=motion_end_scale,
                motion_start_x=motion_start_x,
                motion_start_y=motion_start_y,
                motion_end_x=motion_end_x,
                motion_end_y=motion_end_y,
                background_color=background_color,
                still_image=media_kind == "image",
            )
            input_args = ["-i", str(image_path)] if media_kind == "image" else ["-stream_loop", "-1", "-i", str(image_path)]
            _run([
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                *input_args, "-vf", filter_graph, "-frames:v", str(frames), "-an",
                "-c:v", "libx264", "-profile:v", "high", "-preset", "veryfast", "-crf", "18",
                "-pix_fmt", "yuv420p", "-video_track_timescale", str(fps * 1000), str(scene_path),
            ], timeout=max(180, math.ceil(frames / fps * 12)))
            scene_paths.append(scene_path)

        concat_manifest = directory / "scenes.txt"
        concat_manifest.write_text(
            "\n".join(f"file '{path.as_posix()}'" for path in scene_paths) + "\n",
            encoding="utf-8",
        )
        slideshow_path = directory / "slideshow.mp4"
        _run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "concat", "-safe", "0", "-i", str(concat_manifest),
            "-map", "0:v:0", "-c", "copy", str(slideshow_path),
        ], timeout=max(180, math.ceil(total_frames / fps * 6)))

        subtitle_path = directory / "captions.ass"
        subtitle_path.write_text(_subtitle_ass(
            cues,
            width=width,
            height=height,
            caption_top=caption_top,
            caption_left=caption_left,
            caption_right=caption_right,
            caption_bottom=caption_bottom,
            font_family=caption_font_family,
            font_size=caption_font_size,
            color=caption_color,
            outline_color=caption_outline_color,
            align=caption_align,
        ), encoding="utf-8")
        output_path = directory / "image-story.mp4"
        if not re.fullmatch(r"#[0-9A-Fa-f]{6}", background_color):
            raise ValueError(f"invalid RGB color: {background_color}")
        background = background_color.removeprefix("#")
        filter_graph = (
            f"[0:v]pad={width}:{height}:{image_left}:{image_top}:color=0x{background}[framed];"
            f"[framed]ass={subtitle_path.as_posix()}[video]"
        )
        command = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(slideshow_path),
        ]
        if audio_path is not None:
            command.extend(["-i", str(audio_path)])
        command.extend(["-filter_complex", filter_graph, "-map", "[video]"])
        if audio_path is not None:
            command.extend(["-map", "1:a:0", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"])
        else:
            command.append("-an")
        command.extend([
            "-frames:v", str(total_frames), "-r", str(fps),
            "-c:v", "libx264", "-profile:v", "high", "-level", "4.1", "-preset", "veryfast", "-crf", "18",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(output_path),
        ])
        _run(command, timeout=max(240, math.ceil(total_frames / fps * 18)))
        metadata = _probe(output_path)
        video_stream = next((item for item in metadata.get("streams", []) if item.get("codec_type") == "video"), None)
        if not video_stream:
            raise RuntimeError("Image Story Video renderer produced no video stream")
        duration_ms = round(float((metadata.get("format") or {}).get("duration") or 0) * 1000)
        return RenderedImageStory(
            data=output_path.read_bytes(),
            width=int(video_stream.get("width") or width),
            height=int(video_stream.get("height") or height),
            fps=fps,
            duration_ms=duration_ms,
            scene_count=len(images),
            cue_count=len(cues),
            has_audio=any(item.get("codec_type") == "audio" for item in metadata.get("streams", [])),
            motion_plan=tuple(motion_plan),
            renderer_environment=environment,
        )
