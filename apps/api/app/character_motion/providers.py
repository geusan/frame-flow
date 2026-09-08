from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Any, Callable, Protocol

from ..motion_extraction import extract_holistic_motion
from .bone_maps import resolve_bone_map
from .canonical_motion import validate_canonical_motion
from .mediapipe_adapter import MediaPipeMotionAdapter
from .tripo import TRIPO_API_REVISION, TripoClient, TripoUpload
from .validation import inspect_glb


@dataclass(frozen=True)
class ImageTo3DView:
    role: str
    data: bytes
    content_type: str
    filename: str


@dataclass(frozen=True)
class ImageTo3DInput:
    image: bytes
    image_content_type: str
    quality: str
    seed: int
    override_glb: bytes | None = None
    views: tuple[ImageTo3DView, ...] = ()
    model_id: str = "P1-20260311"
    face_limit: int = 20_000
    texture: bool = True
    pbr: bool = True
    texture_quality: str = "detailed"
    export_uv: bool = True
    smart_low_poly: bool = True
    timeout_seconds: int = 1200
    resume_task_id: str | None = None
    task_callback: Callable[[str, str], None] | None = None
    progress_callback: Callable[[int, str], None] | None = None


@dataclass(frozen=True)
class ImageTo3DResult:
    glb: bytes
    provider: str
    provider_revision: str
    provider_request_id: str
    metadata: dict[str, Any]


class ImageTo3DProvider(Protocol):
    name: str
    revision: str

    def generate(self, input: ImageTo3DInput) -> ImageTo3DResult: ...


class ManualImageTo3DProvider:
    name = "manual"
    revision = "image-to-3d-manual.v1"

    def generate(self, input: ImageTo3DInput) -> ImageTo3DResult:
        if not input.override_glb:
            raise ValueError(
                "Image to 3D manual provider requires manual_3d_artifact_id pointing to an uploaded GLB"
            )
        validation = inspect_glb(input.override_glb)
        if not validation["valid"]:
            raise ValueError("Manual Image to 3D GLB does not contain a usable mesh")
        return ImageTo3DResult(
            glb=input.override_glb,
            provider=self.name,
            provider_revision=self.revision,
            provider_request_id="manual-override",
            metadata={"quality": input.quality, "seed": input.seed, "validation": validation},
        )


class TripoImageTo3DProvider:
    name = "tripo"
    revision = TRIPO_API_REVISION

    def __init__(self, client: TripoClient | None = None) -> None:
        self.client = client

    def generate(self, input: ImageTo3DInput) -> ImageTo3DResult:
        client = self.client or TripoClient()
        try:
            generated = client.generate_multiview(
                tuple(
                    TripoUpload(view.role, view.data, view.content_type, view.filename)
                    for view in input.views
                ),
                model=input.model_id,
                face_limit=input.face_limit,
                texture=input.texture,
                pbr=input.pbr,
                texture_quality=input.texture_quality,
                export_uv=input.export_uv,
                smart_low_poly=input.smart_low_poly,
                seed=input.seed,
                timeout_seconds=input.timeout_seconds,
                resume_task_id=input.resume_task_id,
                on_task=input.task_callback,
                progress=input.progress_callback,
            )
        finally:
            if self.client is None:
                client.close()
        return ImageTo3DResult(
            glb=generated.data,
            provider=self.name,
            provider_revision=self.revision,
            provider_request_id=f"tripo:generate:{generated.task.task_id}",
            metadata={
                **generated.metadata,
                "task_id": generated.task.task_id,
                "task_type": generated.task.task_type,
            },
        )


@dataclass(frozen=True)
class AutoRigInput:
    glb: bytes
    rig_profile: str
    override_glb: bytes | None = None
    model_id: str = "v1.0-20240301"
    rig_type: str = "biped"
    run_rig_check: bool = True
    timeout_seconds: int = 1200
    resume_stage: str | None = None
    resume_task_id: str | None = None
    task_callback: Callable[[str, str], None] | None = None
    progress_callback: Callable[[int, str], None] | None = None


@dataclass(frozen=True)
class AutoRigResult:
    glb: bytes
    provider: str
    provider_revision: str
    provider_request_id: str
    skeleton_metadata: dict[str, Any]


class AutoRigProvider(Protocol):
    name: str
    revision: str

    def rig(self, input: AutoRigInput) -> AutoRigResult: ...


