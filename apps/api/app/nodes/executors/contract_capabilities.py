from __future__ import annotations

import json
import math
import os
from typing import Any

from ...media_preview import render_audio_wav, render_image_svg, render_video_mp4
from ...motion_extraction import MOTION_TRACK_VERSION, extract_holistic_motion
from ...providers import model_id_for_alias
from ...providers_generation import character_shot_prompts
from ...providers_localization import get_localization_services, get_speech_recognizer
from ...reference_analysis import analyze_reference_video
from ..contracts import NodeArtifactContent, NodeArtifactRef, NodeArtifactWrite, NodeExecutionContext, NodeExecutionResult
from .text_support import TextProviderResult, complete_text_execution, input_lineage


def _supports_schema(context: NodeExecutionContext, schema_id: str) -> bool:
    return context.definition.artifact_contract.schema_id == schema_id


def _require(
    artifacts: list[NodeArtifactContent],
    label: str,
    *artifact_types: str,
) -> NodeArtifactContent:
    artifact = next(
        (item for item in artifacts if item.type in set(artifact_types)),
        None,
    )
    if artifact is None:
        raise ValueError(f"{label} input artifact is required")
    return artifact


def _text_from_artifact(artifact: NodeArtifactContent) -> str:
    text = artifact.data.decode("utf-8", errors="replace").strip()
    if artifact.content_type == "application/json":
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return text
        if isinstance(payload, dict):
            return str(payload.get("text") or payload.get("script") or text)
    return text


