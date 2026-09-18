from __future__ import annotations

import json
import os
from typing import Any, Iterable

from ...character_motion.blender import blender_runtime_revision, get_blender_execution_provider
from ...character_motion.bone_maps import resolve_bone_map
from ...character_motion.canonical_motion import canonical_motion_bytes, parse_canonical_motion
from ...character_motion.cleanup import MOTION_CLEANUP_REVISION, cleanup_motion
from ...character_motion.providers import (
    AutoRigInput,
    ImageTo3DInput,
    ImageTo3DView,
    MotionExtractionInput,
    auto_rig_provider,
    image_to_3d_provider,
    motion_extraction_provider,
)
from ...character_motion.tripo import TRIPO_API_REVISION, TRIPO_TASK_ID_PATTERN, TripoProviderError
from ...character_motion.validation import inspect_glb, inspect_image, inspect_video
from ...providers import model_id_for_alias
from ...storage import artifact_content_url
from ..contracts import (
    NodeArtifactContent,
    NodeArtifactRef,
    NodeArtifactWrite,
    NodeExecutionContext,
    NodeExecutionResult,
)


CHARACTER_REFERENCE_REVISION = "character-reference-validation.v1"
IMAGE_TO_3D_REVISION = "image-to-3d-provider.v1"
CHARACTER_3D_VALIDATION_REVISION = "character-3d-validation.v1"
AUTO_RIG_REVISION = "character-auto-rig-provider.v1"
MOTION_VIDEO_REVISION = "motion-video-validation.v1"
CHARACTER_REFERENCE_SET_REVISION = "character-reference-set.v1"
TRIPO_IMAGE_TO_3D_REVISION = "tripo-multiview-image-to-3d.v1"
TRIPO_AUTO_RIG_REVISION = "tripo-auto-rig.v1"
def _artifact_ids(items: Iterable[dict[str, Any]]) -> list[str]:
    return list(dict.fromkeys(
        str(artifact_id)
        for item in items
        for artifact_id in [*(item.get("artifact_ids") or []), *([item.get("artifact_id")] if item.get("artifact_id") else [])]
    ))


def _find_artifact(
    context: NodeExecutionContext,
    typed_inputs: list[dict[str, Any]],
    artifact_types: set[str],
    label: str,
    *,
    explicit_id: str = "",
) -> NodeArtifactContent:
    artifact_store = context.require_artifact_store()
    candidates = [explicit_id] if explicit_id else _artifact_ids(typed_inputs)
    for artifact_id in candidates:
        try:
            artifact = artifact_store.read(artifact_id)
        except ValueError:
            continue
        if artifact.type in artifact_types:
            return artifact
    expected = ", ".join(sorted(artifact_types))
    if explicit_id:
        raise ValueError(f"{label} Artifact {explicit_id} was not found or is not one of: {expected}")
    raise ValueError(f"{label} requires a connected {expected} Artifact")


def _read_artifact(artifact: NodeArtifactContent) -> tuple[bytes, str]:
    return artifact.data, artifact.content_type


def _remember_tripo_task(context: NodeExecutionContext, stage: str, task_id: str) -> None:
    context.require_character_motion_runtime().remember_task(
        context.request_hash,
        context.experiment_id,
        stage,
        task_id,
    )


def _resume_tripo_task(
    context: NodeExecutionContext,
    allowed_stages: set[str],
) -> tuple[str | None, str | None]:
    return context.require_character_motion_runtime().resume_task(
        context.request_hash,
        context.experiment_id,
        allowed_stages,
    )


def create_artifact(
    context: NodeExecutionContext,
    artifact_type: str,
    **kwargs: Any,
) -> NodeArtifactRef:
    return context.require_artifact_store().create(
        NodeArtifactWrite(artifact_type=artifact_type, **kwargs)
    )


def _json_output(title: str, schema_version: str, payload: dict[str, Any]) -> dict[str, object]:
    return {
        "kind": "json",
        "title": title,
        "text": json.dumps({"schema_version": schema_version, **payload}, ensure_ascii=False, separators=(",", ":")),
    }


def _result(
    context: NodeExecutionContext,
    *,
    output: dict[str, object],
    artifacts: list[NodeArtifactRef],
    schema_id: str,
    input_ids: list[str],
    roles: dict[str, str],
    retryable: bool,
    provider_request_id: str | None = None,
    logs: list[str] | None = None,
) -> NodeExecutionResult:
    return NodeExecutionResult(
        output=output,
        output_artifact_ids=[artifact.id for artifact in artifacts],
        provider_request_id=provider_request_id or f"local_{context.request_hash[:20]}",
        metadata={
            "artifact_type": artifacts[0].type,
            "schema_id": schema_id,
            "input_artifact_ids": input_ids,
            "lineage_roles": roles,
            "retryable": retryable,
            "logs": logs or [],
        },
    )


