from __future__ import annotations

from ...provider_credentials import provider_value

import io
import os
import tempfile
from fractions import Fraction
from pathlib import Path

from PIL import Image

from ...media_preview import render_video_mp4
from ...providers_minimax import MINIMAX_H3_MODEL, MiniMaxVideoService, reference_request
from ...providers_performance import MediaProviderError, ProviderMedia
from ..contracts import NodeArtifactWrite, NodeExecutionResult
from .frame_extract import _renderer_revision
from .media_tools import media_duration_seconds, probe_media, video_stream, write_media_artifact


REFERENCE_PORTS = {"images": ("Image", "image", "identity_appearance_reference"), "videos": ("Video", "video", "motion_reference"), "audios": ("Audio", "audio", "speech_reference")}


def ordered_references(store, inputs):
    """Edge order within a port; repeated IDs use their first occurrence, as the artifact store does."""
    grouped = {}
    for port, (typ, _, _) in REFERENCE_PORTS.items():
        ids = []
        for item in inputs:
            if item.get("target_port") != port and (item.get("target_port") or item.get("type") != typ):
                continue
            for aid in [*(item.get("artifact_ids") or []), *([item["artifact_id"]] if item.get("artifact_id") else [])]:
                if aid not in ids:
                    ids.append(aid)
        grouped[port] = [store.read(aid) for aid in ids]
        if any(a.type not in ({"Video", "FinalVideo"} if typ == "Video" else {typ}) for a in grouped[port]):
            raise MediaProviderError(f"Invalid artifact type for {port}")
    if not 1 <= len(grouped["images"]) <= 9 or len(grouped["videos"]) > 3 or len(grouped["audios"]) > 3 or sum(map(len, grouped.values())) > 12:
        raise MediaProviderError("References require 1–9 images, at most 3 videos, 3 audios and 12 files total")
    return grouped


def validate_references(grouped):
    media = []
    with tempfile.TemporaryDirectory(prefix="frameflow-reference-validation-") as temp:
        folder = Path(temp)
        for port, artifacts in grouped.items():
            kind = REFERENCE_PORTS[port][1]; total_duration = 0.0
            for index, artifact in enumerate(artifacts):
                mime = artifact.content_type.split(";", 1)[0].lower()
                limit = {"image": 30, "video": 50, "audio": 15}[kind] * 1024 * 1024
                if not artifact.data or len(artifact.data) > limit:
                    raise MediaProviderError(f"{kind} reference exceeds the provider file limit")
                if kind == "image":
                    if mime not in {"image/png", "image/jpeg", "image/webp"}:
                        raise MediaProviderError("Image references must be PNG, JPEG or WEBP")
                    with Image.open(io.BytesIO(artifact.data)) as image:
                        width, height = image.size
                        image.verify()
                else:
                    allowed = {"video/mp4", "video/quicktime"} if kind == "video" else {"audio/wav", "audio/x-wav", "audio/mpeg"}
                    if mime not in allowed:
                        raise MediaProviderError(f"Unsupported {kind} reference format")
                    path = write_media_artifact(folder, artifact, index)
                    info = probe_media(path); duration = media_duration_seconds(info)
                    if not 2 <= duration <= 15.001:
                        raise MediaProviderError(f"Each {kind} reference must be 2–15 seconds; extract a segment first")
                    total_duration += duration
                    if kind == "video":
                        stream = video_stream(info); width, height = int(stream['width']), int(stream['height'])
                        fps = float(Fraction(stream.get('avg_frame_rate') or stream.get('r_frame_rate') or '0'))
                        if stream.get('codec_name') not in {'h264', 'hevc'} or not 23.975 <= fps <= 60:
                            raise MediaProviderError("Video reference must use H.264/H.265 at 23.976–60fps")
                        if any(s.get('codec_type') == 'audio' and s.get('codec_name') not in {'aac', 'mp3'} for s in info['streams']):
                            raise MediaProviderError("Video reference audio must use AAC or MP3")
                    elif not any(s.get('codec_type') == 'audio' for s in info['streams']):
                        raise MediaProviderError("Audio reference has no audio stream")
                if kind in {"image", "video"} and (not 256 <= min(width, height) or max(width, height) > 5760 or not .4 <= width / height <= 2.5):
                    raise MediaProviderError("Image/video references require 256–5760px and an aspect ratio of 0.4–2.5")
                media.append((kind, 'audio/wav' if mime == 'audio/x-wav' else mime, artifact.data))
            if total_duration > 15.001:
                raise MediaProviderError(f"Combined {kind} reference duration exceeds 15 seconds")
    return media


