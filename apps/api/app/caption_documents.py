from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from .database import ArtifactRecord
from .font_registry import font_snapshots
from .storage import get_storage, storage_location


CAPTION_DOCUMENT_SCHEMA = "caption.document.v1"
TIMESTAMP_PREFIX = re.compile(r"^\s*\[\s*([0-9:.]+)\s*-\s*([0-9:.]+)\s*\]\s*")
HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")


def _timestamp_ms(value: str) -> int:
    parts = value.split(":")
    if len(parts) not in {2, 3}:
        raise ValueError(f"caption timestamp must be MM:SS or HH:MM:SS: {value}")
    try:
        seconds = float(parts[-1])
        minutes = int(parts[-2])
        hours = int(parts[-3]) if len(parts) == 3 else 0
    except ValueError as exc:
        raise ValueError(f"caption timestamp is invalid: {value}") from exc
    if hours < 0 or minutes < 0 or minutes >= 60 or seconds < 0 or seconds >= 60:
        raise ValueError(f"caption timestamp is out of range: {value}")
    return round((hours * 3600 + minutes * 60 + seconds) * 1000)


def _text_segments(node: dict[str, Any]) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    for child in node.get("content") or []:
        if not isinstance(child, dict):
            raise ValueError("caption editor content contains an invalid node")
        node_type = child.get("type")
        if node_type == "text":
            text = str(child.get("text") or "")
            if text:
                segments.append({"text": text, "marks": list(child.get("marks") or [])})
        elif node_type == "hardBreak":
            segments.append({"text": "\n", "marks": []})
        else:
            raise ValueError(f"caption lines cannot contain {node_type or 'unknown'} nodes")
    return segments


def _run_style(marks: list[Any], default_style: dict[str, Any]) -> dict[str, Any]:
    style = {
        "bold": bool(default_style.get("bold", False)),
        "italic": bool(default_style.get("italic", False)),
        "color": str(default_style.get("color") or "#FFFFFF").upper(),
        "font_id": default_style.get("font_id"),
        "font_size": float(default_style.get("font_size") or 54),
    }
    for mark in marks:
        if not isinstance(mark, dict):
            continue
        mark_type = mark.get("type")
        if mark_type == "bold":
            style["bold"] = True
        elif mark_type == "italic":
            style["italic"] = True
        elif mark_type == "textStyle":
            attrs = mark.get("attrs") or {}
            if attrs.get("color"):
                style["color"] = str(attrs["color"]).upper()
            if attrs.get("fontId"):
                style["font_id"] = str(attrs["fontId"])
            if attrs.get("fontSize"):
                size_text = str(attrs["fontSize"])
                match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)px", size_text)
                if not match:
                    raise ValueError(f"caption font size must use px: {size_text}")
                style["font_size"] = float(match.group(1))
    if not HEX_COLOR.fullmatch(str(style["color"])):
        raise ValueError(f"caption color is invalid: {style['color']}")
    if not 8 <= float(style["font_size"]) <= 240:
        raise ValueError("caption font size must be between 8 and 240")
    return style


def _caption_runs(segments: list[dict[str, Any]], prefix_length: int, default_style: dict[str, Any]) -> list[dict[str, Any]]:
    cursor = 0
    runs: list[dict[str, Any]] = []
    for segment in segments:
        text = str(segment["text"])
        start, end = cursor, cursor + len(text)
        cursor = end
        if end <= prefix_length:
            continue
        visible = text[max(0, prefix_length - start):]
        if not visible:
            continue
        style = _run_style(segment.get("marks") or [], default_style)
        run = {"text": visible, **style}
        comparable = {key: value for key, value in run.items() if key != "text"}
        if runs and {key: value for key, value in runs[-1].items() if key != "text"} == comparable:
            runs[-1]["text"] += visible
        else:
            runs.append(run)
    return runs


def canonical_caption_document(db: Session, document: dict[str, Any]) -> dict[str, Any]:
    if document.get("schema_version") != CAPTION_DOCUMENT_SCHEMA:
        raise ValueError(f"caption document must use {CAPTION_DOCUMENT_SCHEMA}")
    content = document.get("content")
    if not isinstance(content, dict) or content.get("type") != "doc":
        raise ValueError("caption document content must be a TipTap doc")
    default_style = dict(document.get("default_style") or {})
    default_style.setdefault("font_size", 54)
    default_style.setdefault("color", "#FFFFFF")
    _run_style([], default_style)

    cues: list[dict[str, Any]] = []
    for line_number, paragraph in enumerate(content.get("content") or [], start=1):
        if not isinstance(paragraph, dict) or paragraph.get("type") != "paragraph":
            raise ValueError("caption document supports one timestamped caption per paragraph")
        segments = _text_segments(paragraph)
        source = "".join(str(segment["text"]) for segment in segments)
        if not source.strip():
            continue
        match = TIMESTAMP_PREFIX.match(source)
        if not match:
            raise ValueError(f"caption line {line_number} must start with [MM:SS-MM:SS]")
        start_ms, end_ms = _timestamp_ms(match.group(1)), _timestamp_ms(match.group(2))
        if end_ms <= start_ms:
            raise ValueError(f"caption line {line_number} must end after it starts")
        runs = _caption_runs(segments, match.end(), default_style)
        if not any(str(run["text"]).strip() for run in runs):
            raise ValueError(f"caption line {line_number} has no text")
        cues.append({
            "id": str(paragraph.get("attrs", {}).get("id") or f"cue-{line_number}"),
            "start_ms": start_ms,
            "end_ms": end_ms,
            "runs": runs,
        })
    if not cues:
        raise ValueError("caption document has no timestamped captions")
    cues.sort(key=lambda cue: (cue["start_ms"], cue["end_ms"]))
    font_ids = {
        str(font_id)
        for font_id in [
            default_style.get("font_id"),
            *(run.get("font_id") for cue in cues for run in cue["runs"]),
        ]
        if font_id
    }
    return {
        "schema_version": CAPTION_DOCUMENT_SCHEMA,
        "content": content,
        "default_style": default_style,
        "cues": cues,
        "fonts": font_snapshots(db, font_ids),
    }