class CharacterReferenceValidationExecutor:
    def execute(self, context: NodeExecutionContext, config: dict[str, Any], typed_inputs: list[dict[str, Any]]) -> NodeExecutionResult:
        context.report_progress(15, "Reading character image")
        source = _find_artifact(context, typed_inputs, {"Image"}, "Character Reference")
        data, content_type = _read_artifact(source)
        metadata = inspect_image(data, content_type)
        if metadata.width < int(config["minimum_width"]) or metadata.height < int(config["minimum_height"]):
            raise ValueError(
                f"Character image is {metadata.width}x{metadata.height}; minimum is "
                f"{config['minimum_width']}x{config['minimum_height']}"
            )
        if metadata.has_alpha and not bool(config["allow_alpha"]):
            raise ValueError("Character image contains alpha/transparency but allow_alpha is disabled")
        context.report_progress(70, "Validated character image dimensions and alpha")
        artifact_metadata = {
            "experiment_id": context.experiment_id,
            "request_hash": context.request_hash,
            "execution_mode": CHARACTER_REFERENCE_REVISION,
            "immutable": True,
            "source": "character_reference_validation",
            "filename": f"character-reference.{metadata.format}",
            "width": metadata.width,
            "height": metadata.height,
            "has_alpha": metadata.has_alpha,
            "image_format": metadata.format,
            "character_id": config["character_id"],
            "character_name": config["character_name"],
            "source_model": config["source_model"],
            "prompt": config["prompt"],
            "normalized_config": config,
        }
        artifact = create_artifact(
            context, "CharacterReference", schema_id="character.reference.v1",
            input_artifact_ids=[source.id], input_artifact_roles={source.id: "source_character_image"},
            metadata=artifact_metadata, content=data, content_type=content_type,
            filename=artifact_metadata["filename"],
        )
        context.require_artifact_store().flush()
        return _result(
            context,
            output={
                "kind": "image", "title": config["character_name"] or "Validated character reference",
                "mimeType": content_type, "url": artifact_content_url(artifact.id),
            },
            artifacts=[artifact], schema_id="character.reference.v1", input_ids=[source.id],
            roles={source.id: "source_character_image"}, retryable=False,
        )


class CharacterMultiviewReferenceExecutor:
    def execute(
        self,
        context: NodeExecutionContext,
        config: dict[str, Any],
        typed_inputs: list[dict[str, Any]],
    ) -> NodeExecutionResult:
        character = _find_artifact(context, typed_inputs, {"Character"}, "Character multiview reference")
        metadata = dict(character.metadata_json or {})
        image_ids = [str(value) for value in metadata.get("image_artifact_ids") or []]
        image_roles = [str(value) for value in metadata.get("image_roles") or []]
        by_role = {
            image_roles[index]: image_id
            for index, image_id in enumerate(image_ids)
            if index < len(image_roles)
        }
        configured_roles = {
            "front": str(config["front_role"]),
            "left": str(config["left_role"]),
            "back": str(config["back_role"]),
            "right": str(config["right_role"]),
        }
        selected = {provider_role: role for provider_role, role in configured_roles.items() if role}
        if "front" not in selected:
            raise ValueError("Character multiview reference requires a front role")
        if len(selected) < int(config["minimum_views"]):
            raise ValueError(
                f"Character multiview reference requires at least {config['minimum_views']} configured views"
            )
        missing = [role for role in selected.values() if role not in by_role]
        if missing:
            available = ", ".join(sorted(by_role)) or "none"
            raise ValueError(
                f"Character bundle is missing configured view roles: {', '.join(missing)}. Available roles: {available}"
            )
        selected_ids = [by_role[role] for role in selected.values()]
        if len(selected_ids) != len(set(selected_ids)):
            raise ValueError("Character multiview roles must resolve to distinct Image Artifacts")

        context.report_progress(15, "Validating character multiview images")
        views: list[dict[str, Any]] = []
        input_ids = [character.id]
        lineage_roles = {character.id: "character_bundle"}
        for provider_role, character_role in selected.items():
            image_id = by_role[character_role]
            try:
                image = context.require_artifact_store().read(image_id)
            except ValueError as exc:
                raise ValueError(
                    f"Character view {character_role} does not reference an Image Artifact"
                ) from exc
            if image.type != "Image":
                raise ValueError(f"Character view {character_role} does not reference an Image Artifact")
            data, content_type = _read_artifact(image)
            inspected = inspect_image(data, content_type)
            if inspected.format not in {"png", "jpeg"}:
                raise ValueError(
                    f"Character view {character_role} is {inspected.format}; Tripo file upload requires PNG or JPEG"
                )
            if inspected.width < int(config["minimum_width"]) or inspected.height < int(config["minimum_height"]):
                raise ValueError(
                    f"Character view {character_role} is {inspected.width}x{inspected.height}; minimum is "
                    f"{config['minimum_width']}x{config['minimum_height']}"
                )
            views.append({
                "provider_role": provider_role,
                "character_role": character_role,
                "artifact_id": image.id,
                "content_type": content_type.split(";", 1)[0].lower(),
                "width": inspected.width,
                "height": inspected.height,
                "has_alpha": inspected.has_alpha,
            })
            input_ids.append(image.id)
            lineage_roles[image.id] = f"{provider_role}_character_view"

        manifest = {
            "schema_version": "character.reference_set.v1",
            "character_id": character.id,
            "character_name": str(metadata.get("name") or ""),
            "views": views,
        }
        context.report_progress(75, f"Prepared {len(views)} reusable character views")
        artifact = create_artifact(
            context,
            "CharacterReferenceSet",
            schema_id="character.reference_set.v1",
            input_artifact_ids=input_ids,
            input_artifact_roles=lineage_roles,
            metadata={
                "experiment_id": context.experiment_id,
                "request_hash": context.request_hash,
                "execution_mode": CHARACTER_REFERENCE_SET_REVISION,
                "immutable": True,
                "source": "character_multiview_reference",
                "filename": "character-reference-set.json",
                "character_id": character.id,
                "character_name": manifest["character_name"],
                "views": views,
                "normalized_config": config,
            },
            content=json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(),
            content_type="application/json",
            filename="character-reference-set.json",
        )
        context.require_artifact_store().flush()
        front = next(view for view in views if view["provider_role"] == "front")
        return _result(
            context,
            output={
                "kind": "image",
                "title": f"{manifest['character_name'] or 'Character'} · {len(views)} validated 3D views",
                "mimeType": front["content_type"],
                "url": artifact_content_url(str(front["artifact_id"])),
            },
            artifacts=[artifact],
            schema_id="character.reference_set.v1",
            input_ids=input_ids,
            roles=lineage_roles,
            retryable=False,
        )


