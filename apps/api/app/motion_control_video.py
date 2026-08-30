from __future__ import annotations

import bisect
import json
import math
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np


MOTION_CONTROL_VIDEO_REVISION = "motion-control-video.v1"
MOTION_CONTROL_VIDEO_SCHEMA = "motion.control_video.v1"

POSE_CONNECTIONS = (
    (11, 12), (11, 13), (13, 15), (12, 14), (14, 16), (11, 23), (12, 24), (23, 24),
    (23, 25), (25, 27), (27, 29), (29, 31), (24, 26), (26, 28), (28, 30), (30, 32),
)
PALM_CONNECTIONS = ((0, 1), (0, 5), (5, 9), (9, 13), (13, 17), (17, 0))
FINGERS = (
    ((1, 2, 3, 4), (247, 202, 93)),
    ((5, 6, 7, 8), (255, 134, 168)),
    ((9, 10, 11, 12), (111, 223, 244)),
    ((13, 14, 15, 16), (185, 156, 255)),
    ((17, 18, 19, 20), (157, 228, 111)),
)
FACE_CHAINS = (
    (10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288, 397, 365, 379, 378, 400, 377, 152, 148, 176, 149, 150, 136, 172, 58, 132, 93, 234, 127, 162, 21, 54, 103, 67, 109, 10),
    (33, 160, 158, 133, 153, 144, 33),
    (362, 385, 387, 263, 373, 380, 362),
    (61, 146, 91, 181, 84, 17, 314, 405, 321, 375, 291, 61),
)


@dataclass(frozen=True)
class RenderedMotionControlVideo:
    data: bytes
    width: int
    height: int
    fps: int
    duration_ms: int
    frame_count: int


def parse_motion_track(content: bytes) -> dict[str, Any]:
    try:
        motion_track = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("MotionTrack artifact does not contain valid JSON") from exc
    if not isinstance(motion_track, dict) or motion_track.get("schema_version") != "motion.track.v1":
        raise ValueError("MotionTrack artifact must use motion.track.v1")
    source = motion_track.get("source")
    frames = motion_track.get("frames")
    if not isinstance(source, dict) or not isinstance(frames, list) or not frames:
        raise ValueError("MotionTrack artifact is missing source metadata or frames")
    timestamps = [frame.get("timestamp_ms") for frame in frames if isinstance(frame, dict)]
    if len(timestamps) != len(frames) or any(not isinstance(value, int) or value < 0 for value in timestamps):
        raise ValueError("MotionTrack frames require non-negative integer timestamps")
    if timestamps != sorted(timestamps):
        raise ValueError("MotionTrack frame timestamps must be ordered")
    return motion_track


def _landmarks(frame: dict[str, Any], key: str) -> list[dict[str, float]]:
    values = frame.get(key)
    if not isinstance(values, list):
        return []
    return [item for item in values if isinstance(item, dict) and all(isinstance(item.get(axis), (int, float)) for axis in ("x", "y", "z"))]


def _interpolate_landmarks(
    before: list[dict[str, float]],
    after: list[dict[str, float]],
    ratio: float,
) -> list[dict[str, float]]:
    if not before or not after or len(before) != len(after):
        return before if before and ratio < 0.5 else after
    return [
        {
            "x": float(left["x"]) + (float(right["x"]) - float(left["x"])) * ratio,
            "y": float(left["y"]) + (float(right["y"]) - float(left["y"])) * ratio,
            "z": float(left["z"]) + (float(right["z"]) - float(left["z"])) * ratio,
            "visibility": min(float(left.get("visibility", 1.0)), float(right.get("visibility", 1.0))),
        }
        for left, right in zip(before, after, strict=True)
    ]


