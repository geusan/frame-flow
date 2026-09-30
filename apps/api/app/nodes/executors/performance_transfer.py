from __future__ import annotations

import tempfile
import hashlib
from functools import lru_cache
from pathlib import Path
from typing import Any

from ...providers_performance import FalPerformanceService, ElevenLabsVoiceService, MediaProviderError, FAL_PERFORMANCE_MODEL, ELEVENLABS_VOICE_MODEL
from ..contracts import NodeArtifactWrite, NodeExecutionContext, NodeExecutionResult
from .media_tools import probe_media, media_duration_seconds, run_media_command, write_media_artifact


@lru_cache(maxsize=1)
def _ffmpeg_version() -> str:
    return run_media_command(["ffmpeg", "-version"]).stdout.splitlines()[0]


def _runtime_revision(definition) -> str:
    return definition.execution.revision + "+ffmpeg:" + hashlib.sha256(_ffmpeg_version().encode()).hexdigest()[:8]


def _input(artifacts, allowed, label):
    matches = [a for a in artifacts if a.type in allowed]
    if len(matches) != 1:
        raise MediaProviderError(f"{label} requires exactly one matching artifact")
    return matches[0]


def _store(context, config, content, *, kind, mime, filename, inputs, roles, request_id, metadata):
    store = context.require_artifact_store()
    definition = context.definition
    artifact = store.create(NodeArtifactWrite(
        artifact_type=definition.artifact_contract.primary_type,
        schema_id=definition.artifact_contract.schema_id,
        content=content, content_type=mime, filename=filename,
        input_artifact_ids=inputs, input_artifact_roles=roles,
        metadata={"source": "node_executor_registry", "immutable": True, "experiment_id": context.experiment_id,
                  "request_hash": context.request_hash, "execution_mode": _runtime_revision(definition), "ffmpeg_version": _ffmpeg_version(),
                  "normalized_config": config, "definition_digest": definition.definition_digest,
                  "model_alias": context.model_alias, "output_role": definition.artifact_contract.output_role,
                  "filename": filename, **metadata},
    ))
    store.flush()
    return NodeExecutionResult(
        output={"kind": kind, "title": filename, "url": store.content_url(artifact.id), "mimeType": mime},
        output_artifact_ids=[artifact.id], provider_request_id=request_id, cost_usd=0.0,
        metadata={"artifact_type": artifact.type, "schema_id": definition.artifact_contract.schema_id,
                  "input_artifact_ids": inputs, "lineage_roles": roles, "retryable": False,
                  "cost_status": "provider_billed_unreported", **metadata},
    )