class ImageTo3DExecutor:
    def execute(self, context: NodeExecutionContext, config: dict[str, Any], typed_inputs: list[dict[str, Any]]) -> NodeExecutionResult:
        reference = _find_artifact(context, typed_inputs, {"CharacterReference"}, "Image to 3D")
        image, image_content_type = _read_artifact(reference)
        override_id = str(config["manual_3d_artifact_id"] or "")
        override = _find_artifact(
            context, typed_inputs, {"Model3D", "Character3D", "Character3DValidated", "CharacterRigged"},
            "Manual 3D override", explicit_id=override_id,
        ) if override_id else None
        override_data = _read_artifact(override)[0] if override else None
        provider = image_to_3d_provider(str(config["provider"]))
        context.report_progress(20, f"Generating mesh with {provider.name} provider")
        generated = provider.generate(ImageTo3DInput(
            image=image,
            image_content_type=image_content_type,
            quality=str(config["quality"]),
            seed=int(config["seed"]),
            override_glb=override_data,
        ))
        context.report_progress(75, "Validating generated GLB")
        validation = inspect_glb(generated.glb)
        input_ids = [reference.id, *([override.id] if override else [])]
        roles = {reference.id: "character_reference", **({override.id: "manual_3d_override"} if override else {})}
        artifact = create_artifact(
            context, "Character3D", schema_id="character.3d.glb.v1",
            input_artifact_ids=input_ids, input_artifact_roles=roles,
            metadata={
                "experiment_id": context.experiment_id, "request_hash": context.request_hash,
                "execution_mode": IMAGE_TO_3D_REVISION, "immutable": True,
                "source": "image_to_3d", "filename": "character.glb",
                "provider": generated.provider, "provider_revision": generated.provider_revision,
                "validation": validation, "normalized_config": config,
            },
            content=generated.glb, content_type="model/gltf-binary", filename="character.glb",
        )
        context.require_artifact_store().flush()
        return _result(
            context,
            output=_json_output("Generated character GLB", "character.3d.glb.v1", validation),
            artifacts=[artifact], schema_id="character.3d.glb.v1", input_ids=input_ids, roles=roles,
            retryable=generated.provider != "manual", provider_request_id=generated.provider_request_id,
        )


