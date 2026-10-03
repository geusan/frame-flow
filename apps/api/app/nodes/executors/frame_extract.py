from __future__ import annotations

import hashlib
import tempfile
from functools import lru_cache
from pathlib import Path

from ..contracts import NodeArtifactWrite, NodeExecutionResult
from .media_tools import media_duration_seconds, probe_media, run_media_command, video_stream, write_media_artifact


class FrameExtractionError(ValueError):
    retryable = False


@lru_cache(maxsize=1)
def _renderer_revision():
    version = run_media_command(["ffmpeg", "-version"]).stdout.splitlines()[0]
    return version, hashlib.sha256(version.encode()).hexdigest()[:8]


class FrameExtractExecutor:
    @staticmethod
    def runtime_revision(definition, resolved_config):
        return definition.execution.revision + "+ffmpeg:" + _renderer_revision()[1]

    def execute(self, context, config, typed_inputs):
        store = context.require_artifact_store()
        sources = [a for a in store.read_inputs(typed_inputs) if a.type in {"Video", "FinalVideo", "VideoPreview"}]
        if len(sources) != 1:
            raise FrameExtractionError("Frame extraction requires exactly one Video artifact")
        source = sources[0]
        timestamp = float(config["timestamp_seconds"])
        with tempfile.TemporaryDirectory(prefix="frameflow-frame-") as temp:
            folder = Path(temp)
            path = write_media_artifact(folder, source, 0)
            try:
                info = probe_media(path)
                video_stream(info)
                duration = media_duration_seconds(info)
                if timestamp >= duration:
                    raise FrameExtractionError("Frame timestamp must be before the end of the video")
                output = folder / "frame.png"
                context.report_progress(25, "Extracting the reference frame")
                run_media_command(["ffmpeg", "-v", "error", "-y", "-ss", str(timestamp), "-i", str(path),
                                   "-map", "0:v:0", "-frames:v", "1", "-vf", "scale=trunc(iw*sar):ih,setsar=1", str(output)])
                if not output.exists():
                    raise FrameExtractionError("No video frame exists at the requested time")
                frame = video_stream(probe_media(output))
            except (ValueError, RuntimeError) as exc:
                raise FrameExtractionError(str(exc)) from exc
            roles = {source.id: "source_video"}
            metadata = {"source": "node_executor_registry", "immutable": True,
                        "experiment_id": context.experiment_id, "request_hash": context.request_hash,
                        "definition_digest": context.definition.definition_digest,
                        "execution_mode": self.runtime_revision(context.definition, config),
                        "ffmpeg_version": _renderer_revision()[0], "provider": "local", "model_alias": context.model_alias,
                        "normalized_config": config, "timestamp_seconds": timestamp,
                        "selection": "first_decoded_frame_at_or_after_timestamp", "source_duration_ms": round(duration * 1000),
                        "width": int(frame["width"]), "height": int(frame["height"]), "output_role": "extracted_frame"}
            artifact = store.create(NodeArtifactWrite(
                artifact_type="Image", schema_id=context.definition.artifact_contract.schema_id,
                content=output.read_bytes(), content_type="image/png", filename="reference-frame.png",
                input_artifact_ids=[source.id], input_artifact_roles=roles, metadata=metadata))
            store.flush()
        return NodeExecutionResult(
            output={"kind": "image", "title": f"Reference frame · {timestamp:g}s", "mimeType": "image/png", "url": store.content_url(artifact.id)},
            output_artifact_ids=[artifact.id], provider_request_id="local_" + context.request_hash[:20], cost_usd=0,
            metadata={"artifact_type": "Image", "schema_id": context.definition.artifact_contract.schema_id,
                      "input_artifact_ids": [source.id], "lineage_roles": roles, "retryable": False})
