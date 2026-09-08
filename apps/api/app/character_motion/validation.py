from __future__ import annotations

import json
import math
import struct
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


GLB_MAGIC = b"glTF"
GLB_JSON_CHUNK = 0x4E4F534A
MAX_MODEL_BYTES = 500 * 1024 * 1024


@dataclass(frozen=True)
class ImageMetadata:
    format: str
    width: int
    height: int
    has_alpha: bool


@dataclass(frozen=True)
class VideoMetadata:
    duration_seconds: float
    fps: float
    width: int
    height: int
    codec: str
    pixel_format: str


def inspect_image(data: bytes, content_type: str) -> ImageMetadata:
    if len(data) < 16:
        raise ValueError("Character image is empty or truncated")
    normalized_type = content_type.split(";", 1)[0].lower()
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        if len(data) < 26 or data[12:16] != b"IHDR":
            raise ValueError("Character PNG is missing its IHDR header")
        width, height = struct.unpack(">II", data[16:24])
        color_type = data[25]
        return ImageMetadata("png", width, height, color_type in {4, 6} or b"tRNS" in data)
    if data.startswith(b"\xff\xd8"):
        offset = 2
        while offset + 9 < len(data):
            if data[offset] != 0xFF:
                offset += 1
                continue
            marker = data[offset + 1]
            offset += 2
            if marker in {0xD8, 0xD9}:
                continue
            if offset + 2 > len(data):
                break
            length = struct.unpack(">H", data[offset:offset + 2])[0]
            if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF} and offset + 7 < len(data):
                height, width = struct.unpack(">HH", data[offset + 3:offset + 7])
                return ImageMetadata("jpeg", width, height, False)
            if length < 2:
                break
            offset += length
        raise ValueError("Character JPEG dimensions could not be read")
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        chunk = data[12:16]
        if chunk == b"VP8X" and len(data) >= 30:
            flags = data[20]
            width = 1 + int.from_bytes(data[24:27], "little")
            height = 1 + int.from_bytes(data[27:30], "little")
            return ImageMetadata("webp", width, height, bool(flags & 0x10))
        if chunk == b"VP8 " and len(data) >= 30:
            width, height = struct.unpack("<HH", data[26:30])
            return ImageMetadata("webp", width & 0x3FFF, height & 0x3FFF, False)
        if chunk == b"VP8L" and len(data) >= 25:
            bits = int.from_bytes(data[21:25], "little")
            width = (bits & 0x3FFF) + 1
            height = ((bits >> 14) & 0x3FFF) + 1
            return ImageMetadata("webp", width, height, True)
        raise ValueError("Character WebP dimensions could not be read")
    raise ValueError(
        f"Unsupported character image format ({normalized_type or 'unknown'}); use PNG, JPEG, or WebP"
    )