def _artifact_result(
    context: NodeExecutionContext,
    config: dict[str, Any],
    *,
    output: dict[str, object],
    content: bytes,
    content_type: str,
    filename: str,
    input_ids: list[str],
    input_roles: dict[str, str],
    provider_request_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> NodeExecutionResult:
    store = context.require_artifact_store()
    artifact = store.create(
        NodeArtifactWrite(
            artifact_type=context.definition.artifact_contract.primary_type,
            schema_id=context.definition.artifact_contract.schema_id,
            input_artifact_ids=input_ids,
            input_artifact_roles=input_roles,
            metadata={
                "experiment_id": context.experiment_id,
                "request_hash": context.request_hash,
                "execution_mode": context.definition.execution.revision,
                "immutable": True,
                "source": "node_executor_registry",
                "provider": context.definition.execution.provider,
                "model_alias": context.model_alias,
                "normalized_config": config,
                "output_role": context.definition.artifact_contract.output_role,
                **(metadata or {}),
            },
            content=content,
            content_type=content_type,
            filename=filename,
        )
    )
    store.flush()
    return NodeExecutionResult(
        output={**output, "url": store.content_url(artifact.id)},
        output_artifact_ids=[artifact.id],
        provider_request_id=provider_request_id or f"local_{context.request_hash[:20]}",
        metadata={
            "artifact_type": context.definition.artifact_contract.primary_type,
            "schema_id": context.definition.artifact_contract.schema_id,
            "input_artifact_ids": input_ids,
            "lineage_roles": input_roles,
            "retryable": False,
            **(metadata or {}),
        },
    )


class FixtureProviderCapabilityExecutor:
    def supports(self, context: NodeExecutionContext) -> bool:
        return (
            context.definition.execution.kind == "provider"
            and os.getenv("GENERATION_PROVIDER_MODE", "live").strip().lower() != "live"
        )

    def execute(
        self,
        context: NodeExecutionContext,
        config: dict[str, Any],
        typed_inputs: list[dict[str, Any]],
    ) -> NodeExecutionResult:
        if not self.supports(context):
            raise RuntimeError("fixture capability does not support this execution context")
        artifact_type = context.definition.artifact_contract.primary_type
        schema_id = context.definition.artifact_contract.schema_id
        exact_model_id = model_id_for_alias(context.model_alias) or context.model_alias
        input_ids, input_roles = input_lineage(context, typed_inputs)
        digest = context.request_hash

        if artifact_type == "Character":
            return self._character(context, config, input_ids, input_roles, exact_model_id)
        if artifact_type == "Image":
            content = render_image_svg(context.prompt, exact_model_id, digest)
            return _artifact_result(
                context,
                config,
                output={"kind": "image", "title": "Experiment image", "mimeType": "image/svg+xml"},
                content=content,
                content_type="image/svg+xml",
                filename="preview.svg",
                input_ids=input_ids,
                input_roles=input_roles,
                metadata={"exact_model_id": exact_model_id},
            )
        if artifact_type == "Video":
            content = render_video_mp4(digest)
            return _artifact_result(
                context,
                config,
                output={"kind": "video", "title": "Experiment video", "mimeType": "video/mp4"},
                content=content,
                content_type="video/mp4",
                filename="preview.mp4",
                input_ids=input_ids,
                input_roles=input_roles,
                metadata={"exact_model_id": exact_model_id},
            )
        if artifact_type == "Audio":
            content = render_audio_wav(digest)
            return _artifact_result(
                context,
                config,
                output={"kind": "audio", "title": "Fixture voiceover", "mimeType": "audio/wav"},
                content=content,
                content_type="audio/wav",
                filename="preview.wav",
                input_ids=input_ids,
                input_roles=input_roles,
                metadata={"exact_model_id": exact_model_id},
            )

        prompt = context.prompt.strip()
        if schema_id == "prompt.master.v1":
            text = (
                "### 1. English Master Prompt\n"
                f"Production-ready visual specification for: {prompt}\n\n"
                "### 2. Korean Translation\n"
                f"제작 가능한 시각 명세: {prompt}\n\n"
                "### 3. Technical / Visual Blueprint\n"
                "Discipline: visual production · Medium / Output: inferred from the request · "
                "Invariants / Avoid: preserve explicit constraints"
            )
        else:
            text = f"{prompt}\n\nCinematic intent preserved. Subject, action, camera motion, lighting, timing, and exclusions are explicit."
        return complete_text_execution(
            context,
            config,
            typed_inputs,
            TextProviderResult(text, f"local_{digest[:20]}", exact_model_id, 0.0),
            provider="fixture",
            execution_revision="fixture.v1",
        )

    @staticmethod
    def _character(
        context: NodeExecutionContext,
        config: dict[str, Any],
        input_ids: list[str],
        input_roles: dict[str, str],
        exact_model_id: str,
    ) -> NodeExecutionResult:
        store = context.require_artifact_store()
        name = str(config.get("character_name") or "Generated character").strip() or "Generated character"
        shot_count = int(config.get("shot_count") or 6)
        prompts = character_shot_prompts(context.prompt, shot_count, shot_style=str(config.get("shot_style") or "story"))
        images: list[tuple[NodeArtifactRef, str, str]] = []
        for index, (role, prompt) in enumerate(prompts):
            content = render_image_svg(
                prompt,
                exact_model_id,
                f"{context.request_hash}:{index}",
            )
            image = store.create(
                NodeArtifactWrite(
                    artifact_type="Image",
                    schema_id="character.view.v1",
                    input_artifact_ids=input_ids,
                    input_artifact_roles=input_roles,
                    metadata={
                        "experiment_id": context.experiment_id,
                        "request_hash": context.request_hash,
                        "immutable": True,
                        "source": "fixture_character_generation",
                        "character_role": role,
                        "character_view_index": index,
                        "prompt": prompt,
                    },
                    content=content,
                    content_type="image/svg+xml",
                    filename=f"character-{index + 1:02d}-{role}.svg",
                )
            )
            images.append((image, role, prompt))
        store.flush()
        image_ids = [image.id for image, _, _ in images]
        character_inputs = [*input_ids, *image_ids]
        character_roles = {**input_roles, **{image_id: "character_view" for image_id in image_ids}}
        manifest = {
            "schema_version": context.definition.artifact_contract.schema_id,
            "name": name,
            "synopsis": context.prompt,
            "cover_artifact_id": image_ids[0],
            "reference_image_artifact_ids": input_ids,
            "images": [
                {"artifact_id": image.id, "role": role, "prompt": prompt}
                for image, role, prompt in images
            ],
        }
        character = store.create(
            NodeArtifactWrite(
                artifact_type="Character",
                schema_id="character.bundle.v1",
                input_artifact_ids=character_inputs,
                input_artifact_roles=character_roles,
                metadata={
                    "experiment_id": context.experiment_id,
                    "request_hash": context.request_hash,
                    "immutable": True,
                    "source": "fixture_character_generation",
                    "name": name,
                    "synopsis": context.prompt,
                    "cover_artifact_id": image_ids[0],
                    "reference_image_artifact_ids": input_ids,
                    "image_artifact_ids": image_ids,
                    "image_roles": [role for _, role, _ in images],
                    "model_alias": context.model_alias,
                    "exact_model_id": exact_model_id,
                    "normalized_config": config,
                },
                content=json.dumps(manifest, ensure_ascii=False, separators=(",", ":")).encode(),
                content_type="application/json",
                filename="character.json",
            )
        )
        store.flush()
        return NodeExecutionResult(
            output={
                "kind": "image",
                "title": f"{name} · {len(images)} views",
                "mimeType": "image/svg+xml",
                "url": store.content_url(image_ids[0]),
                "characterId": character.id,
                "imageCount": len(images),
            },
            output_artifact_ids=[character.id],
            provider_request_id=f"local_{context.request_hash[:20]}",
            metadata={
                "artifact_type": "Character",
                "schema_id": "character.bundle.v1",
                "input_artifact_ids": character_inputs,
                "lineage_roles": character_roles,
                "retryable": False,
                "exact_model_id": exact_model_id,
            },
        )


class ReferenceAnalysisCapabilityExecutor:
    def supports(self, context: NodeExecutionContext) -> bool:
        return _supports_schema(context, "reference.decomposition.v1")

    def execute(self, context: NodeExecutionContext, config: dict[str, Any], typed_inputs: list[dict[str, Any]]) -> NodeExecutionResult:
        store = context.require_artifact_store()
        artifacts = store.read_inputs(typed_inputs)
        video = _require(artifacts, "Video", "Video", "FinalVideo", "ProxyVideo", "ReferenceOriginal")
        analysis_options = {}
        if context.model_alias.startswith(("openai.chat.", "openai.text.")):
            analysis_options["analyzer_revision"] = context.definition.execution.revision
            if os.getenv("REFERENCE_ANALYSIS_MODE", "live").strip().lower() == "live":
                from ...reference_analysis_openai import OpenAIReferenceAnalyzer, OpenAIReferenceRecognizer
                analysis_options.update(
                    semantic_analyzer=OpenAIReferenceAnalyzer(
                        logical_model=context.model_alias,
                        sample_interval_seconds=float(config["sample_interval_seconds"]),
                        max_frames=int(config["max_frames"]),
                    ),
                    speech_recognizer=OpenAIReferenceRecognizer(),
                )
        bundle = analyze_reference_video(
            video.data,
            video.content_type,
            language_code=str(config.get("source_language") or "auto"),
            separate_music=bool(config.get("separate_music", True)),
            scene_threshold=float(config.get("scene_threshold") or 0.28),
            **analysis_options,
        )
        source_id = video.record.id
        metadata = {
            "definition_digest": context.definition.definition_digest,
            "executor_revision": context.definition.execution.revision,
            "access_scope": "reference-analyzer-only",
            "storage_scope": "reference",
            "source_artifact_id": source_id,
            "duration_ms": int(bundle.manifest["source"]["duration_ms"]),
            "immutable": True,
        }
        derived: dict[str, NodeArtifactRef] = {}
        roles = {source_id: "source_video"}
        payloads = (
            ("audio_mix", "ReferenceAudioMix", "reference.audio.mix.v1", bundle.audio_mix, "audio/wav", "reference-audio.wav"),
            ("transcript", "ReferenceTranscript", "transcript.v1", bundle.transcript, "application/json", "transcript.json"),
            ("subtitle", "ReferenceSubtitle", "subtitle.srt.v1", bundle.subtitles, "application/x-subrip", "transcript.srt"),
            ("vocals", "ReferenceVocals", "reference.audio.stem.v1", bundle.vocals, "audio/wav", "vocals.wav"),
            ("accompaniment", "ReferenceAccompaniment", "reference.audio.stem.v1", bundle.accompaniment, "audio/wav", "accompaniment.wav"),
        )
        for key, artifact_type, schema_id, content, content_type, filename in payloads:
            if content is None:
                continue
            parent_id = (
                derived["audio_mix"].id
                if key in {"transcript", "vocals", "accompaniment"} and "audio_mix" in derived
                else derived["transcript"].id
                if key == "subtitle" and "transcript" in derived
                else source_id
            )
            derived[key] = store.create(
                NodeArtifactWrite(
                    artifact_type=artifact_type,
                    schema_id=schema_id,
                    input_artifact_ids=[parent_id],
                    input_artifact_roles={parent_id: "source_audio" if key in {"transcript", "subtitle"} else "source_video"},
                    metadata={**metadata, **({"stem": key} if key in {"vocals", "accompaniment"} else {})},
                    content=content,
                    content_type=content_type,
                    filename=filename,
                )
            )
        store.flush()
        bundle.manifest["artifacts"] = {key: artifact.id for key, artifact in derived.items()}
        manifest = json.dumps(bundle.manifest, ensure_ascii=False, sort_keys=True, indent=2).encode()
        manifest_inputs = [source_id, *(artifact.id for artifact in derived.values())]
        manifest_roles = {source_id: "source_video", **{artifact.id: key for key, artifact in derived.items()}}
        visual = bundle.manifest["visual"]
        audio = bundle.manifest["audio"]
        return _artifact_result(
            context,
            config,
            output={
                "kind": "json",
                "title": f"Reference analysis · {len(visual['shots'])} shots · {len(visual['actions'])} actions · {len(audio['sound_effects'])} SFX",
                "text": manifest.decode(),
            },
            content=manifest,
            content_type="application/json",
            filename="reference-analysis.json",
            input_ids=manifest_inputs,
            input_roles=manifest_roles,
            provider_request_id=bundle.provider_request_id,
            metadata={**metadata, "component_artifact_ids": bundle.manifest["artifacts"], "runtime_snapshot": bundle.manifest["provenance"], "exact_model_id": bundle.manifest["provenance"]["semantic_model"], "cost_recording": "provider billing; no fabricated estimate"},
        )


class MotionExtractCapabilityExecutor:
    def supports(self, context: NodeExecutionContext) -> bool:
        return _supports_schema(context, MOTION_TRACK_VERSION)

    def execute(self, context: NodeExecutionContext, config: dict[str, Any], typed_inputs: list[dict[str, Any]]) -> NodeExecutionResult:
        artifacts = context.require_artifact_store().read_inputs(typed_inputs)
        video = _require(artifacts, "Video", "Video", "FinalVideo", "ProxyVideo", "ReferenceOriginal")
        motion = extract_holistic_motion(
            video.data,
            video.content_type,
            sample_fps=float(config.get("motion_sample_fps") or 12),
            max_width=int(config.get("motion_max_width") or 640),
            min_confidence=float(config.get("motion_min_confidence") or 0.5),
            output_face_blendshapes=bool(config.get("motion_face_blendshapes", True)),
        )
        content = json.dumps(motion, ensure_ascii=False, separators=(",", ":")).encode()
        summary = motion["summary"]
        coverage = summary["coverage"]
        return _artifact_result(
            context,
            config,
            output={
                "kind": "json",
                "title": f"Holistic motion · {summary['frame_count']} frames",
                "frameCount": summary["frame_count"],
                "sampleFps": motion["source"]["sample_fps"],
                "faceCoverage": coverage["face"],
                "poseCoverage": coverage["pose"],
                "leftHandCoverage": coverage["left_hand"],
                "rightHandCoverage": coverage["right_hand"],
            },
            content=content,
            content_type="application/json",
            filename="motion-track.json",
            input_ids=[video.record.id],
            input_roles={video.record.id: "source_video"},
            metadata={
                "duration_ms": motion["source"]["duration_ms"],
                "frame_count": summary["frame_count"],
                "sample_fps": motion["source"]["sample_fps"],
                "coverage": coverage,
            },
        )


class SubtitleAlignCapabilityExecutor:
    def supports(self, context: NodeExecutionContext) -> bool:
        return _supports_schema(context, "subtitle.srt.v1")

    def execute(self, context: NodeExecutionContext, config: dict[str, Any], typed_inputs: list[dict[str, Any]]) -> NodeExecutionResult:
        artifacts = context.require_artifact_store().read_inputs(typed_inputs)
        audio = _require(artifacts, "Audio", "Audio")
        media_runtime = context.require_media_runtime()
        duration = media_runtime.media_duration(audio)
        mode = os.getenv("SUBTITLE_ALIGNMENT_MODE", "live").strip().lower()
        if mode == "live":
            transcript = get_speech_recognizer().transcribe(
                audio.data,
                language_code=str(config.get("source_language") or config.get("language") or "auto"),
                duration_ms=round(duration * 1000),
            )
            content = media_runtime.segments_to_srt(transcript.segments)
            title = f"Speech subtitles · {transcript.language_code}"
        elif mode == "heuristic" and os.getenv("APP_ENV") == "test":
            script = _require(artifacts, "Script", "Script", "TimedScript")
            content = media_runtime.build_subtitles(_text_from_artifact(script), duration)
            title = "Timed subtitles"
        else:
            raise ValueError("SUBTITLE_ALIGNMENT_MODE must be live or heuristic")
        input_ids, input_roles = input_lineage(context, typed_inputs)
        return _artifact_result(
            context,
            config,
            output={"kind": "text", "title": title, "text": content.decode()},
            content=content,
            content_type="application/x-subrip",
            filename="subtitles.srt",
            input_ids=input_ids,
            input_roles=input_roles,
        )


class TimelineCapabilityExecutor:
    def supports(self, context: NodeExecutionContext) -> bool:
        return _supports_schema(context, "timeline.v1")

    def execute(self, context: NodeExecutionContext, config: dict[str, Any], typed_inputs: list[dict[str, Any]]) -> NodeExecutionResult:
        artifacts = context.require_artifact_store().read_inputs(typed_inputs)
        timeline = context.require_media_runtime().build_timeline(artifacts, config)
        content = json.dumps(timeline, ensure_ascii=False, sort_keys=True, indent=2).encode()
        input_ids, input_roles = input_lineage(context, typed_inputs)
        return _artifact_result(
            context,
            config,
            output={"kind": "json", "title": "Timeline", "text": content.decode()},
            content=content,
            content_type="application/json",
            filename="timeline.json",
            input_ids=input_ids,
            input_roles=input_roles,
        )


class VideoTranslateCapabilityExecutor:
    def supports(self, context: NodeExecutionContext) -> bool:
        return _supports_schema(context, "video.translation.v1")

    def execute(self, context: NodeExecutionContext, config: dict[str, Any], typed_inputs: list[dict[str, Any]]) -> NodeExecutionResult:
        store = context.require_artifact_store()
        artifacts = store.read_inputs(typed_inputs)
        video = _require(artifacts, "Video", "Video", "FinalVideo")
        source_language = str(config.get("source_language") or "auto")
        target_language = str(config.get("target_language") or "ko-KR")
        voice_name = str(config.get("voice_name") or "Kore")
        media_runtime = context.require_media_runtime()
        speech_audio, duration_ms = media_runtime.extract_speech_audio(video)
        services = get_localization_services()
        transcript = services.recognizer.transcribe(speech_audio, language_code=source_language, duration_ms=duration_ms)
        translation = services.translator.translate(transcript, target_language=target_language)
        speech = services.synthesizer.synthesize(translation.text, language_code=target_language, voice_name=voice_name)
        translated_audio = media_runtime.synthesized_wav(speech)
        subtitles = media_runtime.segments_to_srt(translation.segments)
        source_id = video.record.id
        derived_specs = (
            ("Transcript", "transcript.v1", json.dumps({"version": "transcript.v1", "language_code": transcript.language_code, "text": transcript.text, "segments": [segment.__dict__ for segment in transcript.segments]}, ensure_ascii=False, indent=2).encode(), "application/json", "transcript.json", "transcript"),
            ("TranslatedTranscript", "translation.v1", json.dumps({"version": "translation.v1", "source_language": transcript.language_code, "target_language": target_language, "text": translation.text, "segments": [segment.__dict__ for segment in translation.segments]}, ensure_ascii=False, indent=2).encode(), "application/json", "translation.json", "translation"),
            ("Audio", None, translated_audio, "audio/wav", "translated.wav", "translated_audio"),
            ("Subtitle", "subtitle.srt.v1", subtitles, "application/x-subrip", "translated.srt", "translated_subtitle"),
        )
        derived: dict[str, NodeArtifactRef] = {}
        for artifact_type, schema_id, content, content_type, filename, role in derived_specs:
            derived[role] = store.create(NodeArtifactWrite(
                artifact_type=artifact_type,
                schema_id=schema_id,
                input_artifact_ids=[source_id],
                input_artifact_roles={source_id: "source_video"},
                metadata={"experiment_id": context.experiment_id, "request_hash": context.request_hash, "immutable": True, "source": "video_translation"},
                content=content,
                content_type=content_type,
                filename=filename,
            ))
        store.flush()
        audio_data = next(item for item in store.read_inputs([{"artifact_id": derived["translated_audio"].id}]) if item.id == derived["translated_audio"].id)
        subtitle_data = next(item for item in store.read_inputs([{"artifact_id": derived["translated_subtitle"].id}]) if item.id == derived["translated_subtitle"].id)
        content = media_runtime.replace_audio(video, audio_data, subtitle_data, language=target_language)
        input_ids = [source_id, *(artifact.id for artifact in derived.values())]
        roles = {source_id: "source_video", **{artifact.id: role for role, artifact in derived.items()}}
        return _artifact_result(
            context,
            config,
            output={
                "kind": "video",
                "title": f"Translated video · {target_language}",
                "mimeType": "video/mp4",
                "sourceLanguage": transcript.language_code,
                "targetLanguage": target_language,
                "transcriptArtifactId": derived["transcript"].id,
                "translationArtifactId": derived["translation"].id,
                "audioArtifactId": derived["translated_audio"].id,
                "subtitleArtifactId": derived["translated_subtitle"].id,
                "ttsProviderRequestId": speech.provider_request_id,
            },
            content=content,
            content_type="video/mp4",
            filename="translated.mp4",
            input_ids=input_ids,
            input_roles=roles,
            provider_request_id=translation.provider_request_id,
        )


class GenerationPolicyCapabilityExecutor:
    def supports(self, context: NodeExecutionContext) -> bool:
        return _supports_schema(context, "generation.spec.v1")

    def execute(self, context: NodeExecutionContext, config: dict[str, Any], typed_inputs: list[dict[str, Any]]) -> NodeExecutionResult:
        source_text = [str(item.get("config_text") or item.get("output_text") or item.get("description") or item.get("label") or "").strip() for item in typed_inputs]
        input_ids, input_roles = input_lineage(context, typed_inputs)
        spec = {"version": "generation.spec.v1", "brief": next((text for text in source_text if text), context.prompt), "target_duration_seconds": int(config.get("target_duration_seconds") or 38), "aspect_ratio": config.get("aspect_ratio") or "9:16", "input_artifact_ids": input_ids}
        content = json.dumps(spec, ensure_ascii=False, sort_keys=True, indent=2).encode()
        return _artifact_result(context, config, output={"kind": "json", "title": "Generation specification", "text": content.decode()}, content=content, content_type="application/json", filename="generation-spec.json", input_ids=input_ids, input_roles=input_roles)


class ScriptFitCapabilityExecutor:
    def supports(self, context: NodeExecutionContext) -> bool:
        return _supports_schema(context, "script.timed.v1")

    def execute(self, context: NodeExecutionContext, config: dict[str, Any], typed_inputs: list[dict[str, Any]]) -> NodeExecutionResult:
        artifacts = context.require_artifact_store().read_inputs(typed_inputs)
        script_artifact = _require(artifacts, "Script", "Script", "TimedScript")
        script = _text_from_artifact(script_artifact)
        target_seconds = int(config.get("target_duration_seconds") or 38)
        target_chars = max(20, round(target_seconds * 4.7))
        fitted = script if len(script) <= target_chars else script[:target_chars].rsplit(" ", 1)[0].rstrip() + "…"
        input_ids, input_roles = input_lineage(context, typed_inputs)
        return _artifact_result(context, config, output={"kind": "text", "title": f"Timed script · {target_seconds}s", "text": fitted}, content=fitted.encode(), content_type="text/plain", filename="script.txt", input_ids=input_ids, input_roles=input_roles)


class ShotPlanCapabilityExecutor:
    def supports(self, context: NodeExecutionContext) -> bool:
        return _supports_schema(context, "shot.plan.v1")

    def execute(self, context: NodeExecutionContext, config: dict[str, Any], typed_inputs: list[dict[str, Any]]) -> NodeExecutionResult:
        target_seconds = int(config.get("target_duration_seconds") or 38)
        shot_duration = 6
        shot_count = max(1, math.ceil(target_seconds / shot_duration))
        shots = [{"index": index + 1, "start_ms": index * shot_duration * 1000, "duration_ms": min(shot_duration, target_seconds - index * shot_duration) * 1000} for index in range(shot_count)]
        payload = {"version": "shot.plan.v1", "shots": shots}
        content = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2).encode()
        input_ids, input_roles = input_lineage(context, typed_inputs)
        return _artifact_result(context, config, output={"kind": "json", "title": "Shot plan", "text": content.decode()}, content=content, content_type="application/json", filename="shot-plan.json", input_ids=input_ids, input_roles=input_roles)


class MediaQcCapabilityExecutor:
    def supports(self, context: NodeExecutionContext) -> bool:
        return _supports_schema(context, "qc.report.v1")

    def execute(self, context: NodeExecutionContext, config: dict[str, Any], typed_inputs: list[dict[str, Any]]) -> NodeExecutionResult:
        artifacts = context.require_artifact_store().read_inputs(typed_inputs)
        video = _require(artifacts, "Video", "Video", "FinalVideo")
        report = context.require_media_runtime().quality_report(video, config)
        content = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2).encode()
        return _artifact_result(context, config, output={"kind": "json", "title": "QC passed" if report["passed"] else "QC failed", "text": content.decode()}, content=content, content_type="application/json", filename="qc-report.json", input_ids=[video.record.id], input_roles={video.record.id: "video"})
