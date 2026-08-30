from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, BinaryIO

import httpx
import numpy as np


MOTION_TRACK_VERSION = "motion.track.v1"
MOTION_EXTRACTOR_REVISION = "mediapipe.holistic.v1"
DEFAULT_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/holistic_landmarker/"
    "holistic_landmarker/float16/latest/holistic_landmarker.task"
)


def _run_json(command: list[str], *, timeout: int = 90) -> dict[str, Any]:
    try:
        completed = subprocess.run(command, check=True, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise RuntimeError(f"required motion extraction tool is not installed: {command[0]}") from exc
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        detail = (getattr(exc, "stderr", "") or str(exc))[-1800:]
        raise RuntimeError(f"motion extraction media probe failed: {detail}") from exc
    return json.loads(completed.stdout)


def _ensure_model() -> Path:
    model_path = Path(
        os.getenv("HOLISTIC_LANDMARKER_MODEL_PATH")
        or Path.home() / ".cache" / "mediapipe" / "holistic_landmarker.task"
    ).expanduser()
    if model_path.exists() and model_path.stat().st_size > 1_000_000:
        return model_path
    model_path.parent.mkdir(parents=True, exist_ok=True)
    model_url = os.getenv("HOLISTIC_LANDMARKER_MODEL_URL") or DEFAULT_MODEL_URL
    temporary_path = model_path.with_suffix(".download")
    with httpx.stream("GET", model_url, follow_redirects=True, timeout=180) as response:
        response.raise_for_status()
        with temporary_path.open("wb") as output:
            for chunk in response.iter_bytes():
                output.write(chunk)
    if temporary_path.stat().st_size <= 1_000_000:
        temporary_path.unlink(missing_ok=True)
        raise RuntimeError("downloaded Holistic Landmarker model bundle is unexpectedly small")
    temporary_path.replace(model_path)
    return model_path


def _read_exact(stream: BinaryIO, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = stream.read(remaining)
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _landmark_payload(landmark: Any) -> dict[str, float]:
    payload = {
        "x": round(float(getattr(landmark, "x", 0.0) or 0.0), 6),
        "y": round(float(getattr(landmark, "y", 0.0) or 0.0), 6),
        "z": round(float(getattr(landmark, "z", 0.0) or 0.0), 6),
    }
    visibility = getattr(landmark, "visibility", None)
    presence = getattr(landmark, "presence", None)
    if visibility is not None:
        payload["visibility"] = round(float(visibility), 6)
    if presence is not None:
        payload["presence"] = round(float(presence), 6)
    return payload


def _landmarks_payload(landmarks: Any) -> list[dict[str, float]]:
    return [_landmark_payload(item) for item in (landmarks or [])]


def _blendshape_payload(blendshapes: Any) -> list[dict[str, float | str]]:
    result: list[dict[str, float | str]] = []
    for item in blendshapes or []:
        name = str(getattr(item, "category_name", "") or getattr(item, "display_name", "") or "")
        if not name:
            continue
        result.append({"name": name, "score": round(float(getattr(item, "score", 0.0) or 0.0), 6)})
    return result


def _safe_point(landmarks: list[dict[str, float]], index: int) -> dict[str, float] | None:
    return landmarks[index] if 0 <= index < len(landmarks) else None


def _retarget_channels(
    face: list[dict[str, float]],
    pose: list[dict[str, float]],
    blendshapes: list[dict[str, float | str]],
) -> dict[str, float]:
    values = {str(item["name"]): float(item["score"]) for item in blendshapes}
    channels = {
        "blink_left": round(values.get("eyeBlinkLeft", 0.0), 6),
        "blink_right": round(values.get("eyeBlinkRight", 0.0), 6),
        "jaw_open": round(values.get("jawOpen", 0.0), 6),
        "mouth_smile": round((values.get("mouthSmileLeft", 0.0) + values.get("mouthSmileRight", 0.0)) / 2, 6),
    }
    left_eye = _safe_point(face, 33)
    right_eye = _safe_point(face, 263)
    nose = _safe_point(face, 1)
    if left_eye and right_eye and nose:
        eye_dx = right_eye["x"] - left_eye["x"]
        eye_dy = right_eye["y"] - left_eye["y"]
        eye_width = max(math.hypot(eye_dx, eye_dy), 1e-5)
        midpoint_x = (left_eye["x"] + right_eye["x"]) / 2
        midpoint_y = (left_eye["y"] + right_eye["y"]) / 2
        channels.update({
            "head_yaw": round(max(-1.0, min(1.0, (nose["x"] - midpoint_x) / eye_width * 2.0)), 6),
            "head_pitch": round(max(-1.0, min(1.0, (nose["y"] - midpoint_y) / eye_width - 0.45)), 6),
            "head_roll": round(math.atan2(eye_dy, eye_dx), 6),
        })
    left_shoulder = _safe_point(pose, 11)
    right_shoulder = _safe_point(pose, 12)
    if left_shoulder and right_shoulder:
        channels.update({
            "shoulder_roll": round(math.atan2(right_shoulder["y"] - left_shoulder["y"], right_shoulder["x"] - left_shoulder["x"]), 6),
            "torso_x": round((left_shoulder["x"] + right_shoulder["x"]) / 2, 6),
            "torso_y": round((left_shoulder["y"] + right_shoulder["y"]) / 2, 6),
        })
    return channels


def extract_holistic_motion(
    video_data: bytes,
    content_type: str,
    *,
    sample_fps: float = 12.0,
    max_width: int = 640,
    min_confidence: float = 0.5,
    output_face_blendshapes: bool = True,
) -> dict[str, Any]:
    try:
        import mediapipe as mp
    except ImportError as exc:
        raise RuntimeError("mediapipe is required for Holistic motion extraction") from exc

    sample_fps = max(1.0, min(30.0, float(sample_fps)))
    max_width = max(256, min(1920, int(max_width)))
    min_confidence = max(0.0, min(1.0, float(min_confidence)))
    model_path = _ensure_model()

    with tempfile.TemporaryDirectory(prefix="frameflow-motion-") as temp_dir:
        source_path = Path(temp_dir) / ("source.mp4" if "mp4" in content_type else "source.video")
        source_path.write_bytes(video_data)
        probe = _run_json(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(source_path)])
        video_stream = next((item for item in probe.get("streams", []) if item.get("codec_type") == "video"), None)
        if not video_stream:
            raise ValueError("Motion Extractor requires a video stream")
        width = int(video_stream.get("width") or 0)
        height = int(video_stream.get("height") or 0)
        duration_seconds = float((probe.get("format") or {}).get("duration") or 0)
        if width <= 0 or height <= 0 or duration_seconds <= 0:
            raise ValueError("Motion Extractor input video metadata is invalid")
        scale = min(1.0, max_width / width)
        frame_width = max(2, int(width * scale) // 2 * 2)
        frame_height = max(2, int(height * scale) // 2 * 2)
        frame_size = frame_width * frame_height * 3
        process = subprocess.Popen(
            [
                "ffmpeg", "-v", "error", "-i", str(source_path),
                "-vf", f"fps={sample_fps},scale={frame_width}:{frame_height}",
                "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if process.stdout is None or process.stderr is None:
            process.kill()
            raise RuntimeError("failed to open FFmpeg motion extraction pipes")

        options = mp.tasks.vision.HolisticLandmarkerOptions(
            base_options=mp.tasks.BaseOptions(
                model_asset_path=str(model_path),
                delegate=mp.tasks.BaseOptions.Delegate.CPU,
            ),
            running_mode=mp.tasks.vision.RunningMode.VIDEO,
            min_face_detection_confidence=min_confidence,
            min_face_landmarks_confidence=min_confidence,
            min_pose_detection_confidence=min_confidence,
            min_pose_landmarks_confidence=min_confidence,
            min_hand_landmarks_confidence=min_confidence,
            output_face_blendshapes=output_face_blendshapes,
            output_segmentation_mask=False,
        )
        frames: list[dict[str, Any]] = []
        coverage = {"face": 0, "pose": 0, "left_hand": 0, "right_hand": 0}
        try:
            with mp.tasks.vision.HolisticLandmarker.create_from_options(options) as landmarker:
                frame_index = 0
                while True:
                    raw = _read_exact(process.stdout, frame_size)
                    if not raw:
                        break
                    if len(raw) != frame_size:
                        raise RuntimeError("FFmpeg returned a truncated RGB frame")
                    array = np.frombuffer(raw, dtype=np.uint8).reshape((frame_height, frame_width, 3)).copy()
                    image = mp.Image(image_format=mp.ImageFormat.SRGB, data=array)
                    timestamp_ms = round(frame_index * 1000 / sample_fps)
                    result = landmarker.detect_for_video(image, timestamp_ms)
                    face = _landmarks_payload(result.face_landmarks)
                    pose = _landmarks_payload(result.pose_landmarks)
                    pose_world = _landmarks_payload(result.pose_world_landmarks)
                    left_hand = _landmarks_payload(result.left_hand_landmarks)
                    left_hand_world = _landmarks_payload(result.left_hand_world_landmarks)
                    right_hand = _landmarks_payload(result.right_hand_landmarks)
                    right_hand_world = _landmarks_payload(result.right_hand_world_landmarks)
                    blendshapes = _blendshape_payload(result.face_blendshapes)
                    for key, detected in (
                        ("face", bool(face)),
                        ("pose", bool(pose)),
                        ("left_hand", bool(left_hand)),
                        ("right_hand", bool(right_hand)),
                    ):
                        coverage[key] += int(detected)
                    frames.append({
                        "timestamp_ms": timestamp_ms,
                        "face_landmarks": face,
                        "pose_landmarks": pose,
                        "pose_world_landmarks": pose_world,
                        "left_hand_landmarks": left_hand,
                        "left_hand_world_landmarks": left_hand_world,
                        "right_hand_landmarks": right_hand,
                        "right_hand_world_landmarks": right_hand_world,
                        "face_blendshapes": blendshapes,
                        "channels": _retarget_channels(face, pose, blendshapes),
                    })
                    frame_index += 1
        finally:
            extraction_error_active = sys.exc_info()[0] is not None
            process.stdout.close()
            stderr = process.stderr.read().decode("utf-8", errors="replace")
            process.stderr.close()
            return_code = process.wait(timeout=30)
            if return_code and not frames and not extraction_error_active:
                raise RuntimeError(f"FFmpeg motion decoding failed: {stderr[-1800:]}")

    frame_count = len(frames)
    if not frame_count:
        raise RuntimeError("Holistic Landmarker produced no sampled frames")
    coverage_ratio = {key: round(value / frame_count, 4) for key, value in coverage.items()}
    return {
        "schema_version": MOTION_TRACK_VERSION,
        "extractor": {
            "name": "MediaPipe Holistic Landmarker",
            "revision": MOTION_EXTRACTOR_REVISION,
            "model": model_path.name,
            "min_confidence": min_confidence,
            "output_face_blendshapes": output_face_blendshapes,
        },
        "source": {
            "duration_ms": round(duration_seconds * 1000),
            "width": width,
            "height": height,
            "sample_fps": sample_fps,
            "sample_width": frame_width,
            "sample_height": frame_height,
            "sha256": hashlib.sha256(video_data).hexdigest(),
        },
        "summary": {
            "frame_count": frame_count,
            "coverage": coverage_ratio,
        },
        "frames": frames,
    }
