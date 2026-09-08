from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable

from .canonical_motion import (
    BONE_NAMES,
    quaternion_dot,
    quaternion_limit_angle,
    quaternion_normalize,
    quaternion_slerp,
    validate_canonical_motion,
    vector_lerp,
)


MOTION_CLEANUP_REVISION = "humanoid-motion-cleanup.v1"
JOINT_LIMIT_DEGREES = {
    "hips": 100, "spine": 65, "chest": 70, "neck": 75, "head": 85,
    "leftShoulder": 90, "rightShoulder": 90,
    "leftUpperArm": 170, "rightUpperArm": 170,
    "leftLowerArm": 155, "rightLowerArm": 155,
    "leftHand": 100, "rightHand": 100,
    "leftUpperLeg": 145, "rightUpperLeg": 145,
    "leftLowerLeg": 155, "rightLowerLeg": 155,
    "leftFoot": 75, "rightFoot": 75,
}


def _neighbors(valid_indexes: list[int], index: int) -> tuple[int | None, int | None]:
    previous = next((candidate for candidate in reversed(valid_indexes) if candidate < index), None)
    following = next((candidate for candidate in valid_indexes if candidate > index), None)
    return previous, following


def _interpolate_value(
    frames: list[dict[str, Any]],
    index: int,
    valid_indexes: list[int],
    getter: Callable[[dict[str, Any]], list[float]],
    *,
    quaternion: bool,
    policy: str,
) -> list[float]:
    previous, following = _neighbors(valid_indexes, index)
    if policy == "hold":
        source = previous if previous is not None else following
        if source is None:
            return [0.0, 0.0, 0.0, 1.0] if quaternion else [0.0, 0.0, 0.0]
        return list(getter(frames[source]))
    if previous is None and following is None:
        return [0.0, 0.0, 0.0, 1.0] if quaternion else [0.0, 0.0, 0.0]
    if previous is None:
        return list(getter(frames[following]))
    if following is None:
        return list(getter(frames[previous]))
    start_time = float(frames[previous]["time"])
    end_time = float(frames[following]["time"])
    amount = 0.0 if end_time <= start_time else (float(frames[index]["time"]) - start_time) / (end_time - start_time)
    return (
        quaternion_slerp(getter(frames[previous]), getter(frames[following]), amount)
        if quaternion
        else vector_lerp(getter(frames[previous]), getter(frames[following]), amount)
    )


def _round_vector(values: list[float]) -> list[float]:
    return [round(float(value), 7) for value in values]


