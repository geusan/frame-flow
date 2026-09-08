from __future__ import annotations

from typing import Any

from .canonical_motion import (
    BONE_NAMES,
    BONE_PARENTS,
    HUMANOID_MOTION_SCHEMA_VERSION,
    HUMANOID_PROFILE,
    quaternion_conjugate,
    quaternion_from_to,
    quaternion_multiply,
    quaternion_normalize,
    validate_canonical_motion,
    vector_length,
    vector_subtract,
)


MEDIAPIPE_ADAPTER_REVISION = "mediapipe-holistic-to-humanoid.v1"
IDENTITY = [0.0, 0.0, 0.0, 1.0]
REST_DIRECTIONS = {
    "hips": [1.0, 0.0, 0.0],
    "spine": [0.0, 1.0, 0.0],
    "chest": [0.0, 1.0, 0.0],
    "neck": [0.0, 1.0, 0.0],
    "head": [0.0, 1.0, 0.0],
    "leftShoulder": [1.0, 0.0, 0.0],
    "leftUpperArm": [1.0, 0.0, 0.0],
    "leftLowerArm": [1.0, 0.0, 0.0],
    "leftHand": [1.0, 0.0, 0.0],
    "rightShoulder": [-1.0, 0.0, 0.0],
    "rightUpperArm": [-1.0, 0.0, 0.0],
    "rightLowerArm": [-1.0, 0.0, 0.0],
    "rightHand": [-1.0, 0.0, 0.0],
    "leftUpperLeg": [0.0, -1.0, 0.0],
    "leftLowerLeg": [0.0, -1.0, 0.0],
    "leftFoot": [0.0, 0.0, 1.0],
    "rightUpperLeg": [0.0, -1.0, 0.0],
    "rightLowerLeg": [0.0, -1.0, 0.0],
    "rightFoot": [0.0, 0.0, 1.0],
}


def _point(landmarks: list[dict[str, Any]], index: int) -> list[float] | None:
    if index < 0 or index >= len(landmarks):
        return None
    item = landmarks[index]
    try:
        # MediaPipe camera/world coordinates are normalized into Frameflow's
        # right-handed Y-up, +Z-forward convention here and nowhere downstream.
        return [float(item["x"]), -float(item["y"]), -float(item["z"])]
    except (KeyError, TypeError, ValueError):
        return None


def _confidence(landmarks: list[dict[str, Any]], *indexes: int) -> float:
    values: list[float] = []
    for index in indexes:
        if index < 0 or index >= len(landmarks):
            return 0.0
        item = landmarks[index]
        values.append(min(float(item.get("visibility", 1.0)), float(item.get("presence", 1.0))))
    return max(0.0, min(1.0, sum(values) / max(1, len(values))))


def _midpoint(first: list[float] | None, second: list[float] | None) -> list[float] | None:
    if first is None or second is None:
        return None
    return [(first[index] + second[index]) / 2.0 for index in range(3)]


def _direction(start: list[float] | None, end: list[float] | None) -> list[float] | None:
    if start is None or end is None:
        return None
    value = vector_subtract(end, start)
    return value if vector_length(value) > 1e-7 else None


