from __future__ import annotations

import json
import math
from copy import deepcopy
from typing import Any, Iterable


HUMANOID_MOTION_SCHEMA_VERSION = "humanoid.motion.v1"
HUMANOID_PROFILE = "frameflow.humanoid.v1"
BONE_NAMES = (
    "hips", "spine", "chest", "neck", "head",
    "leftShoulder", "leftUpperArm", "leftLowerArm", "leftHand",
    "rightShoulder", "rightUpperArm", "rightLowerArm", "rightHand",
    "leftUpperLeg", "leftLowerLeg", "leftFoot",
    "rightUpperLeg", "rightLowerLeg", "rightFoot",
)
REQUIRED_RETARGET_BONES = (
    "hips", "spine", "chest", "neck", "head",
    "leftUpperArm", "leftLowerArm", "leftHand",
    "rightUpperArm", "rightLowerArm", "rightHand",
    "leftUpperLeg", "leftLowerLeg", "leftFoot",
    "rightUpperLeg", "rightLowerLeg", "rightFoot",
)
BONE_PARENTS: dict[str, str | None] = {
    "hips": None,
    "spine": "hips",
    "chest": "spine",
    "neck": "chest",
    "head": "neck",
    "leftShoulder": "chest",
    "leftUpperArm": "leftShoulder",
    "leftLowerArm": "leftUpperArm",
    "leftHand": "leftLowerArm",
    "rightShoulder": "chest",
    "rightUpperArm": "rightShoulder",
    "rightLowerArm": "rightUpperArm",
    "rightHand": "rightLowerArm",
    "leftUpperLeg": "hips",
    "leftLowerLeg": "leftUpperLeg",
    "leftFoot": "leftLowerLeg",
    "rightUpperLeg": "hips",
    "rightLowerLeg": "rightUpperLeg",
    "rightFoot": "rightLowerLeg",
}


def clamp(value: float, minimum: float, maximum: float) -> float:
    return min(maximum, max(minimum, value))


def vector_add(a: Iterable[float], b: Iterable[float]) -> list[float]:
    return [float(x) + float(y) for x, y in zip(a, b, strict=True)]


def vector_subtract(a: Iterable[float], b: Iterable[float]) -> list[float]:
    return [float(x) - float(y) for x, y in zip(a, b, strict=True)]


def vector_scale(vector: Iterable[float], scale: float) -> list[float]:
    return [float(value) * scale for value in vector]


def vector_lerp(a: Iterable[float], b: Iterable[float], amount: float) -> list[float]:
    return [float(x) + (float(y) - float(x)) * amount for x, y in zip(a, b, strict=True)]


def vector_length(vector: Iterable[float]) -> float:
    return math.sqrt(sum(float(value) ** 2 for value in vector))


def vector_normalize(vector: Iterable[float]) -> list[float]:
    values = [float(value) for value in vector]
    length = vector_length(values)
    return [0.0, 1.0, 0.0] if length < 1e-9 else [value / length for value in values]


def vector_dot(a: Iterable[float], b: Iterable[float]) -> float:
    return sum(float(x) * float(y) for x, y in zip(a, b, strict=True))


def vector_cross(a: Iterable[float], b: Iterable[float]) -> list[float]:
    x1, y1, z1 = [float(value) for value in a]
    x2, y2, z2 = [float(value) for value in b]
    return [y1 * z2 - z1 * y2, z1 * x2 - x1 * z2, x1 * y2 - y1 * x2]


def quaternion_normalize(quaternion: Iterable[float]) -> list[float]:
    values = [float(value) for value in quaternion]
    length = math.sqrt(sum(value * value for value in values))
    if length < 1e-9:
        return [0.0, 0.0, 0.0, 1.0]
    return [value / length for value in values]


def quaternion_dot(a: Iterable[float], b: Iterable[float]) -> float:
    return sum(float(x) * float(y) for x, y in zip(a, b, strict=True))