class TripoImageTo3DExecutor:
    reference_artifact_type = "CharacterReferenceSet"
    reference_schema = "character.reference_set.v1"

    def validate_reference_manifest(self, manifest: dict[str, Any]) -> None:
        pass

    @staticmethod
    def runtime_revision(definition: Any, resolved_config: dict[str, Any]) -> str:
        del resolved_config
        return f"{definition.execution.revision}+{TRIPO_API_REVISION}"

    def execute(
        self,
        context: NodeExecutionContext,
        config: dict[str, Any],
        typed_inputs: list[dict[str, Any]],
    ) -> NodeExecutionResult:
        reference = _find_artifact(
            context, typed_inputs, {self.reference_artifact_type}, "Tripo Image to 3D",
        )
        manifest_bytes, _ = _read_artifact(reference)
        try:
            manifest = json.loads(manifest_bytes)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("CharacterReferenceSet Artifact contains invalid JSON") from exc
        if not isinstance(manifest, dict) or manifest.get("schema_version") != self.reference_schema:
            raise ValueError(f"Tripo Image to 3D requires {self.reference_schema}")
        self.validate_reference_manifest(manifest)
        source_views = manifest.get("views")
        if not isinstance(source_views, list):
            raise ValueError("CharacterReferenceSet does not contain views")
        views: list[ImageTo3DView] = []
        for item in source_views:
            if not isinstance(item, dict):
                raise ValueError("CharacterReferenceSet contains an invalid view")
            artifact_id = str(item.get("artifact_id") or "")
            try:
                source = context.require_artifact_store().read(artifact_id)
            except ValueError as exc:
                raise ValueError(
                    f"CharacterReferenceSet view Artifact is missing: {artifact_id}"
                ) from exc
            if source.type != "Image":
                raise ValueError(f"CharacterReferenceSet view Artifact is missing: {artifact_id}")
            data, content_type = _read_artifact(source)
            role = str(item.get("provider_role") or "")
            views.append(ImageTo3DView(
                role=role,
                data=data,
                content_type=content_type,
                filename=f"{role}.{'jpg' if 'jpeg' in content_type else 'png'}",
            ))
        model_alias = str(config["model_alias"])
        model_id = model_id_for_alias(model_alias)
        if not model_id:
            raise ValueError(f"Tripo Image to 3D model alias is not registered: {model_alias}")
        _, resume_task_id = _resume_tripo_task(context, {"generate"})
        provider = image_to_3d_provider("tripo")
        context.report_progress(5, f"Preparing {len(views)} views for Tripo {model_id}")
        generated = provider.generate(ImageTo3DInput(
            image=b"",
            image_content_type="application/json",
            quality=str(config["texture_quality"]),
            seed=int(config["seed"]),
            views=tuple(views),
            model_id=model_id,
            face_limit=int(config["face_limit"]),
            texture=bool(config["texture"]),
            pbr=bool(config["pbr"]),
            texture_quality=str(config["texture_quality"]),
            export_uv=bool(config["export_uv"]),
            smart_low_poly=bool(config["smart_low_poly"]),
            timeout_seconds=int(config["timeout_seconds"]),
            resume_task_id=resume_task_id,
            task_callback=lambda stage, task_id: _remember_tripo_task(context, stage, task_id),
            progress_callback=context.report_progress,
        ))
        context.report_progress(94, "Validating Tripo GLB")
        validation = inspect_glb(generated.glb)
        if not validation["valid"]:
            raise ValueError("Tripo generated GLB does not contain a usable mesh")
        artifact = create_artifact(
            context,
            "Character3D",
            schema_id="character.3d.glb.v1",
            input_artifact_ids=[reference.id],
            input_artifact_roles={reference.id: "character_reference_set"},
            metadata={
                "experiment_id": context.experiment_id,
                "request_hash": context.request_hash,
                "execution_mode": context.definition.execution.revision,
                "immutable": True,
                "source": "tripo_multiview_image_to_3d",
                "filename": "character.glb",
                "provider": generated.provider,
                "provider_revision": generated.provider_revision,
                "provider_metadata": generated.metadata,
                "validation": validation,
                "normalized_config": config,
            },
            content=generated.glb,
            content_type="model/gltf-binary",
            filename="character.glb",
        )
        context.require_artifact_store().flush()
        return _result(
            context,
            output=_json_output("Tripo generated character GLB", "character.3d.glb.v1", {
                **validation,
                "provider": "tripo",
                "provider_metadata": generated.metadata,
            }),
            artifacts=[artifact],
            schema_id="character.3d.glb.v1",
            input_ids=[reference.id],
            roles={reference.id: "character_reference_set"},
            retryable=True,
            provider_request_id=generated.provider_request_id,
        )


class Character3DValidationExecutor:
    def execute(self, context: NodeExecutionContext, config: dict[str, Any], typed_inputs: list[dict[str, Any]]) -> NodeExecutionResult:
        source = _find_artifact(context, typed_inputs, {"Character3D", "Model3D"}, "3D Asset Validation")
        data, _ = _read_artifact(source)
        context.report_progress(25, "Parsing GLB mesh, materials, textures, and skeleton")
        report = inspect_glb(data)
        metadata = report["metadata"]
        if not report["valid"]:
            raise ValueError("GLB could not be parsed into a usable mesh")
        if int(metadata["vertex_count"]) > int(config["maximum_vertices"]):
            raise ValueError(f"GLB has {metadata['vertex_count']} vertices; maximum is {config['maximum_vertices']}")
        if bool(config["require_embedded_textures"]) and metadata["external_texture_references"]:
            raise ValueError("Texture dependency is missing from the GLB")
        if bool(config["require_humanoid_proportions"]) and metadata["humanoid_proportions"] is not True:
            raise ValueError("GLB bounding box does not satisfy the humanoid proportion check")
        context.report_progress(75, "3D Asset validation completed")
        validated = create_artifact(
            context, "Character3DValidated", schema_id="character.3d.validated.v1",
            input_artifact_ids=[source.id], input_artifact_roles={source.id: "generated_3d_asset"},
            metadata={
                "experiment_id": context.experiment_id, "request_hash": context.request_hash,
                "execution_mode": CHARACTER_3D_VALIDATION_REVISION, "immutable": True,
                "source": "character_3d_validation", "filename": "character-validated.glb",
                "validation": report, "normalized_config": config,
            }, content=data, content_type="model/gltf-binary", filename="character-validated.glb",
        )
        report_artifact = create_artifact(
            context, "MetadataJSON", schema_id="character.3d.validation.v1",
            input_artifact_ids=[source.id], input_artifact_roles={source.id: "validated_3d_asset"},
            metadata={"experiment_id": context.experiment_id, "immutable": True, "filename": "validation.json"},
            content=json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(),
            content_type="application/json", filename="validation.json",
        )
        context.require_artifact_store().flush()
        return _result(
            context, output=_json_output("3D character validation", "character.3d.validation.v1", report),
            artifacts=[validated, report_artifact], schema_id="character.3d.validated.v1",
            input_ids=[source.id], roles={source.id: "generated_3d_asset"}, retryable=False,
        )