class ReferenceVideoExecutor:
    @staticmethod
    def runtime_revision(definition, config):
        return definition.execution.revision + ':' + provider_value('GENERATION_PROVIDER_MODE', 'live') + '+ffmpeg:' + _renderer_revision()[1]

    def result_timing(self, info, config):
        duration = media_duration_seconds(info)
        if abs(duration-config['duration_seconds']) > .25:
            raise MediaProviderError('MiniMax result duration differs from the requested duration by more than 250ms')
        return {'duration_ms': round(duration*1000)}

    def execute(self, context, config, inputs):
        if context.model_alias != 'minimax.video.h3':
            raise MediaProviderError("This reference generation contract supports MiniMax H3")
        store = context.require_artifact_store(); grouped = ordered_references(store, inputs)
        try:
            media = validate_references(grouped)
        except MediaProviderError:
            raise
        except (OSError, ValueError, RuntimeError, ZeroDivisionError) as exc:
            raise MediaProviderError("Reference media could not be validated; check the input files") from exc
        payload = reference_request(prompt=context.prompt, resolution=config['resolution'], duration=config['duration_seconds'], ratio=config['aspect_ratio'], media=media)
        fixture = provider_value('GENERATION_PROVIDER_MODE', 'live') != 'live'
        if fixture:
            result = ProviderMedia(render_video_mp4(context.request_hash, config['duration_seconds']), 'video/mp4', 'fixture_' + context.request_hash[:20], {'cost_status': 'fixture'})
        else:
            service = MiniMaxVideoService()
            tasks = context.require_provider_tasks()
            try:
                ident = tasks.claim('minimax', 'reference-video', resumable=True)
                result = service.generate(payload, timeout_seconds=config['timeout_seconds'], resume_id=ident,
                    remember=lambda value: tasks.remember('minimax', 'reference-video', value), progress=context.report_progress)
            finally:
                service.close()
        with tempfile.TemporaryDirectory(prefix='frameflow-reference-result-') as temp:
            path = Path(temp)/'result.mp4'; path.write_bytes(result.content)
            info = probe_media(path); stream = video_stream(info)
            video_info = {**self.result_timing(info, config), 'width': int(stream['width']), 'height': int(stream['height']), 'has_audio': any(s.get('codec_type') == 'audio' for s in info['streams'])}
        ordered = {port: [a.id for a in artifacts] for port, artifacts in grouped.items()}
        roles = {a.id: REFERENCE_PORTS[port][2] for port, artifacts in grouped.items() for a in artifacts}
        artifact = store.create(NodeArtifactWrite(artifact_type='Video', schema_id=context.definition.artifact_contract.schema_id,
            content=result.content, content_type='video/mp4', filename='minimax-h3-reference.mp4', input_artifact_ids=list(roles), input_artifact_roles=roles,
            metadata={'source':'node_executor_registry','immutable':True,'experiment_id':context.experiment_id,'request_hash':context.request_hash,
                      'definition_digest':context.definition.definition_digest,'execution_mode':self.runtime_revision(context.definition,config),
                      'provider':'minimax','model_alias':context.model_alias,'exact_model_id':MINIMAX_H3_MODEL,'provider_request_id':result.request_id,
                      'normalized_config':config,'ordered_reference_artifact_ids':ordered,'reference_mode':'reference_to_video',
                      'audio_policy':'native_provider_audio; replace_with_fixed_speech_downstream','fixture':fixture,'usage':result.usage,
                      'cost_status':result.usage['cost_status'],'output_role':context.definition.artifact_contract.output_role,**video_info}))
        store.flush()
        return NodeExecutionResult(output={'kind':'video','title':'MiniMax H3 reference video','url':store.content_url(artifact.id),'mimeType':'video/mp4'},
            output_artifact_ids=[artifact.id],provider_request_id=result.request_id,cost_usd=0.0,
            metadata={'artifact_type':'Video','schema_id':context.definition.artifact_contract.schema_id,'input_artifact_ids':list(roles),
                      'lineage_roles':roles,'exact_model_id':MINIMAX_H3_MODEL,'usage':result.usage,'retryable':False})


class PaddedReferenceVideoExecutor(ReferenceVideoExecutor):
    """V2 keeps provider media intact and records its bounded native tail padding."""

    def result_timing(self, info, config):
        duration = media_duration_seconds(info)
        requested = float(config['duration_seconds'])
        video_duration = float(video_stream(info).get('duration') or duration)
        if video_duration < requested - .25 or video_duration > requested + 1.0 or duration > requested + 1.0:
            raise MediaProviderError('MiniMax result exceeds the V2 duration bounds (-250ms / +1000ms)')
        return {'duration_ms': round(duration*1000), 'requested_duration_ms': round(requested*1000),
                'video_duration_ms': round(video_duration*1000), 'provider_padding_ms': max(0, round((video_duration-requested)*1000)),
                'duration_policy': 'provider_media_with_up_to_1000ms_tail_padding'}