def cleanup_motion(
    motion: dict[str, Any],
    *,
    smoothing: float,
    confidence_threshold: float,
    invalid_frame_policy: str,
    joint_limits: bool,
    root_stabilization: bool,
    foot_lock: bool,
) -> dict[str, Any]:
    validate_canonical_motion(motion)
    if invalid_frame_policy not in {"interpolate", "hold", "error"}:
        raise ValueError("invalid frame policy must be interpolate, hold, or error")
    smoothing = max(0.0, min(0.95, float(smoothing)))
    confidence_threshold = max(0.0, min(1.0, float(confidence_threshold)))
    result = deepcopy(motion)
    frames = result["frames"]
    invalid_indexes = [
        index for index, frame in enumerate(frames)
        if not frame["valid"] or float(frame["root"]["confidence"]) < confidence_threshold
    ]
    invalid_ratio = len(invalid_indexes) / len(frames)
    if invalid_frame_policy == "error" and invalid_indexes:
        raise ValueError(f"Motion contains {invalid_ratio:.0%} invalid frames; choose interpolate or hold to repair them")
    root_valid = [index for index in range(len(frames)) if index not in invalid_indexes]
    if not root_valid:
        raise ValueError("No usable hip/root trajectory was detected")
    repaired_frames = 0
    for index in invalid_indexes:
        frames[index]["root"]["position"] = _round_vector(_interpolate_value(
            frames, index, root_valid, lambda frame: frame["root"]["position"],
            quaternion=False, policy=invalid_frame_policy,
        ))
        frames[index]["root"]["rotation"] = _round_vector(_interpolate_value(
            frames, index, root_valid, lambda frame: frame["root"]["rotation"],
            quaternion=True, policy=invalid_frame_policy,
        ))
        frames[index]["root"]["confidence"] = confidence_threshold
        frames[index]["valid"] = True
        repaired_frames += 1

    for bone_name in BONE_NAMES:
        valid = [
            index for index, frame in enumerate(frames)
            if bone_name in frame["bones"] and float(frame["bones"][bone_name]["confidence"]) >= confidence_threshold
        ]
        if not valid:
            # Optional/occluded semantic channels remain identity rather than
            # inventing target-rig translations.
            for frame in frames:
                frame["bones"][bone_name] = {"rotation": [0.0, 0.0, 0.0, 1.0], "confidence": 0.0}
            continue
        for index, frame in enumerate(frames):
            transform = frame["bones"].get(bone_name)
            if transform and float(transform["confidence"]) >= confidence_threshold:
                continue
            frame["bones"][bone_name] = {
                "rotation": _round_vector(_interpolate_value(
                    frames, index, valid, lambda item, name=bone_name: item["bones"][name]["rotation"],
                    quaternion=True, policy=invalid_frame_policy,
                )),
                "confidence": confidence_threshold,
            }

    # Quaternion sign continuity, optional joint limit, and causal smoothing.
    previous_root: list[float] | None = None
    previous_bones: dict[str, list[float]] = {}
    alpha = 1.0 - smoothing
    for frame in frames:
        current_root = quaternion_normalize(frame["root"]["rotation"])
        if previous_root is not None and quaternion_dot(previous_root, current_root) < 0:
            current_root = [-value for value in current_root]
        if previous_root is not None and smoothing:
            current_root = quaternion_slerp(previous_root, current_root, alpha)
        frame["root"]["rotation"] = _round_vector(current_root)
        previous_root = current_root
        for bone_name in BONE_NAMES:
            current = quaternion_normalize(frame["bones"][bone_name]["rotation"])
            previous = previous_bones.get(bone_name)
            if previous is not None and quaternion_dot(previous, current) < 0:
                current = [-value for value in current]
            if joint_limits:
                current = quaternion_limit_angle(current, JOINT_LIMIT_DEGREES[bone_name])
            if previous is not None and smoothing:
                current = quaternion_slerp(previous, current, alpha)
            frame["bones"][bone_name]["rotation"] = _round_vector(current)
            previous_bones[bone_name] = current

    if smoothing:
        previous_position = list(frames[0]["root"]["position"])
        for frame in frames[1:]:
            current = list(frame["root"]["position"])
            previous_position = vector_lerp(previous_position, current, alpha)
            frame["root"]["position"] = _round_vector(previous_position)

    if root_stabilization:
        origin = list(frames[0]["root"]["position"])
        for frame in frames:
            position = list(frame["root"]["position"])
            frame["root"]["position"] = _round_vector([
                position[0] - origin[0],
                position[1],
                position[2] - origin[2],
            ])

    locked_frames = 0
    if foot_lock:
        anchors: dict[str, list[float] | None] = {"leftFoot": None, "rightFoot": None}
        observation_keys = {"leftFoot": "left_foot_position", "rightFoot": "right_foot_position"}
        for frame in frames:
            offsets: list[list[float]] = []
            observations = frame.get("observations") or {}
            for side, observation_key in observation_keys.items():
                observation = observations.get(observation_key)
                contact = frame["contacts"][side]
                if contact["active"] and observation:
                    if anchors[side] is None:
                        anchors[side] = list(observation)
                    offsets.append([
                        anchors[side][0] - float(observation[0]),
                        0.0,
                        anchors[side][2] - float(observation[2]),
                    ])
                else:
                    anchors[side] = None
            if offsets:
                position = list(frame["root"]["position"])
                correction = [sum(value[index] for value in offsets) / len(offsets) for index in range(3)]
                frame["root"]["position"] = _round_vector([
                    position[0] + correction[0], position[1], position[2] + correction[2],
                ])
                locked_frames += 1

    result["source"] = {
        "provider": "frameflow-cleanup",
        "revision": MOTION_CLEANUP_REVISION,
        "input_provider": motion["source"].get("provider"),
        "input_revision": motion["source"].get("revision"),
    }
    result["metadata"] = {
        **dict(result.get("metadata") or {}),
        "cleanup": {
            "revision": MOTION_CLEANUP_REVISION,
            "smoothing": smoothing,
            "confidence_threshold": confidence_threshold,
            "invalid_frame_policy": invalid_frame_policy,
            "joint_limits": joint_limits,
            "root_stabilization": root_stabilization,
            "foot_lock": foot_lock,
            "repaired_frame_count": repaired_frames,
            "input_invalid_frame_ratio": round(invalid_ratio, 6),
            "foot_locked_frame_count": locked_frames,
        },
    }
    return validate_canonical_motion(result)