def _sample_frame(frames: list[dict[str, Any]], timestamps: list[int], timestamp_ms: int) -> dict[str, Any]:
    right_index = bisect.bisect_left(timestamps, timestamp_ms)
    if right_index <= 0:
        return frames[0]
    if right_index >= len(frames):
        return frames[-1]
    left_index = right_index - 1
    left_timestamp = timestamps[left_index]
    right_timestamp = timestamps[right_index]
    ratio = (timestamp_ms - left_timestamp) / max(1, right_timestamp - left_timestamp)
    left = frames[left_index]
    right = frames[right_index]
    return {
        key: _interpolate_landmarks(_landmarks(left, key), _landmarks(right, key), ratio)
        for key in ("face_landmarks", "pose_landmarks", "left_hand_landmarks", "right_hand_landmarks")
    }


def _point(landmark: dict[str, float], width: int, height: int) -> tuple[int, int]:
    return round(float(landmark["x"]) * (width - 1)), round(float(landmark["y"]) * (height - 1))


def _draw_disc(frame: np.ndarray, point: tuple[int, int], radius: int, color: tuple[int, int, int]) -> None:
    x, y = point
    height, width = frame.shape[:2]
    left, right = max(0, x - radius), min(width, x + radius + 1)
    top, bottom = max(0, y - radius), min(height, y + radius + 1)
    if left >= right or top >= bottom:
        return
    grid_y, grid_x = np.ogrid[top:bottom, left:right]
    mask = (grid_x - x) ** 2 + (grid_y - y) ** 2 <= radius ** 2
    frame[top:bottom, left:right][mask] = color


