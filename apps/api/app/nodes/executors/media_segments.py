from __future__ import annotations

import tempfile
import wave
from pathlib import Path

from ..contracts import NodeArtifactWrite, NodeExecutionResult
from .frame_extract import _renderer_revision
from .media_tools import media_duration_seconds, probe_media, run_media_command, video_stream, write_media_artifact


class SegmentError(ValueError):
    retryable = False


def segment_revision(definition, config):
    return definition.execution.revision + "+ffmpeg:" + _renderer_revision()[1]


def store_segment(context, config, content, *, source, filename, mime, metadata):
    store = context.require_artifact_store()
    definition = context.definition
    role = next(iter(definition.artifact_contract.input_roles.values()))
    roles = {source.id: role}
    artifact = store.create(NodeArtifactWrite(
        artifact_type=definition.artifact_contract.primary_type, schema_id=definition.artifact_contract.schema_id,
        content=content, content_type=mime, filename=filename, input_artifact_ids=[source.id], input_artifact_roles=roles,
        metadata={"source": "node_executor_registry", "immutable": True, "experiment_id": context.experiment_id,
                  "request_hash": context.request_hash, "normalized_config": config, "definition_digest": definition.definition_digest,
                  "execution_mode": segment_revision(definition, config), "ffmpeg_version": _renderer_revision()[0],
                  "provider": "local", "model_alias": context.model_alias, "output_role": definition.artifact_contract.output_role,
                  **metadata}))
    store.flush()
    return NodeExecutionResult(
        output={"kind": artifact.type.lower(), "title": filename, "mimeType": mime, "url": store.content_url(artifact.id)},
        output_artifact_ids=[artifact.id], provider_request_id="local_" + context.request_hash[:20], cost_usd=0,
        metadata={"artifact_type": artifact.type, "schema_id": definition.artifact_contract.schema_id,
                  "input_artifact_ids": [source.id], "lineage_roles": roles, "retryable": False})


class VideoSegmentExecutor:
    runtime_revision = staticmethod(segment_revision)

    def execute(self, context, config, inputs):
        sources = [a for a in context.require_artifact_store().read_inputs(inputs) if a.type in {"Video", "FinalVideo", "VideoPreview"}]
        if len(sources) != 1:
            raise SegmentError("Video segment requires exactly one video")
        source = sources[0]; fps = int(config["output_fps"])
        start = round(float(config["start_seconds"]) * fps)
        count = round(float(config["duration_seconds"]) * fps)
        if count < 1:
            raise SegmentError("Video segment must contain at least one frame")
        with tempfile.TemporaryDirectory(prefix="frameflow-video-segment-") as temp:
            folder = Path(temp); path = write_media_artifact(folder, source, 0)
            try:
                info = probe_media(path); stream = video_stream(info)
                duration = float(stream.get("duration") or media_duration_seconds(info))
                available = round(duration * fps)
                padding = max(0, start + count - available)
                if start >= available or padding / fps > float(config["end_padding_seconds"]) + 1e-6:
                    raise SegmentError("Requested segment exceeds the video; only the declared end padding is allowed")
                filters = [f"fps={fps}"]
                if padding:
                    filters.append(f"tpad=stop_mode=clone:stop={padding}")
                filters.extend([f"trim=start_frame={start}:end_frame={start+count}", f"setpts=N/({fps}*TB)", "setsar=1"])
                output = folder / "segment.mp4"
                context.report_progress(25, "Extracting the video interval on frame boundaries")
                run_media_command(["ffmpeg", "-v", "error", "-y", "-i", str(path), "-map", "0:v:0", "-an",
                    "-vf", ",".join(filters), "-frames:v", str(count), "-r", str(fps), "-c:v", "libx264",
                    "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(output)], timeout=600)
                result_info = probe_media(output); result_stream = video_stream(result_info)
                if int(result_stream.get("nb_frames") or 0) != count:
                    raise SegmentError("Video segment did not produce the requested frame count")
            except (ValueError, RuntimeError) as exc:
                raise SegmentError(str(exc)) from exc
            return store_segment(context, config, output.read_bytes(), source=source, filename="video-segment.mp4", mime="video/mp4",
                metadata={"start_seconds": start/fps, "duration_ms": round(count/fps*1000), "frame_count": count,
                          "fps": fps, "padding_frames": padding, "audio_policy": "silent",
                          "width": int(result_stream['width']), "height": int(result_stream['height'])})


class AudioSegmentExecutor:
    runtime_revision = staticmethod(segment_revision)

    def execute(self, context, config, inputs):
        sources = [a for a in context.require_artifact_store().read_inputs(inputs) if a.type == "Audio"]
        if len(sources) != 1:
            raise SegmentError("Audio segment requires exactly one audio artifact")
        source = sources[0]; rate = 48000
        start = round(float(config["start_seconds"]) * rate)
        count = round(float(config["duration_seconds"]) * rate)
        if count < 1:
            raise SegmentError("Audio segment must contain at least one sample")
        with tempfile.TemporaryDirectory(prefix="frameflow-audio-segment-") as temp:
            folder = Path(temp); path = write_media_artifact(folder, source, 0)
            try:
                info = probe_media(path)
                if start + count > round(media_duration_seconds(info) * rate) + 1:
                    raise SegmentError("Requested segment exceeds the audio")
                output = folder / "segment.wav"
                context.report_progress(25, "Extracting the corresponding speech samples")
                run_media_command(["ffmpeg", "-v", "error", "-y", "-i", str(path), "-map", "0:a:0", "-vn",
                    "-af", f"aresample={rate},atrim=start_sample={start}:end_sample={start+count},asetpts=PTS-STARTPTS",
                    "-c:a", "pcm_s16le", "-ar", str(rate), str(output)], timeout=600)
                with wave.open(str(output)) as wav:
                    if wav.getnframes() != count:
                        raise SegmentError("Decoded audio is shorter than the requested interval")
                    channels = wav.getnchannels()
            except (ValueError, RuntimeError, wave.Error) as exc:
                raise SegmentError(str(exc)) from exc
            return store_segment(context, config, output.read_bytes(), source=source, filename="speech-segment.wav", mime="audio/wav",
                metadata={"start_seconds": start/rate, "duration_ms": round(count/rate*1000), "sample_count": count,
                          "sample_rate": rate, "channels": channels, "time_stretch": False})
