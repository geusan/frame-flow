from __future__ import annotations

import io
import os
import tempfile
from pathlib import Path

from PIL import Image

from ...media_preview import render_video_mp4
from ...providers_omni import GoogleOmniEditService, OMNI_VERTEX_MODEL, edit_request
from ...providers_performance import MediaProviderError, ProviderMedia
from .media_tools import media_duration_seconds, probe_media, run_media_command, video_stream, write_media_artifact
from .performance_transfer import _input, _runtime_revision, _store


class PerformanceEditExecutor:
    @staticmethod
    def runtime_revision(definition, config):
        return _runtime_revision(definition) + ':' + os.getenv('GENERATION_PROVIDER_MODE', 'live')

    def execute(self, context, config, inputs):
        if context.model_alias != 'google.video.omni.vertex':
            raise MediaProviderError('Performance edit V2 requires the Vertex Omni capability')
        store = context.require_artifact_store()
        artifacts = store.read_inputs(inputs)
        image = _input(artifacts, {'Image'}, 'Character image')
        video = _input(artifacts, {'Video', 'FinalVideo'}, 'Source performance')
        if image.content_type not in {'image/png', 'image/jpeg', 'image/webp'} or len(image.data) > 30 * 1024 * 1024:
            raise MediaProviderError('Character image must be PNG/JPEG/WebP up to 30 MB')
        try:
            with Image.open(io.BytesIO(image.data)) as check:
                check.verify()
        except (OSError, ValueError) as exc:
            raise MediaProviderError('Character image is invalid') from exc
        with tempfile.TemporaryDirectory(prefix='frameflow-performance-edit-') as temp:
            folder = Path(temp)
            source = write_media_artifact(folder, video, 0)
            info = probe_media(source)
            duration = float(video_stream(info).get('duration') or media_duration_seconds(info))
            if not 3 <= duration <= 10.001:
                raise MediaProviderError('Omni source performance must be 3–10 seconds; split longer videos first')
            normalized = folder / 'source.mp4'
            run_media_command(['ffmpeg','-v','error','-y','-i',str(source),'-map','0:v:0','-an',
                '-c:v','libx264','-preset','veryfast','-crf','18','-pix_fmt','yuv420p','-movflags','+faststart',str(normalized)])
            payload = edit_request(prompt=config['prompt'], image=image.data, image_content_type=image.content_type,
                                   video=normalized.read_bytes(), resolution=config['resolution'])
            fixture = os.getenv('GENERATION_PROVIDER_MODE', 'live') != 'live'
            if fixture:
                result = ProviderMedia(render_video_mp4(context.request_hash, duration), 'video/mp4',
                                       'fixture_' + context.request_hash[:20], {'cost_status': 'fixture'})
            else:
                service = GoogleOmniEditService()
                tasks = context.require_provider_tasks()
                try:
                    ident = tasks.claim('google', 'omni-performance-edit', resumable=True)
                    result = service.edit(payload, timeout_seconds=config['timeout_seconds'], resume_id=ident,
                        remember=lambda value: tasks.remember('google', 'omni-performance-edit', value), progress=context.report_progress)
                finally:
                    service.close()
            raw = folder / 'provider.mp4'; raw.write_bytes(result.content)
            output_info = probe_media(raw)
            output_duration = float(video_stream(output_info).get('duration') or media_duration_seconds(output_info))
            if abs(output_duration-duration) > .25:
                raise MediaProviderError('Omni edit changed the source duration by more than 250 ms')
            silent = folder / 'performance.mp4'
            run_media_command(['ffmpeg','-v','error','-y','-i',str(raw),'-map','0:v:0','-c:v','copy','-an','-movflags','+faststart',str(silent)])
            return _store(context, config, silent.read_bytes(), kind='video', mime='video/mp4', filename='omni-performance.mp4',
                inputs=[image.id, video.id], roles={image.id:'character_identity', video.id:'driving_performance'},
                request_id=result.request_id,
                metadata={'provider':'google','exact_model_id':OMNI_VERTEX_MODEL,'provider_request_id':result.request_id,
                    'source_duration_ms':round(duration*1000),'duration_ms':round(output_duration*1000),
                    'execution_mode':self.runtime_revision(context.definition,config),'renderer_revision':'ffmpeg-silent-performance.v2',
                    'audio_policy':'silent','task':'edit','channel':'vertex','region':'global',
                    'fixture':fixture,'cost_status':result.usage['cost_status'],'usage':result.usage})
