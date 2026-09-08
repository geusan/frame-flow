from __future__ import annotations

import argparse
import sys
from pathlib import Path

import bpy
from mathutils import Vector


BONES = {
    "hips": ((0.0, 0.0, 0.9), (0.0, 0.0, 1.08), None),
    "spine": ((0.0, 0.0, 1.08), (0.0, 0.0, 1.32), "hips"),
    "chest": ((0.0, 0.0, 1.32), (0.0, 0.0, 1.52), "spine"),
    "neck": ((0.0, 0.0, 1.52), (0.0, 0.0, 1.64), "chest"),
    "head": ((0.0, 0.0, 1.64), (0.0, 0.0, 1.88), "neck"),
    "leftShoulder": ((0.0, 0.0, 1.48), (0.18, 0.0, 1.48), "chest"),
    "leftUpperArm": ((0.18, 0.0, 1.48), (0.53, 0.0, 1.45), "leftShoulder"),
    "leftLowerArm": ((0.53, 0.0, 1.45), (0.84, 0.0, 1.42), "leftUpperArm"),
    "leftHand": ((0.84, 0.0, 1.42), (1.00, 0.0, 1.42), "leftLowerArm"),
    "rightShoulder": ((0.0, 0.0, 1.48), (-0.18, 0.0, 1.48), "chest"),
    "rightUpperArm": ((-0.18, 0.0, 1.48), (-0.53, 0.0, 1.45), "rightShoulder"),
    "rightLowerArm": ((-0.53, 0.0, 1.45), (-0.84, 0.0, 1.42), "rightUpperArm"),
    "rightHand": ((-0.84, 0.0, 1.42), (-1.00, 0.0, 1.42), "rightLowerArm"),
    "leftUpperLeg": ((0.13, 0.0, 0.92), (0.13, 0.0, 0.52), "hips"),
    "leftLowerLeg": ((0.13, 0.0, 0.52), (0.13, 0.0, 0.12), "leftUpperLeg"),
    "leftFoot": ((0.13, 0.0, 0.12), (0.13, -0.20, 0.05), "leftLowerLeg"),
    "rightUpperLeg": ((-0.13, 0.0, 0.92), (-0.13, 0.0, 0.52), "hips"),
    "rightLowerLeg": ((-0.13, 0.0, 0.52), (-0.13, 0.0, 0.12), "rightUpperLeg"),
    "rightFoot": ((-0.13, 0.0, 0.12), (-0.13, -0.20, 0.05), "rightLowerLeg"),
}


def cuboid(head: Vector, tail: Vector, radius: float) -> tuple[list[Vector], list[tuple[int, int, int, int]]]:
    direction = tail - head
    length = direction.length
    rotation = Vector((0.0, 1.0, 0.0)).rotation_difference(direction.normalized()).to_matrix()
    center = (head + tail) / 2.0
    local = [
        Vector((x * radius, y * length / 2.0, z * radius))
        for x, y, z in (
            (-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1),
            (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1),
        )
    ]
    vertices = [center + rotation @ value for value in local]
    faces = [(0, 1, 2, 3), (4, 7, 6, 5), (0, 4, 5, 1), (1, 5, 6, 2), (2, 6, 7, 3), (4, 0, 3, 7)]
    return vertices, faces


def main() -> None:
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args(values)
    output = Path(args.output).resolve()
    root = Path.cwd().resolve()
    if root != output.parent and root not in output.parents:
        raise ValueError("Fixture output escapes the work directory")
    output.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)

    armature_data = bpy.data.armatures.new("FrameflowHumanoid")
    armature = bpy.data.objects.new("FrameflowHumanoid", armature_data)
    bpy.context.collection.objects.link(armature)
    bpy.context.view_layer.objects.active = armature
    armature.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    edit_bones = {}
    for name, (head, tail, parent) in BONES.items():
        bone = armature_data.edit_bones.new(name)
        bone.head = head
        bone.tail = tail
        edit_bones[name] = bone
        if parent:
            bone.parent = edit_bones[parent]
    bpy.ops.object.mode_set(mode="OBJECT")

    vertices = []
    faces = []
    vertex_ranges = {}
    for name, (head, tail, _) in BONES.items():
        radius = 0.09 if name in {"hips", "spine", "chest", "head"} else 0.055
        part_vertices, part_faces = cuboid(Vector(head), Vector(tail), radius)
        offset = len(vertices)
        vertices.extend(part_vertices)
        faces.extend(tuple(offset + index for index in face) for face in part_faces)
        vertex_ranges[name] = range(offset, offset + len(part_vertices))
    mesh_data = bpy.data.meshes.new("FixtureCharacterMesh")
    mesh_data.from_pydata(vertices, [], faces)
    mesh_data.update()
    mesh = bpy.data.objects.new("FixtureCharacter", mesh_data)
    bpy.context.collection.objects.link(mesh)
    mesh.parent = armature
    modifier = mesh.modifiers.new("Frameflow Armature", "ARMATURE")
    modifier.object = armature
    for name, indexes in vertex_ranges.items():
        group = mesh.vertex_groups.new(name=name)
        group.add(list(indexes), 1.0, "REPLACE")

    material = bpy.data.materials.new("Fixture Toon")
    material.diffuse_color = (0.22, 0.55, 0.92, 1.0)
    material.use_nodes = True
    node = material.node_tree.nodes.get("Principled BSDF") if material.node_tree else None
    if node:
        node.inputs["Base Color"].default_value = material.diffuse_color
        node.inputs["Roughness"].default_value = 0.78
    mesh.data.materials.append(material)
    bpy.ops.export_scene.gltf(filepath=str(output), export_format="GLB", export_skins=True, export_animations=True)
    print(f"FRAMEFLOW Fixture character created: {output.name}", flush=True)


if __name__ == "__main__":
    main()
