from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bpy


def main() -> None:
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args(values)
    root = Path.cwd().resolve()
    source, output, report = (Path(value).resolve() for value in (args.input, args.output, args.report))
    if any(root != path.parent and root not in path.parents for path in (source, output, report)):
        raise ValueError("Model validation path escapes the isolated work directory")
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    bpy.ops.import_scene.gltf(filepath=str(source))
    meshes = [item for item in bpy.context.scene.objects if item.type == "MESH"]
    armatures = [item for item in bpy.context.scene.objects if item.type == "ARMATURE"]
    if not meshes:
        raise ValueError("GLB could not be imported by Blender: no mesh found")
    bpy.ops.export_scene.gltf(filepath=str(output), export_format="GLB", export_animations=True, export_skins=True)
    report.write_text(json.dumps({
        "mesh_count": len(meshes),
        "material_count": len(bpy.data.materials),
        "image_count": len(bpy.data.images),
        "armature_count": len(armatures),
        "bone_count": sum(len(item.data.bones) for item in armatures),
        "animation_count": len(bpy.data.actions),
    }, sort_keys=True))
    print("FRAMEFLOW GLB round trip complete", flush=True)


if __name__ == "__main__":
    main()
