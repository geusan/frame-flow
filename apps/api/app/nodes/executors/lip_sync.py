from __future__ import annotations

import tempfile
from fractions import Fraction
from pathlib import Path

from ...providers_lipsync import FAL_LIPSYNC_MODEL, FalLipSyncService
from ...providers_performance import MediaProviderError
from ..contracts import NodeArtifactWrite, NodeExecutionResult
from .frame_extract import _renderer_revision
from .media_tools import media_duration_seconds, probe_media, run_media_command, video_stream, write_media_artifact


class LipSyncExecutor:
    @staticmethod
    def runtime_revision(definition, config):
        return definition.execution.revision + "+ffmpeg:" + _renderer_revision()[1]

    def execute(self, context, config, inputs):
        store = context.require_artifact_store(); artifacts = store.read_inputs(inputs)
        videos = [a for a in artifacts if a.type in {"Video", "FinalVideo"}]
        audios = [a for a in artifacts if a.type == "Audio"]
        if len(videos) != 1 or len(audios) != 1:
            raise MediaProviderError("Lip sync requires one matched Video and Audio segment")
        video, audio = videos[0], audios[0]
        with tempfile.TemporaryDirectory(prefix="frameflow-lipsync-") as temp:
            folder = Path(temp); video_path = write_media_artifact(folder, video, 0); audio_path = write_media_artifact(folder, audio, 1)
            stream = video_stream(probe_media(video_path)); fps = float(Fraction(str(stream.get('avg_frame_rate') or stream.get('r_frame_rate'))))
            vd = float(stream.get('duration') or media_duration_seconds(probe_media(video_path)))
            ad = media_duration_seconds(probe_media(audio_path))
            if not 1 <= ad <= 300 or not 15 <= fps <= 60 or abs(vd-ad) > 1/fps + .005:
                raise MediaProviderError("Lip-sync inputs must have matching durations (1–300s) and a 15–60fps video")
            count = round(ad * fps)
            normalized_audio = folder/'speech.wav'
            run_media_command(['ffmpeg','-v','error','-y','-i',str(audio_path),'-vn','-c:a','pcm_s16le','-ar','48000',str(normalized_audio)])
            tasks = context.require_provider_tasks(); service = FalLipSyncService()
            try:
                task = tasks.claim('fal', 'lip-sync', resumable=True)
                result = service.synchronize(video=video.data, audio=normalized_audio.read_bytes(), audio_content_type='audio/wav',
                    timeout_seconds=config['timeout_seconds'], resume_id=task,
                    remember=lambda ident: tasks.remember('fal', 'lip-sync', ident), progress=context.report_progress)
            finally:
                service.close()
            raw = folder/'provider.mp4'; raw.write_bytes(result.content)
            rd = media_duration_seconds(probe_media(raw))
            if abs(rd-ad) > .12:
                raise MediaProviderError("Lip-sync result changed the segment duration by more than 120ms")
            output = folder/'lip-synced.mp4'
            # Normalize only the frame clock. The full unchanged speech track is muxed downstream.
            run_media_command(['ffmpeg','-v','error','-y','-i',str(raw),'-map','0:v:0','-an',
                '-vf',f'fps={fps:g},tpad=stop_mode=clone:stop_duration=0.12,trim=end_frame={count},setpts=N/({fps:g}*TB)',
                '-frames:v',str(count),'-r',f'{fps:g}','-c:v','libx264','-preset','veryfast','-crf','18','-pix_fmt','yuv420p','-movflags','+faststart',str(output)],timeout=300)
            out_stream = video_stream(probe_media(output))
            if int(out_stream.get('nb_frames') or 0) != count:
                raise MediaProviderError('Lip-sync output frame count mismatch')
            roles = {video.id:'source_performance', audio.id:'target_speech'}
            artifact = store.create(NodeArtifactWrite(artifact_type='Video', schema_id=context.definition.artifact_contract.schema_id,
                content=output.read_bytes(),content_type='video/mp4',filename='lip-synced.mp4',input_artifact_ids=[video.id,audio.id],input_artifact_roles=roles,
                metadata={'source':'node_executor_registry','immutable':True,'experiment_id':context.experiment_id,'request_hash':context.request_hash,
                          'definition_digest':context.definition.definition_digest,'execution_mode':self.runtime_revision(context.definition,config),
                          'ffmpeg_version':_renderer_revision()[0],'provider':'fal','model_alias':context.model_alias,'exact_model_id':FAL_LIPSYNC_MODEL,
                          'provider_request_id':result.request_id,'normalized_config':config,'sync_mode':'cut_off','duration_ms':round(count/fps*1000),
                          'frame_count':count,'fps':fps,'audio_policy':'silent_for_separate_mux','usage':result.usage,
                          'output_role':context.definition.artifact_contract.output_role}))
            store.flush()
            return NodeExecutionResult(output={'kind':'video','title':'Lip-synced performance','url':store.content_url(artifact.id),'mimeType':'video/mp4'},
                output_artifact_ids=[artifact.id],provider_request_id=result.request_id,cost_usd=float(result.usage.get('calculated_cost_usd') or 0),
                metadata={'artifact_type':'Video','schema_id':context.definition.artifact_contract.schema_id,'input_artifact_ids':[video.id,audio.id],
                          'lineage_roles':roles,'retryable':False,'usage':result.usage})
