from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Quaternion, Vector


def arguments() -> argparse.Namespace:
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--character", required=True)
    parser.add_argument("--motion", required=True)
    parser.add_argument("--bone-map", required=True)
    parser.add_argument("--output-blend", required=True)
    parser.add_argument("--output-glb", required=True)
    parser.add_argument("--root-motion", choices=["on", "off"], default="on")
    parser.add_argument("--scale-mode", choices=["preserve", "hips_height", "none"], default="preserve")
    parser.add_argument("--fps", type=int, default=30)
    return parser.parse_args(values)


def safe_path(value: str, *, must_exist: bool) -> Path:
    path = Path(value).resolve()
    root = Path.cwd().resolve()
    if root != path.parent and root not in path.parents:
        raise ValueError(f"Path escapes the isolated Blender work directory: {path}")
    if must_exist and not path.is_file():
        raise ValueError(f"Required Blender input does not exist: {path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def canonical_to_blender_quaternion(values: list[float]) -> Quaternion:
    source = Quaternion((float(values[3]), float(values[0]), float(values[1]), float(values[2])))
    # Canonical (X right, Y up, Z forward) -> Blender (X right, Y back, Z up).
    conversion = Matrix(((1.0, 0.0, 0.0), (0.0, 0.0, -1.0), (0.0, 1.0, 0.0)))
    return (conversion @ source.to_matrix() @ conversion.inverted()).to_quaternion()


def canonical_to_blender_position(values: list[float], scale: float) -> Vector:
    return Vector((float(values[0]) * scale, -float(values[2]) * scale, float(values[1]) * scale))


def character_height() -> float:
    points = []
    for item in bpy.context.scene.objects:
        if item.type != "MESH":
            continue
        points.extend(item.matrix_world @ Vector(corner) for corner in item.bound_box)
    if not points:
        return 1.7
    return max(point.z for point in points) - min(point.z for point in points)


def main() -> None:
    args = arguments()
    character = safe_path(args.character, must_exist=True)
    motion_path = safe_path(args.motion, must_exist=True)
    map_path = safe_path(args.bone_map, must_exist=True)
    output_blend = safe_path(args.output_blend, must_exist=False)
    output_glb = safe_path(args.output_glb, must_exist=False)
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    bpy.ops.import_scene.gltf(filepath=str(character))
    armatures = [item for item in bpy.context.scene.objects if item.type == "ARMATURE"]
    if not armatures:
        raise ValueError("No humanoid skeleton found in the rigged character GLB")
    armature = max(armatures, key=lambda item: len(item.data.bones))
    motion = json.loads(motion_path.read_text())
    if motion.get("schema_version") != "humanoid.motion.v1" or not motion.get("frames"):
        raise ValueError("Motion input must be a non-empty humanoid.motion.v1 document")
    bone_map = json.loads(map_path.read_text())
    missing = [f"{semantic} -> {target}" for semantic, target in bone_map.items() if target not in armature.pose.bones]
    if missing:
        raise ValueError("Missing required bone mapping: " + ", ".join(missing))
    scene = bpy.context.scene
    scene.render.fps = max(1, min(120, args.fps))
    scene.frame_start = 1
    frame_numbers = [1 + round(float(frame["time"]) * scene.render.fps) for frame in motion["frames"]]
    scene.frame_end = max(frame_numbers)
    initial_location = armature.location.copy()
    scale = 1.0
    if args.scale_mode == "hips_height":
        scale = max(0.01, character_height() / 1.7)
    elif args.scale_mode == "none":
        scale = 0.0
    print(f"FRAMEFLOW Retargeting {len(motion['frames'])} frames on {len(bone_map)} mapped bones", flush=True)
    for source_index, (frame_index, frame) in enumerate(zip(frame_numbers, motion["frames"], strict=True), start=1):
        scene.frame_set(frame_index)
        root = frame["root"]
        if args.root_motion == "on" and scale:
            armature.location = initial_location + canonical_to_blender_position(root["position"], scale)
            armature.keyframe_insert(data_path="location", frame=frame_index, group="root_motion")
        for semantic, target in bone_map.items():
            transform = {"rotation": root["rotation"]} if semantic == "hips" else frame.get("bones", {}).get(semantic)
            if not transform:
                continue
            pose_bone = armature.pose.bones[target]
            pose_bone.rotation_mode = "QUATERNION"
            canonical_rotation = canonical_to_blender_quaternion(transform["rotation"])
            rest_basis = pose_bone.bone.matrix_local.to_quaternion()
            pose_bone.rotation_quaternion = rest_basis.inverted() @ canonical_rotation @ rest_basis
            pose_bone.keyframe_insert(data_path="rotation_quaternion", frame=frame_index, group=semantic)
        if source_index == 1 or source_index == len(motion["frames"]) or source_index % max(1, len(motion["frames"]) // 10) == 0:
            print(f"FRAMEFLOW Retargeting frame {source_index} / {len(motion['frames'])}", flush=True)
    if armature.animation_data and armature.animation_data.action:
        for curve in armature.animation_data.action.fcurves:
            for point in curve.keyframe_points:
                point.interpolation = "LINEAR"
    scene.frame_set(scene.frame_start)
    bpy.ops.wm.save_as_mainfile(filepath=str(output_blend), compress=True)
    bpy.ops.export_scene.gltf(
        filepath=str(output_glb), export_format="GLB", export_animations=True,
        export_force_sampling=True, export_skins=True,
    )
    metadata = {
        "schema_version": "animation.retarget.v1",
        "armature": armature.name,
        "bone_count": len(armature.data.bones),
        "mapped_bones": bone_map,
        "source_frame_count": len(motion["frames"]),
        "frame_count": scene.frame_end - scene.frame_start + 1,
        "fps": scene.render.fps,
        "duration_seconds": (scene.frame_end - scene.frame_start + 1) / scene.render.fps,
        "root_motion": args.root_motion == "on",
        "scale_mode": args.scale_mode,
        "root_scale": scale,
    }
    (output_blend.parent / "retarget-metadata.json").write_text(json.dumps(metadata, sort_keys=True))
    print("FRAMEFLOW Retarget complete", flush=True)


if __name__ == "__main__":
    main()