class AutoRigExecutor:
    def execute(self, context: NodeExecutionContext, config: dict[str, Any], typed_inputs: list[dict[str, Any]]) -> NodeExecutionResult:
        source = _find_artifact(context, typed_inputs, {"Character3DValidated", "Character3D", "Model3D"}, "Auto Rig")
        source_data, _ = _read_artifact(source)
        override_id = str(config["manual_rigged_artifact_id"] or "")
        override = _find_artifact(
            context, typed_inputs, {"Model3D", "CharacterRigged", "Character3D", "Character3DValidated"},
            "Manual rigged override", explicit_id=override_id,
        ) if override_id else None
        provider = auto_rig_provider(str(config["provider"]))
        context.report_progress(20, f"Rigging with {provider.name} provider")
        rigged = provider.rig(AutoRigInput(
            glb=source_data,
            rig_profile=str(config["rig_profile"]),
            override_glb=_read_artifact(override)[0] if override else None,
        ))
        context.report_progress(75, "Validated rig bone hierarchy")
        input_ids = [source.id, *([override.id] if override else [])]
        roles = {source.id: "validated_3d_asset", **({override.id: "manual_rigged_override"} if override else {})}
        artifact = create_artifact(
            context, "CharacterRigged", schema_id="character.rigged.glb.v1",
            input_artifact_ids=input_ids, input_artifact_roles=roles,
            metadata={
                "experiment_id": context.experiment_id, "request_hash": context.request_hash,
                "execution_mode": AUTO_RIG_REVISION, "immutable": True, "source": "character_auto_rig",
                "filename": "character-rigged.glb", "provider": rigged.provider,
                "provider_revision": rigged.provider_revision,
                "skeleton": rigged.skeleton_metadata, "normalized_config": config,
            }, content=rigged.glb, content_type="model/gltf-binary", filename="character-rigged.glb",
        )
        skeleton = create_artifact(
            context, "MetadataJSON", schema_id="humanoid.skeleton.v1",
            input_artifact_ids=[artifact.id], input_artifact_roles={artifact.id: "rigged_character"},
            metadata={"experiment_id": context.experiment_id, "immutable": True, "filename": "skeleton.json"},
            content=json.dumps(rigged.skeleton_metadata, sort_keys=True, separators=(",", ":")).encode(),
            content_type="application/json", filename="skeleton.json",
        )
        context.require_artifact_store().flush()
        return _result(
            context,
            output=_json_output("Rigged character", "character.rigged.glb.v1", {"skeleton": rigged.skeleton_metadata}),
            artifacts=[artifact, skeleton], schema_id="character.rigged.glb.v1",
            input_ids=input_ids, roles=roles, retryable=rigged.provider not in {"manual", "passthrough"},
            provider_request_id=rigged.provider_request_id,
        )