def quaternion_conjugate(quaternion: Iterable[float]) -> list[float]:
    x, y, z, w = quaternion_normalize(quaternion)
    return [-x, -y, -z, w]


def quaternion_multiply(a: Iterable[float], b: Iterable[float]) -> list[float]:
    ax, ay, az, aw = [float(value) for value in a]
    bx, by, bz, bw = [float(value) for value in b]
    return quaternion_normalize([
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
        aw * bw - ax * bx - ay * by - az * bz,
    ])


def quaternion_slerp(a: Iterable[float], b: Iterable[float], amount: float) -> list[float]:
    first = quaternion_normalize(a)
    second = quaternion_normalize(b)
    dot = quaternion_dot(first, second)
    if dot < 0:
        second = [-value for value in second]
        dot = -dot
    amount = clamp(float(amount), 0.0, 1.0)
    if dot > 0.9995:
        return quaternion_normalize([
            first[index] + (second[index] - first[index]) * amount
            for index in range(4)
        ])
    angle = math.acos(clamp(dot, -1.0, 1.0))
    sine = math.sin(angle)
    left = math.sin((1.0 - amount) * angle) / sine
    right = math.sin(amount * angle) / sine
    return quaternion_normalize([first[index] * left + second[index] * right for index in range(4)])


def quaternion_from_to(source: Iterable[float], target: Iterable[float]) -> list[float]:
    start = vector_normalize(source)
    end = vector_normalize(target)
    dot = clamp(vector_dot(start, end), -1.0, 1.0)
    if dot > 0.999999:
        return [0.0, 0.0, 0.0, 1.0]
    if dot < -0.999999:
        axis = vector_cross(start, [1.0, 0.0, 0.0])
        if vector_length(axis) < 1e-6:
            axis = vector_cross(start, [0.0, 0.0, 1.0])
        axis = vector_normalize(axis)
        return [axis[0], axis[1], axis[2], 0.0]
    axis = vector_cross(start, end)
    return quaternion_normalize([axis[0], axis[1], axis[2], 1.0 + dot])


def quaternion_limit_angle(quaternion: Iterable[float], maximum_degrees: float) -> list[float]:
    value = quaternion_normalize(quaternion)
    if value[3] < 0:
        value = [-component for component in value]
    angle = 2.0 * math.acos(clamp(value[3], -1.0, 1.0))
    maximum = math.radians(maximum_degrees)
    if angle <= maximum or angle < 1e-8:
        return value
    axis_length = math.sqrt(sum(component * component for component in value[:3]))
    if axis_length < 1e-9:
        return [0.0, 0.0, 0.0, 1.0]
    axis = [component / axis_length for component in value[:3]]
    sine = math.sin(maximum / 2.0)
    return [axis[0] * sine, axis[1] * sine, axis[2] * sine, math.cos(maximum / 2.0)]