def _semantic_directions(pose: list[dict[str, Any]]) -> tuple[dict[str, list[float]], dict[str, float], dict[str, list[float]]]:
    points = {index: _point(pose, index) for index in range(len(pose))}
    hips = _midpoint(points.get(23), points.get(24))
    shoulders = _midpoint(points.get(11), points.get(12))
    ears = _midpoint(points.get(7), points.get(8))
    hand_left = _midpoint(points.get(17), points.get(19))
    hand_right = _midpoint(points.get(18), points.get(20))
    directions = {
        "hips": _direction(points.get(24), points.get(23)),
        "spine": _direction(hips, shoulders),
        "chest": _direction(hips, shoulders),
        "neck": _direction(shoulders, ears or points.get(0)),
        "head": _direction(ears or shoulders, points.get(0)),
        "leftShoulder": _direction(shoulders, points.get(11)),
        "leftUpperArm": _direction(points.get(11), points.get(13)),
        "leftLowerArm": _direction(points.get(13), points.get(15)),
        "leftHand": _direction(points.get(15), hand_left),
        "rightShoulder": _direction(shoulders, points.get(12)),
        "rightUpperArm": _direction(points.get(12), points.get(14)),
        "rightLowerArm": _direction(points.get(14), points.get(16)),
        "rightHand": _direction(points.get(16), hand_right),
        "leftUpperLeg": _direction(points.get(23), points.get(25)),
        "leftLowerLeg": _direction(points.get(25), points.get(27)),
        "leftFoot": _direction(points.get(27), points.get(31)),
        "rightUpperLeg": _direction(points.get(24), points.get(26)),
        "rightLowerLeg": _direction(points.get(26), points.get(28)),
        "rightFoot": _direction(points.get(28), points.get(32)),
    }
    confidence_indexes = {
        "hips": (23, 24), "spine": (23, 24, 11, 12), "chest": (23, 24, 11, 12),
        "neck": (11, 12, 7, 8), "head": (7, 8, 0),
        "leftShoulder": (11, 12), "leftUpperArm": (11, 13), "leftLowerArm": (13, 15), "leftHand": (15, 17, 19),
        "rightShoulder": (11, 12), "rightUpperArm": (12, 14), "rightLowerArm": (14, 16), "rightHand": (16, 18, 20),
        "leftUpperLeg": (23, 25), "leftLowerLeg": (25, 27), "leftFoot": (27, 31),
        "rightUpperLeg": (24, 26), "rightLowerLeg": (26, 28), "rightFoot": (28, 32),
    }
    return (
        {name: value for name, value in directions.items() if value is not None},
        {name: _confidence(pose, *indexes) for name, indexes in confidence_indexes.items()},
        {
            **({"root": hips} if hips else {}),
            **({"leftFoot": points[31]} if points.get(31) else {}),
            **({"rightFoot": points[32]} if points.get(32) else {}),
        },
    )


def _foot_contact(
    current: list[float] | None,
    previous: list[float] | None,
    confidence: float,
    elapsed: float,
) -> dict[str, float | bool]:
    if current is None or previous is None or elapsed <= 0 or confidence < 0.2:
        return {"active": False, "confidence": 0.0}
    velocity = vector_length(vector_subtract(current, previous)) / elapsed
    # World-landmark origin follows the hips, so height is relative. Velocity
    # is the strongest provider-independent cue available in this adapter.
    active = velocity < 0.12
    contact_confidence = max(0.0, min(1.0, (0.12 - velocity) / 0.12)) * confidence
    return {"active": active, "confidence": round(contact_confidence, 6)}


def _image_root_sample(pose: list[dict[str, Any]]) -> tuple[list[float] | None, float | None]:
    left_hip = _point(pose, 23)
    right_hip = _point(pose, 24)
    root = _midpoint(left_hip, right_hip)
    visible_points = [
        _point(pose, index)
        for index in (0, 7, 8, 11, 12, 23, 24, 27, 28, 31, 32)
        if _confidence(pose, index) >= 0.2
    ]
    visible = [point for point in visible_points if point is not None]
    if root is None or len(visible) < 4:
        return root, None
    image_height = max(point[1] for point in visible) - min(point[1] for point in visible)
    return root, (1.7 / image_height if image_height > 0.1 else None)


