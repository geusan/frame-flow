from __future__ import annotations

import hashlib
import json
import subprocess
from typing import Any

from ...character_motion.tripo import TRIPO_API_REVISION, TRIPO_VIEW_ORDER, TripoClient, TripoUpload
from ...character_motion.validation import ImageMetadata, inspect_image
from ...storage import artifact_content_url
from ...providers import model_id_for_alias
from ..contracts import NodeExecutionContext, NodeExecutionResult
from .character_motion import (
    TripoImageTo3DExecutor, _find_artifact, _remember_tripo_task,
    _resume_tripo_task, _result, create_artifact,
)


TURNAROUND_SCHEMA = "character.turnaround.v1"


def normalize_view(data: bytes, minimum: int) -> tuple[bytes, ImageMetadata]:
    inspected = inspect_image(data, "image")
    if min(inspected.width, inspected.height) < minimum:
        raise ValueError(f"Turnaround image must be at least {minimum} pixels on each side")
    if max(inspected.width, inspected.height) > 8192:
        raise ValueError("Turnaround image dimensions exceed 8192 pixels")
    # Fully decode the image, including WebP responses, and store lossless PNG
    # for the shared Tripo 3D uploader. A readable header alone is insufficient.
    decoded = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", "pipe:0", "-frames:v", "1", "-f", "image2pipe", "-c:v", "png", "pipe:1"],
        input=data, capture_output=True, timeout=30, check=False,
    )
    if decoded.returncode or not decoded.stdout:
        raise ValueError("Turnaround image could not be decoded")
    return decoded.stdout, inspect_image(decoded.stdout, "image/png")


class CharacterTurnaroundExecutor:
    @staticmethod
    def runtime_revision(definition: Any, resolved_config: dict[str, Any]) -> str:
        del resolved_config
        return f"{definition.execution.revision}+{TRIPO_API_REVISION}+ffmpeg-png.v1"

    def execute(self, context: NodeExecutionContext, config: dict[str, Any], typed_inputs: list[dict[str, Any]]) -> NodeExecutionResult:
        source = _find_artifact(context, typed_inputs, {"Image"}, "3D Turnaround")
        context.report_progress(5, "Checking the single reference image")
        source_png, _ = normalize_view(source.data, int(config["minimum_resolution"]))
        _, resume_id = _resume_tripo_task(context, {"multiview"})
        client = TripoClient()
        try:
            generated = client.generate_multiview_images(
                TripoUpload("reference", source_png, "image/png", "reference.png"),
                timeout_seconds=int(config["timeout_seconds"]), resume_task_id=resume_id,
                on_task=lambda stage, task_id: _remember_tripo_task(context, stage, task_id),
                progress=lambda value, message: context.report_progress(10 + round(value * 0.7), message),
            )
        finally:
            client.close()
        if tuple(view.role for view in generated.views) != TRIPO_VIEW_ORDER:
            raise ValueError("3D Turnaround requires front, left, back, right exactly once")
        # Validate all four files before writing a usable output Artifact.
        normalized = [normalize_view(view.data, int(config["minimum_resolution"])) for view in generated.views]
        if len({hashlib.sha256(data).hexdigest() for data, _ in normalized}) != 4:
            raise ValueError("3D Turnaround returned duplicate images; inspect the provider task before retrying")
        provider_metadata = {
            "provider": "tripo", "provider_revision": TRIPO_API_REVISION,
            "task_id": generated.task.task_id, "task_type": generated.task.task_type,
            "credits_consumed": generated.task.credits_consumed,
            # Tripo does not expose a selectable/pinnable model on this API.
            "exact_model_id": generated.task.raw.get("model") or model_id_for_alias(context.model_alias),
            "model_version_pinned": False,
        }
        common = {
            "experiment_id": context.experiment_id, "request_hash": context.request_hash,
            "execution_mode": context.definition.execution.revision, "immutable": True,
            "source": "character_turnaround", "normalized_config": config,
            "provider_metadata": provider_metadata,
        }
        views, images = [], []
        for role, (data, info) in zip(TRIPO_VIEW_ORDER, normalized, strict=True):
            image = create_artifact(
                context, "Image", schema_id="character.view.v1", input_artifact_ids=[source.id],
                input_artifact_roles={source.id: "source_character_image"},
                metadata={**common, "view_role": role, "width": info.width, "height": info.height},
                content=data, content_type="image/png", filename=f"turnaround-{role}.png",
            )
            views.append({
                "provider_role": role, "artifact_id": image.id, "content_type": "image/png",
                "width": info.width, "height": info.height, "has_alpha": info.has_alpha,
            })
            images.append({"url": artifact_content_url(image.id), "title": role.title(), "artifactId": image.id})
        manifest = {
            "schema_version": TURNAROUND_SCHEMA, "source_image_id": source.id,
            "pose_policy": "preserve_source", "views": views,
        }
        inputs = [source.id, *(view["artifact_id"] for view in views)]
        roles = {source.id: "source_character_image", **{view["artifact_id"]: f"{view['provider_role']}_character_view" for view in views}}
        bundle = create_artifact(
            context, "CharacterTurnaround", schema_id=TURNAROUND_SCHEMA,
            input_artifact_ids=inputs, input_artifact_roles=roles,
            metadata={**common, **manifest, "cover_artifact_id": views[0]["artifact_id"]},
            content=json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode(),
            content_type="application/json", filename="character-turnaround.json",
        )
        context.require_artifact_store().flush()
        return _result(
            context, output={"kind": "image", "title": "3D Turnaround · 4 views", "url": images[0]["url"], "mimeType": "image/png", "images": images, "imageCount": 4},
            artifacts=[bundle], schema_id=TURNAROUND_SCHEMA, input_ids=inputs, roles=roles,
            retryable=False, provider_request_id=f"tripo:multiview:{generated.task.task_id}",
            logs=[f"Generated four views · {generated.task.credits_consumed:g} Tripo credits", "Pose follows the source image. Inspect all views before generating 3D."],
        )


class TurnaroundTo3DExecutor(TripoImageTo3DExecutor):
    reference_artifact_type = "CharacterTurnaround"
    reference_schema = TURNAROUND_SCHEMA

    def validate_reference_manifest(self, manifest: dict[str, Any]) -> None:
        if manifest.get("pose_policy") != "preserve_source" or not manifest.get("source_image_id"):
            raise ValueError("3D Turnaround is missing its source image or pose policy")
        views = manifest.get("views")
        if not isinstance(views, list) or [view.get("provider_role") for view in views if isinstance(view, dict)] != list(TRIPO_VIEW_ORDER):
            raise ValueError("3D Turnaround requires ordered front, left, back, right views")
        if len({view.get("artifact_id") for view in views}) != 4:
            raise ValueError("3D Turnaround requires four distinct image Artifacts")
