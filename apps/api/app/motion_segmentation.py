from __future__ import annotations

import copy
import json
from typing import Any

from .motion_control_video import parse_motion_track


MOTION_SEGMENT_REVISION = "motion-segment.v1"
MOTION_SEGMENT_SCHEMA = "motion.track.segment.v1"


def _coverage(frames: list[dict[str, Any]]) -> dict[str, float]:
    keys = {
        "face": "face_landmarks",
        "pose": "pose_landmarks",
        "left_hand": "left_hand_landmarks",
        "right_hand": "right_hand_landmarks",
    }
    return {
        label: round(sum(bool(frame.get(field)) for frame in frames) / len(frames), 4)
        for label, field in keys.items()
    }


def segment_motion_track(
    motion_track: dict[str, Any],
    *,
    start_seconds: float,
    duration_seconds: float,
    time_scale: float,
) -> dict[str, Any]:
    parsed = parse_motion_track(json.dumps(copy.deepcopy(motion_track)).encode())
    source = dict(parsed["source"])
    source_duration_ms = int(source["duration_ms"])
    start_ms = round(start_seconds * 1000)
    requested_duration_ms = round(duration_seconds * 1000)
    if start_ms >= source_duration_ms:
        raise ValueError("Motion segment start must be before the MotionTrack duration")
    end_ms = min(source_duration_ms, start_ms + requested_duration_ms)
    source_frames = list(parsed["frames"])
    selected = [copy.deepcopy(frame) for frame in source_frames if start_ms <= int(frame["timestamp_ms"]) < end_ms]
    if not selected:
        nearest = min(source_frames, key=lambda frame: abs(int(frame["timestamp_ms"]) - start_ms))
        selected = [copy.deepcopy(nearest)]
    for frame in selected:
        frame["timestamp_ms"] = max(0, round((int(frame["timestamp_ms"]) - start_ms) * time_scale))
    output_duration_ms = max(1, round((end_ms - start_ms) * time_scale))
    if selected[0]["timestamp_ms"] != 0:
        first = copy.deepcopy(selected[0])
        first["timestamp_ms"] = 0
        selected.insert(0, first)
    if selected[-1]["timestamp_ms"] < output_duration_ms:
        last = copy.deepcopy(selected[-1])
        last["timestamp_ms"] = output_duration_ms
        selected.append(last)
    source["duration_ms"] = output_duration_ms
    source["sample_fps"] = round(float(source.get("sample_fps") or 1) / time_scale, 6)
    return {
        **parsed,
        "source": source,
        "summary": {"frame_count": len(selected), "coverage": _coverage(selected)},
        "frames": selected,
    }