class MediaPipeMotionAdapter:
    """Convert existing `motion.track.v1` landmarks to semantic rotations.

    The adapter is intentionally before retargeting. Its parent-space rotations,
    root trajectory and confidence can be cached and reused with any humanoid rig.
    """

    revision = MEDIAPIPE_ADAPTER_REVISION

    def convert(
        self,
        track: dict[str, Any],
        *,
        source_artifact_id: str | None = None,
        include_hands: bool = False,
        include_face: bool = False,
    ) -> dict[str, Any]:
        if track.get("schema_version") != "motion.track.v1":
            raise ValueError("MediaPipe adapter requires motion.track.v1")
        source = track.get("source") or {}
        fps = float(source.get("sample_fps") or 0)
        if fps <= 0:
            raise ValueError("MediaPipe MotionTrack has no usable sample FPS")
        frames: list[dict[str, Any]] = []
        previous_positions: dict[str, list[float]] = {}
        previous_globals: dict[str, list[float]] = {}
        image_root_origin: list[float] | None = None
        image_meter_scale: float | None = None
        invalid_frames = 0
        for index, source_frame in enumerate(track.get("frames") or []):
            time = float(source_frame.get("timestamp_ms") or 0) / 1000.0
            pose_world = list(source_frame.get("pose_world_landmarks") or [])
            pose_image = list(source_frame.get("pose_landmarks") or [])
            direction_pose = pose_world or pose_image
            directions, confidences, positions = _semantic_directions(direction_pose)
            image_root, meter_scale = _image_root_sample(pose_image)
            if image_root_origin is None and image_root is not None:
                image_root_origin = image_root
                image_meter_scale = meter_scale or 1.0
            if image_root is not None and image_root_origin is not None:
                scale = image_meter_scale or meter_scale or 1.0
                positions["root"] = [
                    (image_root[axis] - image_root_origin[axis]) * scale
                    for axis in range(3)
                ]
            valid = len(direction_pose) >= 33 and "root" in positions and len(directions) >= 12
            invalid_frames += int(not valid)
            globals_by_bone: dict[str, list[float]] = {}
            bones: dict[str, Any] = {}
            for bone_name in BONE_NAMES:
                direction = directions.get(bone_name)
                if direction is None:
                    global_rotation = previous_globals.get(bone_name, IDENTITY)
                    confidence = 0.0
                else:
                    global_rotation = quaternion_from_to(REST_DIRECTIONS[bone_name], direction)
                    confidence = confidences.get(bone_name, 0.0)
                globals_by_bone[bone_name] = global_rotation
                parent = BONE_PARENTS[bone_name]
                parent_global = globals_by_bone.get(parent, IDENTITY) if parent else IDENTITY
                local_rotation = quaternion_multiply(quaternion_conjugate(parent_global), global_rotation)
                bones[bone_name] = {
                    "rotation": [round(value, 7) for value in quaternion_normalize(local_rotation)],
                    "confidence": round(confidence, 6),
                }
            root_position = positions.get("root") or previous_positions.get("root") or [0.0, 0.0, 0.0]
            elapsed = 0.0 if not frames else time - float(frames[-1]["time"])
            contacts = {
                "leftFoot": _foot_contact(positions.get("leftFoot"), previous_positions.get("leftFoot"), confidences.get("leftFoot", 0.0), elapsed),
                "rightFoot": _foot_contact(positions.get("rightFoot"), previous_positions.get("rightFoot"), confidences.get("rightFoot", 0.0), elapsed),
            }
            frame: dict[str, Any] = {
                "index": index,
                "time": round(time, 7),
                "valid": valid,
                "root": {
                    "position": [round(value, 7) for value in root_position],
                    "rotation": [round(value, 7) for value in globals_by_bone.get("hips", IDENTITY)],
                    "confidence": round(confidences.get("hips", 0.0), 6),
                },
                "bones": bones,
                "contacts": contacts,
                "observations": {
                    **({"left_foot_position": [round(value, 7) for value in positions["leftFoot"]]} if "leftFoot" in positions else {}),
                    **({"right_foot_position": [round(value, 7) for value in positions["rightFoot"]]} if "rightFoot" in positions else {}),
                },
            }
            if include_hands:
                frame["hands"] = {
                    "left": {"detected": bool(source_frame.get("left_hand_world_landmarks") or source_frame.get("left_hand_landmarks"))},
                    "right": {"detected": bool(source_frame.get("right_hand_world_landmarks") or source_frame.get("right_hand_landmarks"))},
                }
            if include_face:
                frame["face"] = {
                    "blendshapes": {
                        str(item.get("name")): float(item.get("score") or 0)
                        for item in source_frame.get("face_blendshapes") or []
                        if item.get("name")
                    },
                    "channels": dict(source_frame.get("channels") or {}),
                }
            frames.append(frame)
            previous_positions = positions or previous_positions
            previous_globals = globals_by_bone or previous_globals
        if not frames:
            raise ValueError("MediaPipe MotionTrack contains no frames")
        duration_seconds = max(float(source.get("duration_ms") or 0) / 1000.0, float(frames[-1]["time"]))
        result = {
            "schema_version": HUMANOID_MOTION_SCHEMA_VERSION,
            "coordinate_system": {"handedness": "right", "up_axis": "Y", "forward_axis": "Z", "units": "meters"},
            "fps": fps,
            "duration_seconds": round(duration_seconds, 7),
            "skeleton": {
                "profile": HUMANOID_PROFILE,
                "rotation_space": "parent",
                "quaternion_order": "xyzw",
                "bones": list(BONE_NAMES),
            },
            "source": {
                "provider": "mediapipe",
                "revision": self.revision,
                "landmark_schema": "motion.track.v1",
                **({"source_artifact_id": source_artifact_id} if source_artifact_id else {}),
            },
            "frames": frames,
            "metadata": {
                "source_extractor": track.get("extractor") or {},
                "coverage": (track.get("summary") or {}).get("coverage") or {},
                "invalid_frame_count": invalid_frames,
                "invalid_frame_ratio": round(invalid_frames / len(frames), 6),
                "adapter_notes": "Target rig bone lengths are not represented or modified.",
                "root_trajectory_source": "normalized image hip midpoint scaled to a 1.7m observed body height",
            },
        }
        return validate_canonical_motion(result)
