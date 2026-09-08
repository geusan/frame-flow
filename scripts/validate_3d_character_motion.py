#!/usr/bin/env python3
"""Run the smallest real rig -> retarget -> Blender MP4 validation in Docker."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
from pathlib import Path


IMAGE = "frameflow-blender:validation"


def run(args: list[str], *, cwd: Path, timeout: int) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(args, cwd=cwd, text=True, capture_output=True, timeout=timeout, check=False)
    if completed.returncode:
        raise RuntimeError(
            f"Command failed ({completed.returncode}): {' '.join(args[:4])}\n"
            f"{completed.stdout[-4000:]}\n{completed.stderr[-4000:]}"
        )
    return completed


def docker_blender_command(output: Path, script: str, arguments: list[str]) -> list[str]:
    return [
        "docker", "run", "--rm", "--network", "none",
        "--volume", f"{output.resolve()}:/work",
        IMAGE,
        "blender", "--background", "--factory-startup", "--disable-autoexec",
        "--python-exit-code", "1", "--python", f"/opt/frameflow/blender/scripts/{script}",
        "--", *arguments,
    ]


def local_blender_command(root: Path, executable: Path, script: str, arguments: list[str]) -> list[str]:
    return [
        str(executable), "--background", "--factory-startup", "--disable-autoexec",
        "--python-exit-code", "1", "--python", str(root / "apps/api/app/blender/scripts" / script),
        "--", *arguments,
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--blender-executable", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    blender_executable = args.blender_executable.resolve() if args.blender_executable else None
    if blender_executable and not blender_executable.is_file():
        raise RuntimeError(f"Blender executable does not exist: {blender_executable}")
    if blender_executable is None and not shutil.which("docker"):
        raise RuntimeError("Docker or --blender-executable is required")
    output = args.output.resolve() if args.output else Path(tempfile.mkdtemp(prefix="frameflow-3d-spike-"))
    output.mkdir(parents=True, exist_ok=True)
    motion_target = output / "known-motion.json"
    shutil.copyfile(root / "examples/3d-character-dance/known-motion.json", motion_target)
    shutil.copyfile(root / "apps/api/app/blender/scripts/semantic-bone-map.json", output / "semantic-bone-map.json")
    if blender_executable is None and not args.skip_build:
        built = run(
            ["docker", "build", "--file", "apps/blender-worker/Dockerfile", "--tag", IMAGE, "."],
            cwd=root,
            timeout=1800,
        )
        print(built.stdout[-1200:])

    prefix = "/work" if blender_executable is None else str(output)
    command = (
        (lambda script, values: docker_blender_command(output, script, values))
        if blender_executable is None
        else (lambda script, values: local_blender_command(root, blender_executable, script, values))
    )
    commands = [
        command("create_fixture_character.py", ["--output", f"{prefix}/fixture-character.glb"]),
        command("validate_model.py", [
            "--input", f"{prefix}/fixture-character.glb", "--output", f"{prefix}/roundtrip-character.glb",
            "--report", f"{prefix}/glb-roundtrip-report.json",
        ]),
        command("retarget_motion.py", [
            "--character", f"{prefix}/roundtrip-character.glb", "--motion", f"{prefix}/known-motion.json",
            "--bone-map", f"{prefix}/semantic-bone-map.json",
            "--output-blend", f"{prefix}/animation.blend", "--output-glb", f"{prefix}/animated-character.glb",
            "--root-motion", "on", "--scale-mode", "preserve", "--fps", "24",
        ]),
        command("render_animation.py", [
            "--input", f"{prefix}/animation.blend", "--output", f"{prefix}/preview.mp4",
            "--width", "360", "--height", "640", "--fps", "24", "--render-style", "toon",
            "--camera-preset", "full_body", "--background", "#181A20", "--samples", "8", "--quality", "preview",
        ]),
    ]
    for command in commands:
        completed = run(command, cwd=root, timeout=1200)
        progress = [line for line in completed.stdout.splitlines() if "FRAMEFLOW" in line]
        print("\n".join(progress[-20:]))

    probe = run(
        ["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(output / "preview.mp4")],
        cwd=root,
        timeout=60,
    )
    media = json.loads(probe.stdout)
    video = next((stream for stream in media["streams"] if stream.get("codec_type") == "video"), None)
    if not video or video.get("codec_name") != "h264" or int(video.get("width") or 0) != 360 or int(video.get("height") or 0) != 640:
        raise RuntimeError(f"Rendered preview does not satisfy the H.264 360x640 contract: {video}")
    roundtrip = json.loads((output / "glb-roundtrip-report.json").read_text())
    retarget = json.loads((output / "retarget-metadata.json").read_text())
    if roundtrip["mesh_count"] < 1 or roundtrip["armature_count"] < 1 or roundtrip["bone_count"] < 17:
        raise RuntimeError(f"GLB round trip lost the fixture rig: {roundtrip}")
    if retarget["frame_count"] < 24 or len(retarget["mapped_bones"]) < 17:
        raise RuntimeError(f"Retarget did not bake the expected animation: {retarget}")
    summary = {
        "output": str(output),
        "blender_runtime": str(blender_executable) if blender_executable else IMAGE,
        "glb_roundtrip": roundtrip,
        "retarget": retarget,
        "video": {
            "codec": video["codec_name"], "width": video["width"], "height": video["height"],
            "frames": int(video.get("nb_frames") or 0),
            "duration_seconds": float((media.get("format") or {}).get("duration") or 0),
            "size_bytes": (output / "preview.mp4").stat().st_size,
        },
    }
    (output / "validation-summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True))
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
