#!/usr/bin/env python3
"""Measure MediaPipe-to-canonical coverage on a rights-cleared dance clip."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--fps", type=float, default=8)
    args = parser.parse_args()
    repository = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repository / "apps/api"))

    from app.character_motion.mediapipe_adapter import MediaPipeMotionAdapter
    from app.motion_extraction import extract_holistic_motion

    source = args.input.resolve()
    track = extract_holistic_motion(
        source.read_bytes(), "video/mp4", sample_fps=args.fps, max_width=640,
        min_confidence=0.5, output_face_blendshapes=False,
    )
    motion = MediaPipeMotionAdapter().convert(track, source_artifact_id=source.name)
    frames = motion["frames"]

    def angle(quaternion: list[float]) -> float:
        return math.degrees(2 * math.acos(max(-1.0, min(1.0, abs(quaternion[3])))))

    def root_range(axis: int) -> float:
        values = [frame["root"]["position"][axis] for frame in frames]
        return round(max(values) - min(values), 4)

    bones = ["hips", "spine", "leftUpperArm", "rightUpperArm", "leftUpperLeg", "rightUpperLeg"]
    confidence_bones = [*bones, "leftFoot", "rightFoot"]
    summary = {
        "source": track["source"],
        "coverage": track["summary"]["coverage"],
        "frame_count": len(frames),
        "invalid_frame_ratio": motion["metadata"]["invalid_frame_ratio"],
        "root_range_m": {"x": root_range(0), "y": root_range(1), "z": root_range(2)},
        "bone_rotation_max_degrees": {
            bone: round(max(angle(frame["bones"][bone]["rotation"]) for frame in frames), 1)
            for bone in bones
        },
        "low_confidence_ratio": {
            bone: round(sum(frame["bones"][bone]["confidence"] < 0.5 for frame in frames) / len(frames), 3)
            for bone in confidence_bones
        },
        "foot_contact_frames": {
            side: sum(bool(frame["contacts"][side]["active"]) for frame in frames)
            for side in ("leftFoot", "rightFoot")
        },
    }
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