class PassthroughRigProvider:
    name = "passthrough"
    revision = "rig-passthrough.v1"

    def rig(self, input: AutoRigInput) -> AutoRigResult:
        data = input.override_glb or input.glb
        validation = inspect_glb(data)
        skeleton = validation["metadata"]
        if not skeleton.get("skeleton_exists"):
            raise ValueError(
                "No humanoid skeleton found. Supply manual_rigged_artifact_id or configure a real Auto Rig provider."
            )
        return AutoRigResult(
            glb=data,
            provider=self.name,
            provider_revision=self.revision,
            provider_request_id="manual-rig" if input.override_glb else "already-rigged",
            skeleton_metadata={
                "rig_profile": input.rig_profile,
                "bone_count": skeleton.get("bone_count"),
                "bone_names": skeleton.get("bone_names"),
                "skin_count": skeleton.get("skin_count"),
            },
        )


class TripoAutoRigProvider:
    name = "tripo"
    revision = TRIPO_API_REVISION

    def __init__(self, client: TripoClient | None = None) -> None:
        self.client = client

    def rig(self, input: AutoRigInput) -> AutoRigResult:
        client = self.client or TripoClient()
        try:
            generated = client.auto_rig(
                input.glb,
                model=input.model_id,
                rig_type=input.rig_type,
                spec=input.rig_profile,
                timeout_seconds=input.timeout_seconds,
                run_rig_check=input.run_rig_check,
                resume_stage=input.resume_stage,
                resume_task_id=input.resume_task_id,
                on_task=input.task_callback,
                progress=input.progress_callback,
            )
        finally:
            if self.client is None:
                client.close()
        validation = inspect_glb(generated.data)
        skeleton = validation["metadata"]
        if not validation["valid"] or not skeleton.get("skeleton_exists"):
            raise ValueError("Tripo Auto Rig returned a GLB without a usable humanoid skeleton")
        expected = set(resolve_bone_map(input.rig_profile).values())
        available = set(str(value) for value in skeleton.get("bone_names") or [])
        missing = sorted(expected - available)
        if missing:
            raise ValueError(
                "Tripo Auto Rig GLB is missing required Mixamo bones: " + ", ".join(missing[:8])
            )
        return AutoRigResult(
            glb=generated.data,
            provider=self.name,
            provider_revision=self.revision,
            provider_request_id=f"tripo:rig:{generated.task.task_id}",
            skeleton_metadata={
                "rig_profile": input.rig_profile,
                "rig_type": input.rig_type,
                "bone_count": skeleton.get("bone_count"),
                "bone_names": skeleton.get("bone_names"),
                "skin_count": skeleton.get("skin_count"),
                "task_id": generated.task.task_id,
                **generated.metadata,
            },
        )


@dataclass(frozen=True)
class MotionExtractionInput:
    video: bytes
    video_content_type: str
    fps: float
    max_width: int
    confidence_threshold: float
    include_hands: bool
    include_face: bool
    source_artifact_id: str


@dataclass(frozen=True)
class MotionExtractionResult:
    motion: dict[str, Any]
    provider: str
    provider_revision: str
    provider_request_id: str
    metadata: dict[str, Any]


class MotionExtractionProvider(Protocol):
    name: str
    revision: str

    def extract(self, input: MotionExtractionInput) -> MotionExtractionResult: ...