class TripoAutoRigExecutor:
    @staticmethod
    def runtime_revision(definition: Any, resolved_config: dict[str, Any]) -> str:
        del resolved_config
        return f"{definition.execution.revision}+{TRIPO_API_REVISION}"

    def execute(
        self,
        context: NodeExecutionContext,
        config: dict[str, Any],
        typed_inputs: list[dict[str, Any]],
    ) -> NodeExecutionResult:
        source = _find_artifact(
            context,
            typed_inputs,
            {"Character3DValidated", "Character3D", "Model3D"},
            "Tripo Auto Rig",
        )
        source_data, _ = _read_artifact(source)
        model_id = model_id_for_alias(context.model_alias)
        if not model_id:
            raise ValueError(f"Tripo Auto Rig model alias is not registered: {context.model_alias}")
        resume_stage, resume_task_id = _resume_tripo_task(context, {"rig_check", "rig"})
        provider = auto_rig_provider("tripo")
        context.report_progress(5, "Preparing GLB for Tripo Rig Check")
        rigged = provider.rig(AutoRigInput(
            glb=source_data,
            rig_profile=str(config["rig_profile"]),
            model_id=model_id,
            rig_type=str(config["rig_type"]),
            run_rig_check=bool(config["run_rig_check"]),
            timeout_seconds=int(config["timeout_seconds"]),
            resume_stage=resume_stage,
            resume_task_id=resume_task_id,
            task_callback=lambda stage, task_id: _remember_tripo_task(context, stage, task_id),
            progress_callback=context.report_progress,
        ))
        context.report_progress(94, "Validating Tripo humanoid rig")
        validation = inspect_glb(rigged.glb)
        if not validation["valid"] or not validation["metadata"].get("skeleton_exists"):
            raise ValueError("Tripo Auto Rig GLB does not contain a usable mesh and skeleton")
        artifact = create_artifact(
            context,
            "CharacterRigged",
            schema_id="character.rigged.glb.v1",
            input_artifact_ids=[source.id],
            input_artifact_roles={source.id: "validated_3d_asset"},
            metadata={
                "experiment_id": context.experiment_id,
                "request_hash": context.request_hash,
                "execution_mode": TRIPO_AUTO_RIG_REVISION,
                "immutable": True,
                "source": "tripo_auto_rig",
                "filename": "character-rigged.glb",
                "provider": rigged.provider,
                "provider_revision": rigged.provider_revision,
                "skeleton": rigged.skeleton_metadata,
                "validation": validation,
                "normalized_config": config,
            },
            content=rigged.glb,
            content_type="model/gltf-binary",
            filename="character-rigged.glb",
        )
        skeleton = create_artifact(
            context,
            "MetadataJSON",
            schema_id="humanoid.skeleton.v1",
            input_artifact_ids=[artifact.id],
            input_artifact_roles={artifact.id: "rigged_character"},
            metadata={
                "experiment_id": context.experiment_id,
                "immutable": True,
                "filename": "skeleton.json",
                "provider": "tripo",
            },
            content=json.dumps(rigged.skeleton_metadata, sort_keys=True, separators=(",", ":")).encode(),
            content_type="application/json",
            filename="skeleton.json",
        )
        context.require_artifact_store().flush()
        return _result(
            context,
            output=_json_output("Tripo rigged character", "character.rigged.glb.v1", {
                "skeleton": rigged.skeleton_metadata,
                "validation": validation,
            }),
            artifacts=[artifact, skeleton],
            schema_id="character.rigged.glb.v1",
            input_ids=[source.id],
            roles={source.id: "validated_3d_asset"},
            retryable=True,
            provider_request_id=rigged.provider_request_id,
        )


class MotionVideoValidationExecutor:
    def execute(self, context: NodeExecutionContext, config: dict[str, Any], typed_inputs: list[dict[str, Any]]) -> NodeExecutionResult:
        source = _find_artifact(context, typed_inputs, {"Video", "FinalVideo", "ProxyVideo"}, "Motion Video Input")
        data, content_type = _read_artifact(source)
        context.report_progress(25, "Inspecting dance video with ffprobe")
        metadata = inspect_video(data, content_type)
        if metadata.duration_seconds > float(config["maximum_duration_seconds"]):
            raise ValueError(
                f"Dance video is {metadata.duration_seconds:.2f}s; maximum is {config['maximum_duration_seconds']}s"
            )
        if metadata.fps < float(config["minimum_fps"]):
            raise ValueError(f"Dance video FPS is {metadata.fps:.3g}; minimum is {config['minimum_fps']}")
        if metadata.width < int(config["minimum_width"]) or metadata.height < int(config["minimum_height"]):
            raise ValueError(
                f"Dance video resolution is {metadata.width}x{metadata.height}; minimum is "
                f"{config['minimum_width']}x{config['minimum_height']}"
            )
        artifact = create_artifact(
            context, "MotionSourceVideo", schema_id="motion.source_video.v1",
            input_artifact_ids=[source.id], input_artifact_roles={source.id: "reference_dance_video"},
            metadata={
                "experiment_id": context.experiment_id, "request_hash": context.request_hash,
                "execution_mode": MOTION_VIDEO_REVISION, "immutable": True,
                "source": "motion_video_validation", "filename": "motion-source-video",
                "duration_ms": round(metadata.duration_seconds * 1000), "fps": metadata.fps,
                "width": metadata.width, "height": metadata.height, "codec": metadata.codec,
                "pixel_format": metadata.pixel_format, "normalized_config": config,
            }, content=data, content_type=content_type, filename="motion-source-video.mp4",
        )
        context.require_artifact_store().flush()
        return _result(
            context,
            output={"kind": "video", "title": "Validated motion source", "mimeType": content_type, "url": artifact_content_url(artifact.id)},
            artifacts=[artifact], schema_id="motion.source_video.v1", input_ids=[source.id],
            roles={source.id: "reference_dance_video"}, retryable=False,
        )