def inspect_video(data: bytes, content_type: str) -> VideoMetadata:
    if not data:
        raise ValueError("Motion source video is empty")
    suffix = {
        "video/mp4": ".mp4", "video/quicktime": ".mov", "video/webm": ".webm",
        "video/x-matroska": ".mkv", "video/mkv": ".mkv",
    }.get(content_type.split(";", 1)[0].lower(), ".video")
    with tempfile.TemporaryDirectory(prefix="frameflow-motion-video-") as temporary:
        path = Path(temporary) / f"source{suffix}"
        path.write_bytes(data)
        try:
            completed = subprocess.run(
                ["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
                check=True,
                capture_output=True,
                text=True,
                timeout=90,
            )
        except FileNotFoundError as exc:
            raise RuntimeError("ffprobe is required to validate a motion source video") from exc
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            detail = (getattr(exc, "stderr", "") or str(exc))[-1600:]
            raise ValueError(f"Motion source video could not be read by ffprobe: {detail}") from exc
    try:
        probe = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError("ffprobe returned invalid motion source metadata") from exc
    stream = next((item for item in probe.get("streams") or [] if item.get("codec_type") == "video"), None)
    if not stream:
        raise ValueError("Motion source Artifact has no video stream")
    rate = str(stream.get("avg_frame_rate") or stream.get("r_frame_rate") or "0/1")
    try:
        numerator, denominator = rate.split("/", 1)
        fps = float(numerator) / max(float(denominator), 1e-9)
    except (ValueError, ZeroDivisionError):
        fps = 0.0
    duration = float(stream.get("duration") or (probe.get("format") or {}).get("duration") or 0)
    metadata = VideoMetadata(
        duration_seconds=duration,
        fps=fps,
        width=int(stream.get("width") or 0),
        height=int(stream.get("height") or 0),
        codec=str(stream.get("codec_name") or "unknown"),
        pixel_format=str(stream.get("pix_fmt") or "unknown"),
    )
    if metadata.duration_seconds <= 0 or metadata.fps <= 0 or metadata.width <= 0 or metadata.height <= 0:
        raise ValueError("Motion source video has invalid duration, FPS, or resolution metadata")
    return metadata


def parse_glb(data: bytes) -> dict[str, Any]:
    if not data:
        raise ValueError("3D Artifact is empty")
    if len(data) > MAX_MODEL_BYTES:
        raise ValueError("3D Artifact exceeds the 500 MB worker limit")
    if len(data) < 20 or data[:4] != GLB_MAGIC:
        raise ValueError("3D Artifact is not a binary glTF/GLB file")
    magic, version, declared_length = struct.unpack("<4sII", data[:12])
    if magic != GLB_MAGIC or version != 2:
        raise ValueError("Only binary glTF 2.0 GLB files are supported")
    if declared_length != len(data):
        raise ValueError("GLB header length does not match the Artifact size")
    offset = 12
    document: dict[str, Any] | None = None
    while offset + 8 <= len(data):
        chunk_length, chunk_type = struct.unpack("<II", data[offset:offset + 8])
        offset += 8
        if chunk_length < 0 or offset + chunk_length > len(data):
            raise ValueError("GLB contains a truncated chunk")
        chunk = data[offset:offset + chunk_length]
        offset += chunk_length
        if chunk_type == GLB_JSON_CHUNK and document is None:
            try:
                document = json.loads(chunk.rstrip(b" \t\r\n\x00"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError("GLB JSON chunk is invalid") from exc
    if offset != len(data) or document is None:
        raise ValueError("GLB is missing a valid JSON chunk")
    asset = document.get("asset") or {}
    if str(asset.get("version") or "") != "2.0":
        raise ValueError("GLB JSON asset.version must be 2.0")
    return document


def inspect_glb(data: bytes) -> dict[str, Any]:
    document = parse_glb(data)
    meshes = list(document.get("meshes") or [])
    nodes = list(document.get("nodes") or [])
    accessors = list(document.get("accessors") or [])
    skins = list(document.get("skins") or [])
    materials = list(document.get("materials") or [])
    textures = list(document.get("textures") or [])
    images = list(document.get("images") or [])
    animations = list(document.get("animations") or [])
    vertex_count = 0
    primitive_count = 0
    bounds_min = [math.inf, math.inf, math.inf]
    bounds_max = [-math.inf, -math.inf, -math.inf]
    for mesh in meshes:
        for primitive in mesh.get("primitives") or []:
            primitive_count += 1
            accessor_index = (primitive.get("attributes") or {}).get("POSITION")
            if not isinstance(accessor_index, int) or not 0 <= accessor_index < len(accessors):
                continue
            accessor = accessors[accessor_index]
            vertex_count += int(accessor.get("count") or 0)
            minimum, maximum = accessor.get("min"), accessor.get("max")
            if isinstance(minimum, list) and isinstance(maximum, list) and len(minimum) >= 3 and len(maximum) >= 3:
                bounds_min = [min(bounds_min[index], float(minimum[index])) for index in range(3)]
                bounds_max = [max(bounds_max[index], float(maximum[index])) for index in range(3)]
    joint_indexes = list(dict.fromkeys(
        int(index)
        for skin in skins
        for index in skin.get("joints") or []
        if isinstance(index, int) and 0 <= index < len(nodes)
    ))
    bone_names = [str(nodes[index].get("name") or f"joint_{index}") for index in joint_indexes]
    external_textures = [
        str(image.get("uri")) for image in images
        if image.get("uri") and not str(image.get("uri")).startswith("data:")
    ]
    warnings: list[str] = []
    if not meshes:
        warnings.append("No mesh was found in the GLB.")
    if not skins or not bone_names:
        warnings.append("No humanoid skeleton found.")
    if not materials:
        warnings.append("No material was found; Blender will use a fallback material.")
    if textures and not images:
        warnings.append("Texture entries exist but no image payloads were found.")
    if external_textures:
        warnings.append("Texture dependency is missing from this self-contained GLB: " + ", ".join(external_textures[:5]))
    if primitive_count > 12:
        warnings.append(f"The model has {primitive_count} mesh primitives; inspect disconnected geometry before rigging.")
    bounds = None
    humanoid_proportions = None
    if all(math.isfinite(value) for value in [*bounds_min, *bounds_max]):
        size = [bounds_max[index] - bounds_min[index] for index in range(3)]
        bounds = {"min": bounds_min, "max": bounds_max, "size": size}
        height = size[1]
        width = size[0]
        depth = size[2]
        # T/A-pose arm span can be slightly wider than the character is tall.
        humanoid_proportions = bool(height > 0 and 0.7 <= height / max(width, 1e-6) <= 6.5 and depth <= max(height, width) * 1.5)
        if not humanoid_proportions:
            warnings.append("Bounding-box proportions do not look like a Y-up humanoid; verify orientation and scale.")
    else:
        warnings.append("Mesh accessors do not declare a usable bounding box.")
    return {
        "valid": bool(meshes and vertex_count > 0),
        "warnings": warnings,
        "metadata": {
            "glb_version": 2,
            "mesh_count": len(meshes),
            "primitive_count": primitive_count,
            "vertex_count": vertex_count,
            "material_count": len(materials),
            "texture_count": len(textures),
            "image_count": len(images),
            "external_texture_references": external_textures,
            "skin_count": len(skins),
            "skeleton_exists": bool(bone_names),
            "bone_count": len(bone_names),
            "bone_names": bone_names,
            "animation_count": len(animations),
            "bounding_box": bounds,
            "humanoid_proportions": humanoid_proportions,
            "orientation": "Y-up (glTF contract; heuristic only)",
        },
    }
