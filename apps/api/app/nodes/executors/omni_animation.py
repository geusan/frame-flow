from __future__ import annotations

from ...provider_credentials import provider_value

import io
import os
import tempfile
from pathlib import Path

from PIL import Image

from ...media_preview import render_video_mp4
from ...providers_omni import GoogleOmniAnimationService, OMNI_VERTEX_MODEL, animation_request
from ...providers_performance import MediaProviderError, ProviderMedia
from ..contracts import NodeArtifactWrite, NodeExecutionResult
from .frame_extract import _renderer_revision
from .media_tools import media_duration_seconds, probe_media, video_stream


def animation_timing(info, requested):
    duration = media_duration_seconds(info)
    video_duration = float(video_stream(info).get('duration') or duration)
    if video_duration < requested-.25 or video_duration > requested+1 or duration > requested+1:
        raise MediaProviderError('Omni animation duration is outside the requested -250ms/+1000ms bounds')
    return {'duration_ms':round(duration*1000),'video_duration_ms':round(video_duration*1000),
            'requested_duration_ms':round(requested*1000),'provider_padding_ms':max(0,round((video_duration-requested)*1000))}


class OmniAnimationExecutor:
    @staticmethod
    def runtime_revision(definition, config):
        return definition.execution.revision + ':' + provider_value('GENERATION_PROVIDER_MODE','live') + '+ffmpeg:' + _renderer_revision()[1]

    def execute(self, context, config, inputs):
        if context.model_alias != 'google.video.omni.vertex':
            raise MediaProviderError('Image animation V2 requires Vertex Omni')
        if not context.prompt.strip():
            raise MediaProviderError('Image animation requires a connected motion prompt')
        store=context.require_artifact_store(); artifacts=store.read_inputs(inputs)
        images=[a for a in artifacts if a.type=='Image']
        if len(images)!=1 or any(a.type not in {'Image','Prompt','Text'} for a in artifacts):
            raise MediaProviderError('Image animation accepts exactly one image and prompt; video/audio references are not allowed')
        image=images[0]
        if image.content_type not in {'image/png','image/jpeg','image/webp'} or len(image.data)>30*1024*1024:
            raise MediaProviderError('Starting image must be PNG/JPEG/WebP up to 30 MB')
        try:
            with Image.open(io.BytesIO(image.data)) as check:check.verify()
        except (OSError,ValueError) as exc:
            raise MediaProviderError('Starting image is invalid') from exc
        payload=animation_request(prompt=context.prompt,image=image.data,image_content_type=image.content_type,
            resolution=config['resolution'],aspect_ratio=config['aspect_ratio'],duration_seconds=config['duration_seconds'])
        fixture=provider_value('GENERATION_PROVIDER_MODE','live')!='live'
        if fixture:
            result=ProviderMedia(render_video_mp4(context.request_hash,config['duration_seconds']),'video/mp4',
                'fixture_'+context.request_hash[:20],{'cost_status':'fixture'})
        else:
            service=GoogleOmniAnimationService();tasks=context.require_provider_tasks()
            try:
                ident=tasks.claim('google','omni-image-animation',resumable=True)
                result=service.generate(payload,timeout_seconds=config['timeout_seconds'],resume_id=ident,
                    remember=lambda value:tasks.remember('google','omni-image-animation',value),progress=context.report_progress)
            finally:service.close()
        with tempfile.TemporaryDirectory(prefix='frameflow-omni-animation-') as temp:
            path=Path(temp)/'result.mp4';path.write_bytes(result.content)
            info=probe_media(path);stream=video_stream(info);timing=animation_timing(info,config['duration_seconds'])
        roles={a.id:('first_frame' if a.type=='Image' else 'motion_prompt') for a in artifacts}
        artifact=store.create(NodeArtifactWrite(artifact_type='Video',schema_id=context.definition.artifact_contract.schema_id,
            content=result.content,content_type='video/mp4',filename='omni-image-animation.mp4',input_artifact_ids=list(roles),input_artifact_roles=roles,
            metadata={'source':'node_executor_registry','immutable':True,'experiment_id':context.experiment_id,'request_hash':context.request_hash,
                'definition_digest':context.definition.definition_digest,'execution_mode':self.runtime_revision(context.definition,config),
                'provider':'google','model_alias':context.model_alias,'exact_model_id':OMNI_VERTEX_MODEL,'provider_request_id':result.request_id,
                'normalized_config':config,'ffmpeg_version':_renderer_revision()[0],'width':int(stream['width']),'height':int(stream['height']),
                'task':'image_to_video','channel':'vertex','region':'global','image_input_mode':'first_frame',
                'audio_policy':'native_provider_audio; replace_with_fixed_speech_downstream','duration_control':'prompted_and_validated',
                'fixture':fixture,'usage':result.usage,'cost_status':result.usage['cost_status'],
                'output_role':context.definition.artifact_contract.output_role,**timing}))
        store.flush()
        return NodeExecutionResult(output={'kind':'video','title':'Omni image animation','url':store.content_url(artifact.id),'mimeType':'video/mp4'},
            output_artifact_ids=[artifact.id],provider_request_id=result.request_id,cost_usd=0.0,
            metadata={'artifact_type':'Video','schema_id':context.definition.artifact_contract.schema_id,'input_artifact_ids':list(roles),
                'lineage_roles':roles,'exact_model_id':OMNI_VERTEX_MODEL,'usage':result.usage,'retryable':False})