class MediaPipeMotionProvider:
    name = "mediapipe"
    revision = "mediapipe-holistic-canonical.v1"

    def __init__(self, adapter: MediaPipeMotionAdapter | None = None) -> None:
        self.adapter = adapter or MediaPipeMotionAdapter()

    def extract(self, input: MotionExtractionInput) -> MotionExtractionResult:
        if os.getenv("MOTION_EXTRACTION_EXECUTION_MODE", "local").strip().lower() == "docker":
            return self._extract_in_docker(input)
        track = extract_holistic_motion(
            input.video,
            input.video_content_type,
            sample_fps=input.fps,
            max_width=input.max_width,
            min_confidence=input.confidence_threshold,
            output_face_blendshapes=input.include_face,
        )
        motion = self.adapter.convert(
            track,
            source_artifact_id=input.source_artifact_id,
            include_hands=input.include_hands,
            include_face=input.include_face,
        )
        validate_canonical_motion(motion)
        return MotionExtractionResult(
            motion=motion,
            provider=self.name,
            provider_revision=self.revision,
            provider_request_id=f"mediapipe-{input.source_artifact_id}",
            metadata={
                "landmark_frame_count": (track.get("summary") or {}).get("frame_count", 0),
                "coverage": (track.get("summary") or {}).get("coverage") or {},
                "invalid_frame_ratio": (motion.get("metadata") or {}).get("invalid_frame_ratio", 0),
            },
        )

    def _extract_in_docker(self, input: MotionExtractionInput) -> MotionExtractionResult:
        repository = Path(__file__).resolve().parents[4]
        image = os.getenv("MEDIAPIPE_DOCKER_IMAGE", "frame-flow-api:local").strip()
        if not image:
            raise RuntimeError("MEDIAPIPE_DOCKER_IMAGE is required for Docker motion extraction")
        with tempfile.TemporaryDirectory(prefix="frameflow-mediapipe-worker-") as temporary:
            work = Path(temporary).resolve()
            source = work / "source-video"
            output = work / "motion.json"
            source.write_bytes(input.video)
            command = [
                "docker", "run", "--rm", "--network", "bridge",
                "--volume", f"{repository}:/repo:ro",
                "--volume", f"{work}:/work",
                "--volume", "video-canvas_mediapipe_cache:/home/frameflow/.cache/mediapipe",
                "--workdir", "/work",
                "--env", "PYTHONDONTWRITEBYTECODE=1",
                "--env", "PYTHONPATH=/repo/apps/api",
                image, "python", "-m", "app.character_motion.mediapipe_worker",
                "--input", "/work/source-video", "--output", "/work/motion.json",
                "--content-type", input.video_content_type,
                "--fps", str(input.fps), "--max-width", str(input.max_width),
                "--confidence", str(input.confidence_threshold),
                "--source-artifact-id", input.source_artifact_id,
                *(["--include-hands"] if input.include_hands else []),
                *(["--include-face"] if input.include_face else []),
            ]
            try:
                completed = subprocess.run(
                    command, check=True, capture_output=True, text=True, timeout=1800,
                )
            except FileNotFoundError as exc:
                raise RuntimeError("Docker is required for the configured MediaPipe worker") from exc
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError("Docker MediaPipe worker exceeded its 30 minute timeout") from exc
            except subprocess.CalledProcessError as exc:
                detail = "\n".join((exc.stdout or "", exc.stderr or ""))[-6000:]
                raise RuntimeError(f"Docker MediaPipe worker exited with status code {exc.returncode}: {detail}") from exc
            if not output.is_file():
                raise RuntimeError("Docker MediaPipe worker did not create canonical motion output")
            motion = json.loads(output.read_text())
            validate_canonical_motion(motion)
            metadata = dict(motion.get("metadata") or {})
            return MotionExtractionResult(
                motion=motion,
                provider=self.name,
                provider_revision=f"{self.revision}+docker",
                provider_request_id=f"mediapipe-docker-{input.source_artifact_id}",
                metadata={
                    "coverage": metadata.get("coverage") or {},
                    "invalid_frame_ratio": metadata.get("invalid_frame_ratio", 0),
                    "worker_log": next(
                        (line for line in reversed(completed.stdout.splitlines()) if "FRAMEFLOW" in line),
                        "Docker MediaPipe worker completed",
                    ),
                },
            )


IMAGE_TO_3D_PROVIDERS: dict[str, ImageTo3DProvider] = {"manual": ManualImageTo3DProvider()}
AUTO_RIG_PROVIDERS: dict[str, AutoRigProvider] = {
    "passthrough": PassthroughRigProvider(),
    "manual": PassthroughRigProvider(),
}
MOTION_EXTRACTION_PROVIDERS: dict[str, MotionExtractionProvider] = {"mediapipe": MediaPipeMotionProvider()}


def image_to_3d_provider(name: str) -> ImageTo3DProvider:
    if name == "tripo":
        return TripoImageTo3DProvider()
    try:
        return IMAGE_TO_3D_PROVIDERS[name]
    except KeyError as exc:
        raise ValueError(f"Image to 3D provider is not configured: {name}") from exc


def auto_rig_provider(name: str) -> AutoRigProvider:
    if name == "tripo":
        return TripoAutoRigProvider()
    try:
        return AUTO_RIG_PROVIDERS[name]
    except KeyError as exc:
        raise ValueError(f"Auto Rig provider is not configured: {name}") from exc


def motion_extraction_provider(name: str) -> MotionExtractionProvider:
    try:
        return MOTION_EXTRACTION_PROVIDERS[name]
    except KeyError as exc:
        raise ValueError(f"Motion extraction provider is not configured: {name}") from exc
