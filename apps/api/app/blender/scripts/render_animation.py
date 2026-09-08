from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector


def arguments() -> argparse.Namespace:
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--width", type=int, required=True)
    parser.add_argument("--height", type=int, required=True)
    parser.add_argument("--fps", type=int, required=True)
    parser.add_argument("--render-style", choices=["realistic", "toon", "flat"], required=True)
    parser.add_argument("--camera-preset", choices=["full_body", "portrait"], required=True)
    parser.add_argument("--background", required=True)
    parser.add_argument("--samples", type=int, required=True)
    parser.add_argument("--quality", choices=["preview", "final"], required=True)
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


def color(value: str) -> tuple[float, float, float, float]:
    if len(value) != 7 or not value.startswith("#"):
        raise ValueError("Blender render background must be a #RRGGBB color")
    return tuple(int(value[index:index + 2], 16) / 255.0 for index in (1, 3, 5)) + (1.0,)


def look_at(item: bpy.types.Object, target: Vector) -> None:
    item.rotation_euler = (target - item.location).to_track_quat("-Z", "Y").to_euler()


def scene_bounds() -> tuple[Vector, Vector]:
    points = [
        item.matrix_world @ Vector(corner)
        for item in bpy.context.scene.objects if item.type == "MESH" and not item.hide_render
        for corner in item.bound_box
    ]
    if not points:
        return Vector((-0.5, -0.5, 0.0)), Vector((0.5, 0.5, 1.8))
    return (
        Vector(tuple(min(point[index] for point in points) for index in range(3))),
        Vector(tuple(max(point[index] for point in points) for index in range(3))),
    )


def apply_style(style: str) -> None:
    if style == "realistic":
        return
    for material in bpy.data.materials:
        material.use_nodes = True
        node = material.node_tree.nodes.get("Principled BSDF") if material.node_tree else None
        if node:
            if "Roughness" in node.inputs:
                node.inputs["Roughness"].default_value = 0.8 if style == "toon" else 1.0
            if "Specular IOR Level" in node.inputs:
                node.inputs["Specular IOR Level"].default_value = 0.12 if style == "toon" else 0.0
            elif "Specular" in node.inputs:
                node.inputs["Specular"].default_value = 0.12 if style == "toon" else 0.0
        if style == "flat":
            material.diffuse_color = tuple(min(1.0, component * 1.08) for component in material.diffuse_color[:3]) + (material.diffuse_color[3],)


def configure_camera(preset: str) -> None:
    minimum, maximum = scene_bounds()
    center = (minimum + maximum) / 2.0
    size = maximum - minimum
    camera_data = bpy.data.cameras.new("Frameflow Camera")
    camera = bpy.data.objects.new("Frameflow Camera", camera_data)
    bpy.context.scene.collection.objects.link(camera)
    height = max(size.z, 1.0)
    focus_z = center.z + (height * 0.18 if preset == "portrait" else 0.0)
    target = Vector((center.x, center.y, focus_z))
    distance = max(height * (1.35 if preset == "portrait" else 2.15), size.x * 2.4, 3.0)
    camera.location = Vector((center.x, minimum.y - distance, focus_z + height * 0.08))
    camera_data.lens = 58 if preset == "portrait" else 48
    look_at(camera, target)
    bpy.context.scene.camera = camera


def configure_lights() -> None:
    minimum, maximum = scene_bounds()
    center = (minimum + maximum) / 2.0
    height = max(maximum.z - minimum.z, 1.0)
    for name, location, energy, size in (
        ("Key", (center.x - height, center.y - height, center.z + height), 900, height * 1.4),
        ("Fill", (center.x + height, center.y - height * 0.4, center.z + height * 0.3), 500, height),
        ("Rim", (center.x, center.y + height, center.z + height), 700, height),
    ):
        light_data = bpy.data.lights.new(name, "AREA")
        light_data.energy = energy
        light_data.shape = "DISK"
        light_data.size = max(size, 0.5)
        light = bpy.data.objects.new(name, light_data)
        bpy.context.scene.collection.objects.link(light)
        light.location = location
        look_at(light, center)


def main() -> None:
    args = arguments()
    source = safe_path(args.input, must_exist=True)
    output = safe_path(args.output, must_exist=False)
    bpy.ops.wm.open_mainfile(filepath=str(source), load_ui=False)
    scene = bpy.context.scene
    scene.render.resolution_x = max(64, min(4096, args.width))
    scene.render.resolution_y = max(64, min(4096, args.height))
    scene.render.resolution_percentage = 100
    scene.render.fps = max(1, min(120, args.fps))
    if args.quality == "preview":
        scene.frame_end = min(scene.frame_end, scene.frame_start + 89)
    try:
        scene.render.engine = "BLENDER_EEVEE_NEXT"
    except TypeError:
        scene.render.engine = "BLENDER_EEVEE"
    if hasattr(scene, "eevee") and hasattr(scene.eevee, "taa_render_samples"):
        scene.eevee.taa_render_samples = max(1, min(256, args.samples))
    scene.world.color = color(args.background)[:3]
    if scene.world.use_nodes and scene.world.node_tree:
        background = scene.world.node_tree.nodes.get("Background")
        if background:
            background.inputs["Color"].default_value = color(args.background)
            background.inputs["Strength"].default_value = 0.45
    apply_style(args.render_style)
    configure_camera(args.camera_preset)
    configure_lights()
    scene.render.image_settings.file_format = "FFMPEG"
    scene.render.ffmpeg.format = "MPEG4"
    scene.render.ffmpeg.codec = "H264"
    scene.render.ffmpeg.constant_rate_factor = "MEDIUM" if args.quality == "final" else "LOW"
    scene.render.ffmpeg.ffmpeg_preset = "GOOD"
    scene.render.filepath = str(output)
    print(f"FRAMEFLOW Rendering frames {scene.frame_start} / {scene.frame_end}", flush=True)
    bpy.ops.render.render(animation=True)
    if not output.exists():
        candidate = Path(str(output) + ".mp4")
        if candidate.exists():
            candidate.replace(output)
    if not output.exists():
        raise RuntimeError("Blender render completed without producing an MP4")
    metadata = {
        "schema_version": "blender.render.v1",
        "width": scene.render.resolution_x,
        "height": scene.render.resolution_y,
        "fps": scene.render.fps,
        "frame_start": scene.frame_start,
        "frame_end": scene.frame_end,
        "frame_count": scene.frame_end - scene.frame_start + 1,
        "duration_seconds": (scene.frame_end - scene.frame_start + 1) / scene.render.fps,
        "render_style": args.render_style,
        "camera_preset": args.camera_preset,
        "quality": args.quality,
        "engine": scene.render.engine,
    }
    (output.parent / "render-metadata.json").write_text(json.dumps(metadata, sort_keys=True))
    print("FRAMEFLOW Render complete", flush=True)


if __name__ == "__main__":
    main()