class PerformanceTransferExecutor:
    @staticmethod
    def runtime_revision(definition, resolved_config) -> str:
        return _runtime_revision(definition)

    def execute(self, context: NodeExecutionContext, config: dict[str, Any], inputs: list[dict[str, Any]]) -> NodeExecutionResult:
        artifacts = context.require_artifact_store().read_inputs(inputs)
        image = _input(artifacts, {"Image"}, "Character image")
        video = _input(artifacts, {"Video", "FinalVideo"}, "Reference performance")
        context.report_progress(5, "Checking the reference performance")
        with tempfile.TemporaryDirectory(prefix="frameflow-performance-") as temp:
            directory = Path(temp)
            source = write_media_artifact(directory, video, 0)
            source_probe = probe_media(source)
            duration = media_duration_seconds(source_probe)
            limit = 30 if config["character_orientation"] == "video" else 10
            if not 3 <= duration <= limit:
                raise MediaProviderError(f"Reference duration must be between 3 and {limit} seconds for this orientation")
            normalized = directory / "driving.mp4"
            run_media_command(["ffmpeg", "-v", "error", "-y", "-i", str(source), "-map", "0:v:0", "-an",
                               "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(normalized)])
            if normalized.stat().st_size > 100 * 1024 * 1024:
                raise MediaProviderError("Driving video exceeds the 100 MB provider limit")
            tasks = context.require_provider_tasks()
            service = FalPerformanceService()
            try:
                resume = tasks.claim("fal", "performance", resumable=True)
                result = service.transfer(image=image.data, image_content_type=image.content_type, video=normalized.read_bytes(),
                    prompt=config["prompt"], orientation=config["character_orientation"], timeout_seconds=config["timeout_seconds"],
                    resume_id=resume, remember=lambda task_id: tasks.remember("fal", "performance", task_id), progress=context.report_progress)
            finally:
                service.close()
            output = directory / "performance.mp4"
            output.write_bytes(result.content)
            info = probe_media(output)
            result_duration = media_duration_seconds(info)
            if abs(result_duration - duration) > 0.6:
                raise MediaProviderError(f"Motion output duration {result_duration:.3f}s differs from reference {duration:.3f}s")
            if not any(s.get("codec_type") == "video" for s in info.get("streams", [])):
                raise MediaProviderError("Provider output contains no video")
            # The generation contract is silent; final audio belongs to the separate mux node.
            silent = directory / "silent.mp4"
            run_media_command(["ffmpeg", "-v", "error", "-y", "-i", str(output), "-map", "0:v:0", "-c:v", "copy", "-an", "-movflags", "+faststart", str(silent)])
            metadata = {"provider": "fal", "exact_model_id": FAL_PERFORMANCE_MODEL, "provider_request_id": result.request_id,
                        "source_duration_ms": round(duration * 1000), "duration_ms": round(result_duration * 1000),
                        "renderer_revision": "ffmpeg-h264-driving.v1",
                        "audio_policy": "silent", "usage": result.usage}
            return _store(context, config, silent.read_bytes(), kind="video", mime="video/mp4", filename="character-performance.mp4",
                          inputs=[image.id, video.id], roles={image.id: "character_identity", video.id: "driving_performance"},
                          request_id=f"fal:performance:{result.request_id}", metadata=metadata)


class VoiceConvertExecutor:
    @staticmethod
    def runtime_revision(definition, resolved_config) -> str:
        return _runtime_revision(definition)

    def execute(self, context: NodeExecutionContext, config: dict[str, Any], inputs: list[dict[str, Any]]) -> NodeExecutionResult:
        audio = _input(context.require_artifact_store().read_inputs(inputs), {"Audio"}, "Source speech")
        context.report_progress(5, "Preparing the original speech performance")
        with tempfile.TemporaryDirectory(prefix="frameflow-voice-convert-") as temp:
            directory = Path(temp)
            source = write_media_artifact(directory, audio, 0)
            duration = media_duration_seconds(probe_media(source))
            if not 0 < duration <= 300:
                raise MediaProviderError("Voice conversion supports up to 300 seconds per node")
            wav = directory / "source.wav"
            run_media_command(["ffmpeg", "-v", "error", "-y", "-i", str(source), "-vn", "-ac", "1", "-ar", "44100", "-c:a", "pcm_s16le", str(wav)])
            service = ElevenLabsVoiceService()
            tasks = context.require_provider_tasks()
            try:
                service.validate_voice(config["voice_id"])
                tasks.claim("elevenlabs", "voice", resumable=False)
                context.report_progress(20, "Converting voice while preserving the original delivery")
                try:
                    result = service.convert(audio=wav.read_bytes(), voice_id=config["voice_id"], stability=config["stability"],
                        similarity=config["similarity_boost"], seed=config["seed"], remove_noise=config["remove_background_noise"])
                except MediaProviderError as exc:
                    if exc.rejected:
                        tasks.remember("elevenlabs", "voice", "rejected")
                    raise
                tasks.remember("elevenlabs", "voice", result.request_id)
            finally:
                service.close()
            mp3 = directory / "converted.mp3"
            mp3.write_bytes(result.content)
            converted_duration = media_duration_seconds(probe_media(mp3))
            if abs(converted_duration - duration) > 0.5:
                raise MediaProviderError("Converted speech has drifted by more than 500 ms; inspect timing before muxing")
            output = directory / "converted.wav"
            run_media_command(["ffmpeg", "-v", "error", "-y", "-i", str(mp3), "-af", f"apad,atrim=duration={duration:.6f},asetpts=PTS-STARTPTS",
                               "-ac", "1", "-ar", "48000", "-c:a", "pcm_s16le", str(output)])
            return _store(context, config, output.read_bytes(), kind="audio", mime="audio/wav", filename="converted-voice.wav",
                inputs=[audio.id], roles={audio.id: "source_speech"}, request_id=f"elevenlabs:voice:{result.request_id}",
                metadata={"provider": "elevenlabs", "exact_model_id": ELEVENLABS_VOICE_MODEL, "voice_id": config["voice_id"],
                          "source_duration_ms": round(duration * 1000), "duration_ms": round(duration * 1000),
                          "provider_duration_ms": round(converted_duration * 1000), "renderer_revision": "ffmpeg-voice-duration.v1", "usage": result.usage})
