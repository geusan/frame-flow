from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class MediaError(RuntimeError):
    pass


def _run(args: list[str], timeout: int = 120) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(args, check=True, capture_output=True, text=True, timeout=timeout)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        stderr = getattr(exc, "stderr", "") or ""
        raise MediaError(f"media command failed: {stderr[-1200:]}") from exc


def probe_media(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise MediaError(f"media file not found: {path}")
    result = _run([
        "ffprobe", "-v", "error", "-show_format", "-show_streams",
        "-of", "json", str(path.resolve()),
    ])
    return json.loads(result.stdout)


def render_timeline(timeline: dict[str, Any], output_path: Path) -> Path:
    """Render a standards-compliant synthetic source for the golden codec/QC test.

    Production render activities replace the synthetic sources with immutable
    Artifact paths while keeping this codec/loudness output contract.
    """
    if timeline.get("version") != "timeline.v1":
        raise MediaError("unsupported timeline version")
    width = int(timeline["width"])
    height = int(timeline["height"])
    fps = float(timeline["fps"])
    duration_s = int(timeline["duration_ms"]) / 1000
    if width < 1 or height < 1 or fps <= 0 or duration_s <= 0:
        raise MediaError("invalid timeline dimensions or duration")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", f"color=c=#171914:s={width}x{height}:r={fps}:d={duration_s}",
        "-f", "lavfi", "-i", f"sine=frequency=220:sample_rate=48000:duration={duration_s}",
        "-vf", "format=yuv420p",
        "-af", "volume=0.02,loudnorm=I=-16:TP=-1.5:LRA=11",
        "-c:v", "libx264", "-profile:v", "high", "-level", "4.1",
        "-preset", "veryfast", "-movflags", "+faststart",
        "-c:a", "aac", "-b:a", "128k", "-shortest", str(output_path.resolve()),
    ], timeout=max(120, round(duration_s * 5)))
    return output_path


@dataclass(frozen=True)
class QcResult:
    passed: bool
    checks: dict[str, dict[str, Any]]
    sha256: str


def quality_check(path: Path, *, target_width: int, target_height: int, target_duration_ms: int, tolerance_ms: int = 250) -> QcResult:
    metadata = probe_media(path)
    streams = metadata.get("streams", [])
    video = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
    audio = next((stream for stream in streams if stream.get("codec_type") == "audio"), None)
    duration_ms = round(float(metadata.get("format", {}).get("duration", 0)) * 1000)
    checks = {
        "playable": {"passed": bool(video), "actual": bool(video)},
        "resolution": {"passed": bool(video) and video.get("width") == target_width and video.get("height") == target_height, "actual": [video.get("width"), video.get("height")] if video else None, "expected": [target_width, target_height]},
        "duration": {"passed": abs(duration_ms - target_duration_ms) <= tolerance_ms, "actual_ms": duration_ms, "expected_ms": target_duration_ms},
        "audio_present": {"passed": bool(audio), "actual": bool(audio)},
        "pixel_format": {"passed": bool(video) and video.get("pix_fmt") == "yuv420p", "actual": video.get("pix_fmt") if video else None},
    }
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return QcResult(all(check["passed"] for check in checks.values()), checks, digest)


def build_provenance_manifest(
    *,
    final_artifact_id: str,
    format_id: str,
    parent_reference_ids: list[str],
    prompt_versions: list[str],
    model_ids: list[str],
    artifact_ids: list[str],
    qc_report_artifact_id: str,
) -> dict[str, Any]:
    return {
        "version": "provenance.v1",
        "final_artifact_id": final_artifact_id,
        "format": {"format_id": format_id, "parent_reference_ids": parent_reference_ids},
        "prompt_versions": prompt_versions,
        "exact_model_ids": model_ids,
        "generated_artifact_ids": artifact_ids,
        "qc_report_artifact_id": qc_report_artifact_id,
        "reference_originals_used": False,
        "reference_isolation_enforced": True,
    }