def _ass_timestamp(milliseconds: int) -> str:
    centiseconds = max(0, milliseconds) // 10
    hours, remainder = divmod(centiseconds, 360_000)
    minutes, remainder = divmod(remainder, 6_000)
    seconds, fraction = divmod(remainder, 100)
    return f"{hours}:{minutes:02}:{seconds:02}.{fraction:02}"


def _ass_color(value: str) -> str:
    match = re.fullmatch(r"#([0-9A-Fa-f]{2})([0-9A-Fa-f]{2})([0-9A-Fa-f]{2})", value)
    if not match:
        raise ValueError(f"invalid caption RGB color: {value}")
    red, green, blue = match.groups()
    return f"&H00{blue}{green}{red}".upper()


def _ass_text(value: str) -> str:
    return value.replace("\\", "／").replace("{", "(").replace("}", ")").replace("\n", r"\N")


def _safe_font_name(value: str) -> str:
    return re.sub(r"[,{}\\\r\n]", " ", value).strip() or "Noto Sans CJK KR"


def caption_document_to_ass(
    document: dict[str, Any],
    *,
    width: int,
    height: int,
    track_style: dict[str, Any],
) -> str:
    if document.get("schema_version") != CAPTION_DOCUMENT_SCHEMA or not document.get("cues"):
        raise ValueError("timeline contains an invalid canonical caption document")
    fonts = {str(item["font_id"]): item for item in document.get("fonts") or []}
    default_style = dict(document.get("default_style") or {})
    default_font = fonts.get(str(default_style.get("font_id") or ""))
    base_font = _safe_font_name(str((default_font or {}).get("family_name") or track_style.get("font_family") or "Noto Sans CJK KR"))
    base_size = float(default_style.get("font_size") or track_style.get("font_size") or 54)
    base_color = str(default_style.get("color") or track_style.get("color") or "#FFFFFF").upper()
    scale = min(width, height) / 1080
    scaled_base_size = max(8, round(base_size * scale * float((default_font or {}).get("size_adjust") or 1), 2))
    align = str(track_style.get("align") or "center")
    alignment = {"left": 4, "center": 5, "right": 6}.get(align)
    if alignment is None:
        raise ValueError("caption alignment must be left, center or right")
    frame = track_style.get("frame")
    clip_tag = ""
    if isinstance(frame, dict):
        left = round(float(frame.get("x", 0)) * width)
        top = round(float(frame.get("y", 0)) * height)
        right = left + round(float(frame.get("width", 1)) * width)
        bottom = top + round(float(frame.get("height", 1)) * height)
        if left < 0 or top < 0 or right > width or bottom > height or right <= left or bottom <= top:
            raise ValueError("caption frame must stay inside the Video Canvas")
        margin = max(8, round((right - left) * 0.04))
        x = {"left": left + margin, "center": left + (right - left) // 2, "right": right - margin}[align]
        y = top + (bottom - top) // 2
        clip_tag = f"\\clip({left},{top},{right},{bottom})"
    else:
        x = round(float(track_style.get("x", 0.5)) * width)
        y = round(float(track_style.get("y", 0.82)) * height)
    outline = max(1, round(4 * min(width, height) / 1080))
    events: list[str] = []
    for cue in document["cues"]:
        rendered_runs: list[str] = []
        for run in cue.get("runs") or []:
            font = fonts.get(str(run.get("font_id") or ""), default_font)
            family = _safe_font_name(str((font or {}).get("family_name") or base_font))
            font_size = max(8, round(float(run.get("font_size") or base_size) * scale * float((font or {}).get("size_adjust") or 1), 2))
            color = _ass_color(str(run.get("color") or base_color))
            tags = f"\\fn{family}\\fs{font_size}\\c{color}\\b{1 if run.get('bold') else 0}\\i{1 if run.get('italic') else 0}"
            rendered_runs.append(f"{{{tags}}}{_ass_text(str(run.get('text') or ''))}")
        events.append(
            "Dialogue: 0,"
            f"{_ass_timestamp(int(cue['start_ms']))},{_ass_timestamp(int(cue['end_ms']))},Caption,,0,0,0,,"
            f"{{\\an{alignment}\\pos({x},{y}){clip_tag}\\q2}}{''.join(rendered_runs)}"
        )
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
        f"Style: Caption,{base_font},{scaled_base_size},{_ass_color(base_color)},{_ass_color(base_color)},&H00000000,&H78000000,0,0,0,0,100,100,0,0,1,{outline},0,{alignment},24,24,24,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        *events,
        "",
    ])


def materialize_caption_fonts(db: Session, document: dict[str, Any], directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    storage = get_storage()
    for index, snapshot in enumerate(document.get("fonts") or []):
        artifact = db.get(ArtifactRecord, str(snapshot.get("artifact_id") or ""))
        if not artifact or artifact.type != "Font" or artifact.sha256 != snapshot.get("sha256"):
            raise ValueError("caption document font snapshot is unavailable or changed")
        bucket, key = storage_location(artifact.uri, artifact.metadata_json)
        suffix = Path(str((artifact.metadata_json or {}).get("filename") or "font.ttf")).suffix.lower()
        if suffix not in {".ttf", ".otf"}:
            suffix = ".ttf"
        (directory / f"{index:03d}-{artifact.sha256[:12]}{suffix}").write_bytes(storage.get_bytes(bucket=bucket, key=key))