class HumanoidMotionExtractionExecutor:
    @staticmethod
    def runtime_revision(definition: Any, resolved_config: dict[str, Any]) -> str:
        del resolved_config
        placement = os.getenv("MOTION_EXTRACTION_EXECUTION_MODE", "local").strip().lower()
        return f"{definition.execution.revision}+{placement}"

    def execute(self, context: NodeExecutionContext, config: dict[str, Any], typed_inputs: list[dict[str, Any]]) -> NodeExecutionResult:
        source = _find_artifact(context, typed_inputs, {"MotionSourceVideo"}, "Humanoid Motion Extraction")
        data, content_type = _read_artifact(source)
        provider = motion_extraction_provider(str(config["provider"]))
        context.report_progress(10, "Decoding reference dance video")
        context.report_progress(20, f"Extracting motion with {provider.name}")
        extracted = provider.extract(MotionExtractionInput(
            video=data, video_content_type=content_type, fps=float(config["fps"]),
            max_width=int(config["max_width"]), confidence_threshold=float(config["confidence_threshold"]),
            include_hands=bool(config["include_hands"]), include_face=bool(config["include_face"]),
            source_artifact_id=source.id,
        ))
        context.report_progress(80, "Converted landmarks to canonical bone rotations")
        motion_bytes = canonical_motion_bytes(extracted.motion)
        artifact = create_artifact(
            context, "MotionRaw", schema_id="humanoid.motion.v1",
            input_artifact_ids=[source.id], input_artifact_roles={source.id: "motion_source_video"},
            metadata={
                "experiment_id": context.experiment_id, "request_hash": context.request_hash,
                "execution_mode": self.runtime_revision(context.definition, config), "immutable": True,
                "source": "humanoid_motion_extraction", "filename": "dance-motion-raw.json",
                "provider": extracted.provider, "provider_revision": extracted.provider_revision,
                "frame_count": len(extracted.motion["frames"]), "fps": extracted.motion["fps"],
                "duration_ms": round(extracted.motion["duration_seconds"] * 1000),
                "extraction": extracted.metadata, "normalized_config": config,
            }, content=motion_bytes, content_type="application/json", filename="dance-motion-raw.json",
        )
        metadata_artifact = create_artifact(
            context, "MetadataJSON", schema_id="humanoid.motion.metadata.v1",
            input_artifact_ids=[artifact.id], input_artifact_roles={artifact.id: "raw_humanoid_motion"},
            metadata={"experiment_id": context.experiment_id, "immutable": True, "filename": "motion-metadata.json"},
            content=json.dumps(extracted.metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(),
            content_type="application/json", filename="motion-metadata.json",
        )
        context.require_artifact_store().flush()
        summary = {
            "frame_count": len(extracted.motion["frames"]), "fps": extracted.motion["fps"],
            "duration_seconds": extracted.motion["duration_seconds"], "provider": extracted.provider,
            **extracted.metadata,
        }
        return _result(
            context, output=_json_output("Raw humanoid motion", "humanoid.motion.v1", summary),
            artifacts=[artifact, metadata_artifact], schema_id="humanoid.motion.v1", input_ids=[source.id],
            roles={source.id: "motion_source_video"}, retryable=False,
            provider_request_id=extracted.provider_request_id,
        )


class HumanoidMotionCleanupExecutor:
    def execute(self, context: NodeExecutionContext, config: dict[str, Any], typed_inputs: list[dict[str, Any]]) -> NodeExecutionResult:
        source = _find_artifact(context, typed_inputs, {"MotionRaw", "MotionClean"}, "Humanoid Motion Cleanup")
        data, _ = _read_artifact(source)
        motion = parse_canonical_motion(data)
        context.report_progress(20, "Interpolating invalid and low-confidence frames")
        cleaned = cleanup_motion(
            motion,
            smoothing=float(config["smoothing"]),
            confidence_threshold=float(config["confidence_threshold"]),
            invalid_frame_policy=str(config["invalid_frame_policy"]),
            joint_limits=bool(config["joint_limits"]),
            root_stabilization=bool(config["root_stabilization"]),
            foot_lock=bool(config["foot_lock"]),
        )
        context.report_progress(80, "Applied quaternion smoothing, root stabilization, and foot locking")
        artifact = create_artifact(
            context, "MotionClean", schema_id="humanoid.motion.clean.v1",
            input_artifact_ids=[source.id], input_artifact_roles={source.id: "raw_humanoid_motion"},
            metadata={
                "experiment_id": context.experiment_id, "request_hash": context.request_hash,
                "execution_mode": MOTION_CLEANUP_REVISION, "immutable": True,
                "source": "humanoid_motion_cleanup", "filename": "dance-motion-clean.json",
                "frame_count": len(cleaned["frames"]), "fps": cleaned["fps"],
                "duration_ms": round(cleaned["duration_seconds"] * 1000),
                "cleanup": cleaned["metadata"]["cleanup"], "normalized_config": config,
            }, content=canonical_motion_bytes(cleaned), content_type="application/json", filename="dance-motion-clean.json",
        )
        context.require_artifact_store().flush()
        return _result(
            context,
            output=_json_output("Clean humanoid motion", "humanoid.motion.clean.v1", cleaned["metadata"]["cleanup"]),
            artifacts=[artifact], schema_id="humanoid.motion.clean.v1", input_ids=[source.id],
            roles={source.id: "raw_humanoid_motion"}, retryable=False,
        )


class HumanoidMotionRetargetExecutor:
    @staticmethod
    def runtime_revision(definition: Any, resolved_config: dict[str, Any]) -> str:
        del resolved_config
        return f"{definition.execution.revision}+{blender_runtime_revision()}"

    def execute(self, context: NodeExecutionContext, config: dict[str, Any], typed_inputs: list[dict[str, Any]]) -> NodeExecutionResult:
        character = _find_artifact(context, typed_inputs, {"CharacterRigged"}, "Motion Retarget rig")
        motion_artifact = _find_artifact(context, typed_inputs, {"MotionClean"}, "Motion Retarget motion")
        character_data, _ = _read_artifact(character)
        motion_data, _ = _read_artifact(motion_artifact)
        motion = parse_canonical_motion(motion_data)
        bone_map = resolve_bone_map(str(config["rig_profile"]), str(config["bone_map_json"] or ""))
        provider = get_blender_execution_provider()
        result = provider.retarget(
            character_data, motion, bone_map,
            root_motion=bool(config["root_motion"]), scale_mode=str(config["scale_mode"]),
            fps=int(config["fps"]), timeout_seconds=int(config["timeout_seconds"]),
            progress=context.report_progress,
        )
        input_ids = [character.id, motion_artifact.id]
        roles = {character.id: "rigged_character", motion_artifact.id: "clean_humanoid_motion"}
        animated = create_artifact(
            context, "AnimatedCharacter", schema_id="character.animated.glb.v1",
            input_artifact_ids=input_ids, input_artifact_roles=roles,
            metadata={
                "experiment_id": context.experiment_id, "request_hash": context.request_hash,
                "execution_mode": self.runtime_revision(context.definition, config), "immutable": True,
                "source": "blender_motion_retarget", "filename": "animated-character.glb",
                "retarget": result.metadata, "bone_map": bone_map, "worker_logs": result.logs, "normalized_config": config,
            }, content=result.animated_glb, content_type="model/gltf-binary", filename="animated-character.glb",
        )
        blend = create_artifact(
            context, "BlendFile", schema_id="animation.blend.v1",
            input_artifact_ids=input_ids, input_artifact_roles=roles,
            metadata={
                "experiment_id": context.experiment_id, "request_hash": context.request_hash,
                "execution_mode": self.runtime_revision(context.definition, config), "immutable": True,
                "source": "blender_motion_retarget", "filename": "animation.blend",
                "retarget": result.metadata, "worker_logs": result.logs, "normalized_config": config,
            }, content=result.blend, content_type="application/x-blender", filename="animation.blend",
        )
        context.require_artifact_store().flush()
        return _result(
            context,
            output=_json_output("Retargeted character animation", "animation.retarget.v1", result.metadata),
            artifacts=[animated, blend], schema_id="character.animated.glb.v1",
            input_ids=input_ids, roles=roles, retryable=True, logs=result.logs,
        )


class BlenderRenderExecutor:
    @staticmethod
    def runtime_revision(definition: Any, resolved_config: dict[str, Any]) -> str:
        del resolved_config
        return f"{definition.execution.revision}+{blender_runtime_revision()}"

    def execute(self, context: NodeExecutionContext, config: dict[str, Any], typed_inputs: list[dict[str, Any]]) -> NodeExecutionResult:
        animated = _find_artifact(context, typed_inputs, {"AnimatedCharacter"}, "Blender Render")
        blend = _find_artifact(context, typed_inputs, {"BlendFile"}, "Blender Render animation")
        blend_data, _ = _read_artifact(blend)
        resolution = str(config["resolution"])
        width, height = {
            "preview": (360, 640), "portrait_1080": (1080, 1920), "square_1080": (1080, 1080),
            "custom": (int(config["width"]), int(config["height"])),
        }[resolution]
        quality = str(config["quality"])
        provider = get_blender_execution_provider()
        rendered = provider.render(
            blend_data, width=width, height=height, fps=int(config["fps"]),
            render_style=str(config["render_style"]), camera_preset=str(config["camera_preset"]),
            background=str(config["background"]), samples=int(config["samples"]), quality=quality,
            timeout_seconds=int(config["timeout_seconds"]), progress=context.report_progress,
        )
        media = inspect_video(rendered.video, "video/mp4")
        artifact_type = "VideoPreview" if quality == "preview" else "FinalVideo"
        schema_id = "video.blender_preview.v1" if quality == "preview" else "video.blender_final.v1"
        input_ids = [animated.id, blend.id]
        roles = {animated.id: "animated_character", blend.id: "animation_file"}
        artifact = create_artifact(
            context, artifact_type, schema_id=schema_id,
            input_artifact_ids=input_ids, input_artifact_roles=roles,
            metadata={
                "experiment_id": context.experiment_id, "request_hash": context.request_hash,
                "execution_mode": self.runtime_revision(context.definition, config), "immutable": True,
                "storage_scope": "renders", "source": "blender_render",
                "filename": "preview.mp4" if quality == "preview" else "final.mp4",
                "duration_ms": round(media.duration_seconds * 1000), "fps": media.fps,
                "width": media.width, "height": media.height, "codec": media.codec,
                "render": rendered.metadata, "normalized_config": config,
                "worker_logs": rendered.logs,
            }, content=rendered.video, content_type="video/mp4",
            filename="preview.mp4" if quality == "preview" else "final.mp4",
        )
        context.require_artifact_store().flush()
        return _result(
            context,
            output={
                "kind": "video", "title": "Blender animation preview" if quality == "preview" else "Final Blender render",
                "mimeType": "video/mp4", "url": artifact_content_url(artifact.id),
            },
            artifacts=[artifact], schema_id=schema_id, input_ids=input_ids, roles=roles,
            retryable=True, logs=rendered.logs,
        )
