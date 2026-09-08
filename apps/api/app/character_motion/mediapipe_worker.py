from __future__ import annotations

import argparse
from pathlib import Path

from ..motion_extraction import extract_holistic_motion
from .canonical_motion import canonical_motion_bytes
from .mediapipe_adapter import MediaPipeMotionAdapter


def _safe_path(value: str, *, must_exist: bool) -> Path:
    path = Path(value).resolve()
    root = Path.cwd().resolve()
    if root != path.parent and root not in path.parents:
        raise ValueError(f"MediaPipe worker path escapes its isolated work directory: {path}")
    if must_exist and not path.is_file():
        raise ValueError(f"MediaPipe worker input does not exist: {path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--content-type", default="video/mp4")
    parser.add_argument("--fps", type=float, required=True)
    parser.add_argument("--max-width", type=int, required=True)
    parser.add_argument("--confidence", type=float, required=True)
    parser.add_argument("--include-hands", action="store_true")
    parser.add_argument("--include-face", action="store_true")
    parser.add_argument("--source-artifact-id", required=True)
    args = parser.parse_args()
    source = _safe_path(args.input, must_exist=True)
    output = _safe_path(args.output, must_exist=False)
    track = extract_holistic_motion(
        source.read_bytes(), args.content_type, sample_fps=args.fps,
        max_width=args.max_width, min_confidence=args.confidence,
        output_face_blendshapes=args.include_face,
    )
    motion = MediaPipeMotionAdapter().convert(
        track,
        source_artifact_id=args.source_artifact_id,
        include_hands=args.include_hands,
        include_face=args.include_face,
    )
    output.write_bytes(canonical_motion_bytes(motion))
    print(f"FRAMEFLOW MediaPipe extracted {len(motion['frames'])} canonical frames", flush=True)


if __name__ == "__main__":
    main()
