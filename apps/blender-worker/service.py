from __future__ import annotations

import argparse
import base64
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Any


MAX_REQUEST_BYTES = int(os.getenv("BLENDER_SERVICE_MAX_REQUEST_BYTES", str(750 * 1024 * 1024)))
BLENDER_EXECUTABLE = os.getenv("BLENDER_EXECUTABLE", "blender")
SCRIPTS = Path("/app/scripts")


def blender_version() -> str:
    completed = subprocess.run(
        [BLENDER_EXECUTABLE, "--version"], check=True, capture_output=True, text=True, timeout=15,
    )
    return next((line.strip() for line in completed.stdout.splitlines() if line.strip()), "Blender unknown")


def run_blender(script: str, arguments: list[str], work: Path, timeout: int) -> list[str]:
    script_path = (SCRIPTS / script).resolve()
    if SCRIPTS.resolve() not in script_path.parents or not script_path.is_file():
        raise RuntimeError(f"Blender service script is missing: {script}")
    command = [
        BLENDER_EXECUTABLE, "--background", "--factory-startup", "--disable-autoexec",
        "--python-exit-code", "1", "--python", str(script_path), "--", *arguments,
    ]
    try:
        completed = subprocess.run(
            command, cwd=work, check=True, capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Blender service exceeded its {timeout} second timeout") from exc
    except subprocess.CalledProcessError as exc:
        detail = "\n".join((exc.stdout or "", exc.stderr or ""))[-6000:]
        raise RuntimeError(f"Blender exited with status code {exc.returncode}: {detail}") from exc
    return [line.strip() for line in (completed.stdout + "\n" + completed.stderr).splitlines() if line.strip()][-200:]


def decode(value: Any, label: str) -> bytes:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be base64 text")
    try:
        return base64.b64decode(value, validate=True)
    except ValueError as exc:
        raise ValueError(f"{label} is not valid base64") from exc


def encode(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def retarget(payload: dict[str, Any]) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="frameflow-blender-retarget-") as temporary:
        work = Path(temporary).resolve()
        character = work / "character.glb"
        motion = work / "motion.json"
        bone_map = work / "bone-map.json"
        output_blend = work / "animation.blend"
        output_glb = work / "animated-character.glb"
        character.write_bytes(decode(payload.get("character_glb"), "character_glb"))
        motion.write_text(json.dumps(payload.get("motion"), sort_keys=True, separators=(",", ":")))
        bone_map.write_text(json.dumps(payload.get("bone_map"), sort_keys=True, separators=(",", ":")))
        config = dict(payload.get("config") or {})
        logs = run_blender("retarget_motion.py", [
            "--character", str(character), "--motion", str(motion), "--bone-map", str(bone_map),
            "--output-blend", str(output_blend), "--output-glb", str(output_glb),
            "--root-motion", "on" if config.get("root_motion", True) else "off",
            "--scale-mode", str(config.get("scale_mode", "preserve")),
            "--fps", str(int(config.get("fps", 30))),
        ], work, int(config.get("timeout_seconds", 900)))
        if not output_blend.is_file() or not output_glb.is_file():
            raise RuntimeError("Blender retarget did not create both animation outputs")
        metadata_path = work / "retarget-metadata.json"
        return {
            "blend": encode(output_blend.read_bytes()),
            "animated_glb": encode(output_glb.read_bytes()),
            "metadata": json.loads(metadata_path.read_text()) if metadata_path.is_file() else {},
            "logs": logs,
        }


def render(payload: dict[str, Any]) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="frameflow-blender-render-") as temporary:
        work = Path(temporary).resolve()
        source = work / "animation.blend"
        output = work / "render.mp4"
        source.write_bytes(decode(payload.get("animation_blend"), "animation_blend"))
        config = dict(payload.get("config") or {})
        logs = run_blender("render_animation.py", [
            "--input", str(source), "--output", str(output),
            "--width", str(int(config["width"])), "--height", str(int(config["height"])),
            "--fps", str(int(config["fps"])), "--render-style", str(config["render_style"]),
            "--camera-preset", str(config["camera_preset"]), "--background", str(config["background"]),
            "--samples", str(int(config["samples"])), "--quality", str(config["quality"]),
        ], work, int(config.get("timeout_seconds", 1800)))
        if not output.is_file():
            raise RuntimeError("Blender render did not create an MP4")
        metadata_path = work / "render-metadata.json"
        return {
            "video": encode(output.read_bytes()),
            "metadata": json.loads(metadata_path.read_text()) if metadata_path.is_file() else {},
            "logs": logs,
        }


class Handler(BaseHTTPRequestHandler):
    server_version = "FrameflowBlender/1"

    def _json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path != "/health":
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        try:
            self._json(HTTPStatus.OK, {"status": "ok", "blender": blender_version()})
        except Exception as exc:
            self._json(HTTPStatus.SERVICE_UNAVAILABLE, {"status": "unavailable", "error": str(exc)})

    def do_POST(self) -> None:
        if self.path not in {"/retarget", "/render"}:
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > MAX_REQUEST_BYTES:
                raise ValueError("Blender request is empty or exceeds the service limit")
            payload = json.loads(self.rfile.read(length))
            result = retarget(payload) if self.path == "/retarget" else render(payload)
            self._json(HTTPStatus.OK, result)
        except (ValueError, RuntimeError, json.JSONDecodeError) as exc:
            self._json(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": str(exc)})
        except Exception as exc:
            self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": f"Blender service failed: {exc}"})

    def log_message(self, format: str, *args: Any) -> None:
        print(f"{self.address_string()} {format % args}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8090)
    args = parser.parse_args()
    print(f"Frameflow Blender worker ready: {blender_version()}", flush=True)
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