def _draw_line(
    frame: np.ndarray,
    start: tuple[int, int],
    end: tuple[int, int],
    width: int,
    color: tuple[int, int, int],
) -> None:
    frame_height, frame_width = frame.shape[:2]
    steps = max(abs(end[0] - start[0]), abs(end[1] - start[1]), 1) + 1
    x_values = np.rint(np.linspace(start[0], end[0], steps)).astype(np.int32)
    y_values = np.rint(np.linspace(start[1], end[1], steps)).astype(np.int32)
    radius = max(0, width // 2)
    for offset_y in range(-radius, radius + 1):
        for offset_x in range(-radius, radius + 1):
            if offset_x * offset_x + offset_y * offset_y > radius * radius:
                continue
            x = x_values + offset_x
            y = y_values + offset_y
            valid = (x >= 0) & (x < frame_width) & (y >= 0) & (y < frame_height)
            frame[y[valid], x[valid]] = color


def _draw_connections(
    frame: np.ndarray,
    landmarks: list[dict[str, float]],
    connections: tuple[tuple[int, int], ...] | list[tuple[int, int]],
    color: tuple[int, int, int],
    line_width: int,
) -> None:
    for start_index, end_index in connections:
        if start_index >= len(landmarks) or end_index >= len(landmarks):
            continue
        start = landmarks[start_index]
        end = landmarks[end_index]
        if float(start.get("visibility", 1.0)) < 0.2 or float(end.get("visibility", 1.0)) < 0.2:
            continue
        _draw_line(frame, _point(start, frame.shape[1], frame.shape[0]), _point(end, frame.shape[1], frame.shape[0]), line_width, color)


def _draw_hand(
    frame: np.ndarray,
    landmarks: list[dict[str, float]],
    palm_color: tuple[int, int, int],
    line_width: int,
    point_radius: int,
) -> None:
    if len(landmarks) != 21:
        return
    _draw_connections(frame, landmarks, list(PALM_CONNECTIONS), palm_color, line_width)
    for indices, color in FINGERS:
        connections = [(indices[index], indices[index + 1]) for index in range(len(indices) - 1)]
        _draw_connections(frame, landmarks, connections, color, line_width)
        _draw_disc(frame, _point(landmarks[indices[-1]], frame.shape[1], frame.shape[0]), point_radius + 1, color)
    for landmark in landmarks:
        _draw_disc(frame, _point(landmark, frame.shape[1], frame.shape[0]), point_radius, palm_color)


def _draw_control_frame(
    sampled: dict[str, Any],
    *,
    width: int,
    height: int,
    theme: str,
    draw_pose: bool,
    draw_face: bool,
    draw_hands: bool,
    line_width: int,
    point_radius: int,
) -> np.ndarray:
    dark = theme == "dark"
    frame = np.full((height, width, 3), (7, 9, 13) if dark else (246, 247, 244), dtype=np.uint8)
    pose_color = (111, 240, 229) if dark else (10, 112, 105)
    face_color = (232, 236, 230) if dark else (45, 49, 43)
    left_color = (255, 136, 188) if dark else (184, 41, 105)
    right_color = (214, 255, 111) if dark else (82, 119, 9)
    pose = _landmarks(sampled, "pose_landmarks")
    face = _landmarks(sampled, "face_landmarks")
    if draw_pose:
        _draw_connections(frame, pose, list(POSE_CONNECTIONS), pose_color, line_width)
        for landmark in pose:
            if float(landmark.get("visibility", 1.0)) >= 0.2:
                _draw_disc(frame, _point(landmark, width, height), point_radius, pose_color)
    if draw_face:
        for chain in FACE_CHAINS:
            connections = [(chain[index], chain[index + 1]) for index in range(len(chain) - 1)]
            _draw_connections(frame, face, connections, face_color, max(1, line_width - 2))
    if draw_hands:
        _draw_hand(frame, _landmarks(sampled, "left_hand_landmarks"), left_color, line_width, point_radius)
        _draw_hand(frame, _landmarks(sampled, "right_hand_landmarks"), right_color, line_width, point_radius)
    return frame


def render_motion_control_video(
    motion_track: dict[str, Any],
    *,
    width: int,
    output_fps: int,
    theme: str,
    draw_pose: bool,
    draw_face: bool,
    draw_hands: bool,
    line_width: int,
    point_radius: int,
) -> RenderedMotionControlVideo:
    source = motion_track["source"]
    source_width = int(source.get("width") or source.get("sample_width") or 0)
    source_height = int(source.get("height") or source.get("sample_height") or 0)
    duration_ms = int(source.get("duration_ms") or 0)
    frames = list(motion_track["frames"])
    if source_width <= 0 or source_height <= 0 or duration_ms <= 0:
        raise ValueError("MotionTrack source dimensions and duration must be positive")
    height = max(2, round(width * source_height / source_width) // 2 * 2)
    frame_count = max(1, math.ceil(duration_ms / 1000 * output_fps))
    timestamps = [int(frame["timestamp_ms"]) for frame in frames]
    with tempfile.TemporaryDirectory(prefix="frameflow-motion-control-") as temp_dir:
        output_path = Path(temp_dir) / "motion-control.mp4"
        command = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}", "-r", str(output_fps), "-i", "pipe:0",
            "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            str(output_path),
        ]
        try:
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        except FileNotFoundError as exc:
            raise RuntimeError("ffmpeg is required to render Motion control video") from exc
        if process.stdin is None or process.stderr is None:
            process.kill()
            raise RuntimeError("failed to open ffmpeg Motion control video pipes")
        try:
            for frame_index in range(frame_count):
                timestamp_ms = min(duration_ms, round(frame_index * 1000 / output_fps))
                sampled = _sample_frame(frames, timestamps, timestamp_ms)
                rendered = _draw_control_frame(
                    sampled,
                    width=width,
                    height=height,
                    theme=theme,
                    draw_pose=draw_pose,
                    draw_face=draw_face,
                    draw_hands=draw_hands,
                    line_width=line_width,
                    point_radius=point_radius,
                )
                process.stdin.write(rendered.tobytes())
            process.stdin.close()
            stderr = process.stderr.read().decode("utf-8", errors="replace")
            return_code = process.wait(timeout=max(60, math.ceil(duration_ms / 1000 * 5)))
        except Exception:
            process.kill()
            process.wait(timeout=10)
            raise
        finally:
            if not process.stderr.closed:
                process.stderr.close()
        if return_code:
            raise RuntimeError(f"ffmpeg Motion control video render failed: {stderr[-1600:]}")
        return RenderedMotionControlVideo(
            data=output_path.read_bytes(),
            width=width,
            height=height,
            fps=output_fps,
            duration_ms=duration_ms,
            frame_count=frame_count,
        )