def canonical_motion_bytes(motion: dict[str, Any]) -> bytes:
    validate_canonical_motion(motion)
    return json.dumps(motion, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def parse_canonical_motion(data: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Humanoid motion Artifact does not contain valid JSON") from exc
    validate_canonical_motion(payload)
    return payload


def _finite_vector(value: Any, size: int, label: str) -> list[float]:
    if not isinstance(value, list) or len(value) != size:
        raise ValueError(f"{label} must contain {size} numbers")
    result = [float(component) for component in value]
    if not all(math.isfinite(component) for component in result):
        raise ValueError(f"{label} contains a non-finite number")
    return result


def validate_canonical_motion(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("schema_version") != HUMANOID_MOTION_SCHEMA_VERSION:
        raise ValueError(f"Humanoid motion must use {HUMANOID_MOTION_SCHEMA_VERSION}")
    coordinate_system = payload.get("coordinate_system") or {}
    if coordinate_system != {"handedness": "right", "up_axis": "Y", "forward_axis": "Z", "units": "meters"}:
        raise ValueError("Humanoid motion must use the Frameflow right-handed Y-up coordinate system")
    skeleton = payload.get("skeleton") or {}
    if skeleton.get("profile") != HUMANOID_PROFILE or skeleton.get("rotation_space") != "parent" or skeleton.get("quaternion_order") != "xyzw":
        raise ValueError("Humanoid motion skeleton profile or rotation convention is unsupported")
    declared_bones = skeleton.get("bones")
    if not isinstance(declared_bones, list) or not declared_bones or len(declared_bones) != len(set(declared_bones)):
        raise ValueError("Humanoid motion must declare unique semantic bones")
    unknown_bones = sorted(set(declared_bones) - set(BONE_NAMES))
    if unknown_bones:
        raise ValueError(f"Humanoid motion declares unknown bones: {', '.join(unknown_bones)}")
    fps = float(payload.get("fps") or 0)
    if not 0 < fps <= 120:
        raise ValueError("Humanoid motion FPS must be greater than zero and at most 120")
    frames = payload.get("frames")
    if not isinstance(frames, list) or not frames:
        raise ValueError("Humanoid motion must contain at least one frame")
    previous_time = -1.0
    for expected_index, frame in enumerate(frames):
        if not isinstance(frame, dict) or frame.get("index") != expected_index:
            raise ValueError("Humanoid motion frame indexes must be contiguous from zero")
        time = float(frame.get("time", -1))
        if not math.isfinite(time) or time < 0 or time <= previous_time and expected_index > 0:
            raise ValueError("Humanoid motion frame times must be finite and strictly increasing")
        previous_time = time
        if not isinstance(frame.get("valid"), bool):
            raise ValueError(f"Humanoid motion frame {expected_index} is missing its validity flag")
        root = frame.get("root") or {}
        _finite_vector(root.get("position"), 3, f"frame {expected_index} root position")
        rotation = _finite_vector(root.get("rotation"), 4, f"frame {expected_index} root rotation")
        if abs(sum(value * value for value in rotation) - 1.0) > 1e-3:
            raise ValueError(f"frame {expected_index} root rotation is not a unit quaternion")
        root_confidence = float(root.get("confidence", -1))
        if not 0 <= root_confidence <= 1:
            raise ValueError(f"frame {expected_index} root confidence must be between zero and one")
        bones = frame.get("bones")
        if not isinstance(bones, dict):
            raise ValueError(f"frame {expected_index} bones must be an object")
        for bone_name, transform in bones.items():
            if bone_name not in declared_bones or not isinstance(transform, dict):
                raise ValueError(f"frame {expected_index} contains undeclared bone {bone_name}")
            raw_rotation = _finite_vector(transform.get("rotation"), 4, f"frame {expected_index} {bone_name} rotation")
            if abs(sum(value * value for value in raw_rotation) - 1.0) > 1e-3:
                raise ValueError(f"frame {expected_index} {bone_name} rotation is not a unit quaternion")
            confidence = float(transform.get("confidence", -1))
            if not 0 <= confidence <= 1:
                raise ValueError(f"frame {expected_index} {bone_name} confidence must be between zero and one")
            if "translation" in transform:
                _finite_vector(transform["translation"], 3, f"frame {expected_index} {bone_name} translation")
        contacts = frame.get("contacts") or {}
        for side in ("leftFoot", "rightFoot"):
            contact = contacts.get(side) or {}
            if not isinstance(contact.get("active"), bool) or not 0 <= float(contact.get("confidence", -1)) <= 1:
                raise ValueError(f"frame {expected_index} {side} contact is invalid")
    duration = float(payload.get("duration_seconds", -1))
    if not math.isfinite(duration) or duration < previous_time:
        raise ValueError("Humanoid motion duration ends before its final frame")
    source = payload.get("source") or {}
    if not str(source.get("provider") or "").strip() or not str(source.get("revision") or "").strip():
        raise ValueError("Humanoid motion source provider and revision are required")
    if not isinstance(payload.get("metadata"), dict):
        raise ValueError("Humanoid motion metadata must be an object")
    return deepcopy(payload)
