from __future__ import annotations

import base64
import json
import os
import queue
import re
import shutil
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Protocol

import httpx

from .canonical_motion import canonical_motion_bytes
from .validation import MAX_MODEL_BYTES, inspect_glb


BLENDER_RETARGET_REVISION = "blender-retarget.v1"
BLENDER_RENDER_REVISION = "blender-render.v1"
MAX_BLEND_BYTES = 2 * 1024 * 1024 * 1024


@lru_cache(maxsize=8)
def blender_runtime_revision(executable: str | None = None) -> str:
    if os.getenv("BLENDER_EXECUTION_PROVIDER", "local").strip().lower() == "http":
        service_url = os.getenv("BLENDER_SERVICE_URL", "http://blender-worker:8090").rstrip("/")
        try:
            response = httpx.get(f"{service_url}/health", timeout=15)
            response.raise_for_status()
            version = str(response.json().get("blender") or "Blender service unknown")
            return re.sub(r"[^A-Za-z0-9._-]+", "-", version).strip("-").lower()
        except (httpx.HTTPError, ValueError):
            return os.getenv("BLENDER_RUNTIME_REVISION", "blender-service-unavailable")
    selected = executable or os.getenv("BLENDER_EXECUTABLE", "blender")
    resolved = shutil.which(selected) if not Path(selected).is_absolute() else selected
    if not resolved or not Path(resolved).is_file():
        return os.getenv("BLENDER_RUNTIME_REVISION", "blender-unavailable")
    try:
        completed = subprocess.run(
            [str(resolved), "--version"], check=True, capture_output=True, text=True, timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return os.getenv("BLENDER_RUNTIME_REVISION", "blender-version-unknown")
    first_line = next((line.strip() for line in completed.stdout.splitlines() if line.strip()), "Blender unknown")
    return re.sub(r"[^A-Za-z0-9._-]+", "-", first_line).strip("-").lower()


@dataclass(frozen=True)
class BlenderRetargetResult:
    blend: bytes
    animated_glb: bytes
    metadata: dict[str, Any]
    logs: list[str]


@dataclass(frozen=True)
class BlenderRenderResult:
    video: bytes
    metadata: dict[str, Any]
    logs: list[str]


class BlenderExecutionProvider(Protocol):
    revision: str

    def retarget(
        self,
        character_glb: bytes,
        motion: dict[str, Any],
        bone_map: dict[str, str],
        *,
        root_motion: bool,
        scale_mode: str,
        fps: int,
        timeout_seconds: int,
        progress: Callable[[int, str], None] | None = None,
    ) -> BlenderRetargetResult: ...

    def render(
        self,
        animation_blend: bytes,
        *,
        width: int,
        height: int,
        fps: int,
        render_style: str,
        camera_preset: str,
        background: str,
        samples: int,
        quality: str,
        timeout_seconds: int,
        progress: Callable[[int, str], None] | None = None,
    ) -> BlenderRenderResult: ...


class LocalBlenderExecutionProvider:
    revision = "blender-headless-local.v1"

    def __init__(self, executable: str | None = None) -> None:
        self.executable = executable or os.getenv("BLENDER_EXECUTABLE", "blender")
        self.scripts_dir = Path(__file__).parents[1] / "blender" / "scripts"

    def _command(self, script_name: str, arguments: list[str]) -> list[str]:
        executable = shutil.which(self.executable) if not Path(self.executable).is_absolute() else self.executable
        if not executable or not Path(executable).is_file():
            raise RuntimeError(
                "Blender executable was not found. Install Blender on the worker or set BLENDER_EXECUTABLE."
            )
        script = (self.scripts_dir / script_name).resolve()
        if not script.is_file() or self.scripts_dir.resolve() not in script.parents:
            raise RuntimeError(f"Frameflow Blender worker script is missing: {script_name}")
        return [
            str(executable), "--background", "--factory-startup", "--disable-autoexec",
            "--python-exit-code", "1", "--python", str(script), "--", *arguments,
        ]

    @staticmethod
    def _run(
        command: list[str],
        *,
        cwd: Path,
        timeout_seconds: int,
        line_callback: Callable[[str], None] | None = None,
    ) -> list[str]:
        try:
            process = subprocess.Popen(
                command,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except FileNotFoundError as exc:
            raise RuntimeError("Blender worker executable is not installed") from exc
        if process.stdout is None:
            process.kill()
            raise RuntimeError("Blender worker stdout pipe could not be opened")
        messages: queue.Queue[str | None] = queue.Queue()

        def read_output() -> None:
            try:
                for line in process.stdout:
                    messages.put(line.rstrip())
            finally:
                messages.put(None)

        reader = threading.Thread(target=read_output, daemon=True)
        reader.start()
        deadline = time.monotonic() + timeout_seconds
        lines: list[str] = []
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                process.terminate()
                try:
                    process.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    process.kill()
                raise RuntimeError(f"Blender worker exceeded its {timeout_seconds} second timeout")
            try:
                line = messages.get(timeout=min(0.5, remaining))
            except queue.Empty:
                if process.poll() is not None and not reader.is_alive():
                    break
                continue
            if line is None:
                break
            if line.strip():
                lines.append(line.strip())
                if line_callback:
                    try:
                        line_callback(line.strip())
                    except Exception:
                        process.terminate()
                        try:
                            process.wait(timeout=8)
                        except subprocess.TimeoutExpired:
                            process.kill()
                        raise
        return_code = process.wait(timeout=max(1.0, deadline - time.monotonic()))
        if return_code:
            detail = "\n".join(lines)[-6000:]
            raise RuntimeError(f"Blender worker exited with status code {return_code}: {detail}")
        return lines[-200:]

    @staticmethod
    def _read_output(path: Path, *, maximum: int, label: str) -> bytes:
        if not path.is_file():
            raise RuntimeError(f"Blender worker did not create {label}")
        size = path.stat().st_size
        if size <= 0 or size > maximum:
            raise RuntimeError(f"Blender worker created an invalid {label} size: {size} bytes")
        return path.read_bytes()

    def retarget(
        self,
        character_glb: bytes,
        motion: dict[str, Any],
        bone_map: dict[str, str],
        *,
        root_motion: bool,
        scale_mode: str,
        fps: int,
        timeout_seconds: int,
        progress: Callable[[int, str], None] | None = None,
    ) -> BlenderRetargetResult:
        if len(character_glb) > MAX_MODEL_BYTES:
            raise ValueError("Rigged character exceeds the 500 MB Blender input limit")
        inspect_glb(character_glb)
        with tempfile.TemporaryDirectory(prefix="frameflow-retarget-") as temporary:
            work = Path(temporary).resolve()
            character_path = work / "character.glb"
            motion_path = work / "motion.json"
            bone_map_path = work / "bone-map.json"
            blend_path = work / "animation.blend"
            glb_path = work / "animated-character.glb"
            character_path.write_bytes(character_glb)
            motion_path.write_bytes(canonical_motion_bytes(motion))
            bone_map_path.write_text(json.dumps(bone_map, sort_keys=True, separators=(",", ":")))
            if progress:
                progress(15, "Loading rigged character")
            command = self._command("retarget_motion.py", [
                "--character", str(character_path),
                "--motion", str(motion_path),
                "--bone-map", str(bone_map_path),
                "--output-blend", str(blend_path),
                "--output-glb", str(glb_path),
                "--root-motion", "on" if root_motion else "off",
                "--scale-mode", scale_mode,
                "--fps", str(fps),
            ])
            last_progress = 15

            def retarget_progress(line: str) -> None:
                nonlocal last_progress
                match = re.search(r"Retargeting frame (\d+) / (\d+)", line)
                if not match or not progress:
                    return
                current, total = int(match.group(1)), max(1, int(match.group(2)))
                value = min(84, 15 + round(current / total * 69))
                if value > last_progress:
                    last_progress = value
                    progress(value, f"Retargeting frame {current} / {total}")

            logs = self._run(
                command, cwd=work, timeout_seconds=timeout_seconds, line_callback=retarget_progress,
            )
            if progress:
                progress(85, "Baked motion keyframes")
            blend = self._read_output(blend_path, maximum=MAX_BLEND_BYTES, label="animation.blend")
            animated_glb = self._read_output(glb_path, maximum=MAX_MODEL_BYTES, label="animated-character.glb")
            animated_validation = inspect_glb(animated_glb)
            if not animated_validation["valid"] or animated_validation["metadata"]["animation_count"] < 1:
                raise RuntimeError("Blender retarget output does not contain a mesh, rig, and baked animation")
            metadata_path = work / "retarget-metadata.json"
            metadata = json.loads(metadata_path.read_text()) if metadata_path.is_file() else {}
            metadata["animated_glb_validation"] = animated_validation
            return BlenderRetargetResult(blend, animated_glb, metadata, logs)

    def render(
        self,
        animation_blend: bytes,
        *,
        width: int,
        height: int,
        fps: int,
        render_style: str,
        camera_preset: str,
        background: str,
        samples: int,
        quality: str,
        timeout_seconds: int,
        progress: Callable[[int, str], None] | None = None,
    ) -> BlenderRenderResult:
        if not animation_blend or len(animation_blend) > MAX_BLEND_BYTES:
            raise ValueError("Animation .blend Artifact is empty or exceeds the 2 GB worker limit")
        with tempfile.TemporaryDirectory(prefix="frameflow-blender-render-") as temporary:
            work = Path(temporary).resolve()
            blend_path = work / "animation.blend"
            video_path = work / "render.mp4"
            blend_path.write_bytes(animation_blend)
            if progress:
                progress(10, "Preparing camera, lights, and render style")
            command = self._command("render_animation.py", [
                "--input", str(blend_path),
                "--output", str(video_path),
                "--width", str(width), "--height", str(height), "--fps", str(fps),
                "--render-style", render_style,
                "--camera-preset", camera_preset,
                "--background", background,
                "--samples", str(samples),
                "--quality", quality,
            ])
            render_total = 0
            last_progress = 10

            def render_progress(line: str) -> None:
                nonlocal render_total, last_progress
                total_match = re.search(r"Rendering frames \d+ / (\d+)", line)
                if total_match:
                    render_total = max(1, int(total_match.group(1)))
                    return
                frame_match = re.match(r"Fra:(\d+)", line)
                if not frame_match or not render_total or not progress:
                    return
                current = int(frame_match.group(1))
                value = min(90, 10 + round(current / render_total * 80))
                if value >= last_progress + 2:
                    last_progress = value
                    progress(value, f"Rendering frame {current} / {render_total}")

            logs = self._run(
                command, cwd=work, timeout_seconds=timeout_seconds, line_callback=render_progress,
            )
            if progress:
                progress(92, "Encoding Blender render")
            video = self._read_output(video_path, maximum=2 * 1024 * 1024 * 1024, label="render.mp4")
            metadata_path = work / "render-metadata.json"
            metadata = json.loads(metadata_path.read_text()) if metadata_path.is_file() else {}
            return BlenderRenderResult(video, metadata, logs)


class HttpBlenderExecutionProvider:
    revision = "blender-headless-http.v1"

    def __init__(self, service_url: str | None = None) -> None:
        self.service_url = (service_url or os.getenv("BLENDER_SERVICE_URL", "http://blender-worker:8090")).rstrip("/")

    def _post(self, path: str, payload: dict[str, Any], timeout_seconds: int) -> dict[str, Any]:
        try:
            response = httpx.post(
                f"{self.service_url}{path}", json=payload,
                timeout=httpx.Timeout(timeout_seconds + 30, connect=15),
            )
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Blender worker service is unavailable: {exc}") from exc
        if response.status_code >= 400:
            try:
                detail = str(response.json().get("error") or response.text)
            except ValueError:
                detail = response.text
            raise RuntimeError(f"Blender worker service failed ({response.status_code}): {detail[-6000:]}")
        try:
            result = response.json()
        except ValueError as exc:
            raise RuntimeError("Blender worker service returned invalid JSON") from exc
        if not isinstance(result, dict):
            raise RuntimeError("Blender worker service returned an invalid result")
        return result

    @staticmethod
    def _decode(result: dict[str, Any], key: str) -> bytes:
        value = result.get(key)
        if not isinstance(value, str):
            raise RuntimeError(f"Blender worker response is missing {key}")
        try:
            return base64.b64decode(value, validate=True)
        except ValueError as exc:
            raise RuntimeError(f"Blender worker returned invalid {key} bytes") from exc

    def retarget(
        self,
        character_glb: bytes,
        motion: dict[str, Any],
        bone_map: dict[str, str],
        *,
        root_motion: bool,
        scale_mode: str,
        fps: int,
        timeout_seconds: int,
        progress: Callable[[int, str], None] | None = None,
    ) -> BlenderRetargetResult:
        if progress:
            progress(15, "Uploading rig and motion to Blender worker")
        result = self._post("/retarget", {
            "character_glb": base64.b64encode(character_glb).decode("ascii"),
            "motion": motion,
            "bone_map": bone_map,
            "config": {
                "root_motion": root_motion, "scale_mode": scale_mode,
                "fps": fps, "timeout_seconds": timeout_seconds,
            },
        }, timeout_seconds)
        blend = self._decode(result, "blend")
        animated_glb = self._decode(result, "animated_glb")
        animated_validation = inspect_glb(animated_glb)
        if not animated_validation["valid"] or animated_validation["metadata"]["animation_count"] < 1:
            raise RuntimeError("Blender worker output does not contain a mesh, rig, and baked animation")
        metadata = dict(result.get("metadata") or {})
        metadata["animated_glb_validation"] = animated_validation
        if progress:
            progress(90, "Downloaded baked animation from Blender worker")
        return BlenderRetargetResult(blend, animated_glb, metadata, [str(line) for line in result.get("logs") or []])

    def render(
        self,
        animation_blend: bytes,
        *,
        width: int,
        height: int,
        fps: int,
        render_style: str,
        camera_preset: str,
        background: str,
        samples: int,
        quality: str,
        timeout_seconds: int,
        progress: Callable[[int, str], None] | None = None,
    ) -> BlenderRenderResult:
        if progress:
            progress(15, "Uploading animation to Blender render worker")
        result = self._post("/render", {
            "animation_blend": base64.b64encode(animation_blend).decode("ascii"),
            "config": {
                "width": width, "height": height, "fps": fps,
                "render_style": render_style, "camera_preset": camera_preset,
                "background": background, "samples": samples, "quality": quality,
                "timeout_seconds": timeout_seconds,
            },
        }, timeout_seconds)
        if progress:
            progress(92, "Downloaded encoded video from Blender worker")
        return BlenderRenderResult(
            self._decode(result, "video"),
            dict(result.get("metadata") or {}),
            [str(line) for line in result.get("logs") or []],
        )


def get_blender_execution_provider() -> BlenderExecutionProvider:
    # The protocol boundary intentionally allows a remote/Docker provider to be
    # injected later without changing any Node manifest or Artifact contract.
    provider = os.getenv("BLENDER_EXECUTION_PROVIDER", "local").strip().lower()
    if provider == "local":
        return LocalBlenderExecutionProvider()
    if provider == "http":
        return HttpBlenderExecutionProvider()
    raise RuntimeError(f"Blender execution provider is not configured: {provider}")
