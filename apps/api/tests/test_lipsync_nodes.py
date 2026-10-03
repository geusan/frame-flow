import asyncio
import io
import json
import subprocess
import wave
from types import SimpleNamespace

import httpx
import pytest

from app import canvas_activities
from app.canvas_documents import canonicalize_canvas_document
from app.canvas_runs import create_canvas_run, execute_canvas_node
from app.database import SessionLocal
from app.domain import CanvasRunRequest, ExperimentRunRequest
from app.experiments import request_fingerprint, resolve_model
from app.media_preview import render_audio_wav, render_video_mp4
from app.nodes import node_registry
from app.providers_lipsync import FalLipSyncService
from app.providers_performance import MediaProviderError, ProviderMedia


def test_lipsync_request_billing_and_resume(monkeypatch):
    calls = []; remembered = []
    def handle(request):
        calls.append((request.method, str(request.url)))
        if request.method == 'POST':
            assert request.url.path == '/fal-ai/sync-lipsync/v2/pro'
            assert json.loads(request.content) == {'video_url':'https://v3.fal.media/video.mp4','audio_url':'https://v3.fal.media/audio.wav','sync_mode':'cut_off'}
            return httpx.Response(200,json={'request_id':'task_1'})
        if request.url.path.endswith('/status'):return httpx.Response(200,json={'status':'COMPLETED'})
        if request.url.host == 'queue.fal.run':return httpx.Response(200,json={'video':{'url':'https://v3.fal.media/result.mp4'}},headers={'x-fal-billable-units':'0.05'})
        if request.url.host == 'api.fal.ai':return httpx.Response(200,json={'prices':[{'endpoint_id':'fal-ai/sync-lipsync/v2/pro','unit_price':5,'unit':'minutes','currency':'USD'}]})
        assert 'authorization' not in request.headers
        return httpx.Response(200,content=b'result')
    service=FalLipSyncService(api_key='test',client=httpx.Client(transport=httpx.MockTransport(handle)))
    monkeypatch.setattr(service,'_upload',lambda content,mime,name:'https://v3.fal.media/'+('video.mp4' if mime=='video/mp4' else 'audio.wav'))
    kwargs=dict(video=b'v',audio=b'a',audio_content_type='audio/wav',timeout_seconds=30,remember=remembered.append,progress=lambda *_:None)
    result=service.synchronize(**kwargs,resume_id=None)
    assert result.content==b'result' and result.usage['calculated_cost_usd']==.25 and remembered==['task_1']
    calls.clear();service.synchronize(**kwargs,resume_id='task_1')
    assert all(method=='GET' for method,_ in calls)


def test_ambiguous_lipsync_submit_is_not_retried(monkeypatch):
    service=FalLipSyncService(api_key='test',client=httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(503))))
    monkeypatch.setattr(service,'_upload',lambda *a:'https://v3.fal.media/file')
    remembered=[]
    with pytest.raises(MediaProviderError) as error:
        service.synchronize(video=b'v',audio=b'a',audio_content_type='audio/wav',timeout_seconds=30,resume_id=None,remember=remembered.append,progress=lambda *_:None)
    assert error.value.retryable is False and remembered==[]


@pytest.fixture(scope='module')
def media():
    return render_video_mp4('0123456789abcdef',duration_seconds=2),render_audio_wav('abcdef',duration_seconds=2)


def upload(client,name,data,mime):
    response=client.post('/artifacts/upload',files={'file':(name,data,mime)})
    assert response.status_code==201,response.text
    return response.json()['artifact_id']


def test_contracts_and_segment_fingerprint(client):
    definitions={d['type_key']:d for d in client.get('/node-definitions').json()}
    for key in ['audio.segment','video.segment','video.lip_sync']:
        assert definitions[key]['editor']['kind']=='generic'
        assert node_registry.resolve_config(node_registry.get(key,1),{})
    with pytest.raises(ValueError):node_registry.resolve_config(node_registry.get('audio.segment',1),{'duration_seconds':0})
    with pytest.raises(ValueError):node_registry.resolve_config(node_registry.get('video.segment',1),{'start_seconds':-1})
    p=ExperimentRunRequest(canvas_id='c',node_id='n',node_key='audio.segment',model_alias='local.audio-segment',parameters={'start_seconds':0})
    model,exact=resolve_model(p.model_alias,p.node_key)
    assert request_fingerprint(p,model,exact)!=request_fingerprint(p.model_copy(update={'parameters':{'start_seconds':1}}),model,exact)
    assert definitions['video.lip_sync']['ports']['inputs'][1]['type']=='media.audio.v1'


@pytest.mark.parametrize('temporal',[False,True])
@pytest.mark.parametrize('kind',['video','audio','lip'])
def test_native_segments_and_lipsync_local_temporal_cache_lineage(client,monkeypatch,media,temporal,kind):
    monkeypatch.setattr(canvas_activities,'refresh_provider_environment',lambda:None)
    monkeypatch.setattr(canvas_activities.activity,'heartbeat',lambda *_:None)
    video,audio=media;calls=[]
    vid=upload(client,'source.mp4',video,'video/mp4');aud=upload(client,'source.wav',audio,'audio/wav')
    if kind=='video':
        key,alias,config,refs='video.segment','local.video-segment',{'start_seconds':.5,'duration_seconds':.75},[(vid,'Video','video')]
    elif kind=='audio':
        key,alias,config,refs='audio.segment','local.audio-segment',{'start_seconds':.5,'duration_seconds':.75},[(aud,'Audio','audio')]
    else:
        key,alias,config,refs='video.lip_sync','fal.video.lip_sync',{},[(vid,'Video','video'),(aud,'Audio','audio')]
        class Service:
            def synchronize(self,**kwargs):
                calls.append(kwargs);kwargs['remember']('known_task')
                return ProviderMedia(video,'video/mp4','known_task',{'calculated_cost_usd':.25,'cost_status':'provider_usage_calculated'})
            def close(self):pass
        monkeypatch.setattr('app.nodes.executors.lip_sync.FalLipSyncService',Service)
    nodes=[{'id':f'source-{i}','data':{'key':'asset.select','contractVersion':2,'config':{'artifact_id':a,'artifact_type':typ},'outputArtifactIds':[a]}} for i,(a,typ,_) in enumerate(refs)]
    nodes.append({'id':'target','data':{'key':key,'model':alias,'config':config}})
    edges=[{'id':str(i),'source':f'source-{i}','target':'target','sourceHandle':'artifact','targetHandle':port} for i,(_,_,port) in enumerate(refs)]
    saved=client.post('/canvases',json={'name':'Lipsync flow','document':canonicalize_canvas_document(nodes,edges)}).json()
    with SessionLocal() as db:run_id=create_canvas_run(db,CanvasRunRequest(canvas_id=saved['id'],canvas_revision=saved['revision'],target_node_id='target')).id
    result=asyncio.run(canvas_activities.execute_canvas_node_activity(run_id,'target')) if temporal else execute_canvas_node(run_id,'target')
    artifact=client.get('/artifacts/'+result['artifact_ids'][0]).json();data=client.get('/artifacts/'+artifact['id']+'/content').content
    assert artifact['input_artifact_ids']==[a for a,_,_ in refs]
    assert artifact['metadata']['definition_digest']==node_registry.get(key,1).definition_digest
    assert '+ffmpeg:' in artifact['metadata']['execution_mode']
    if kind=='audio':
        with wave.open(io.BytesIO(data)) as wav:
            assert wav.getframerate()==48000 and wav.getnframes()==36000
    else:
        p=subprocess.run(['ffprobe','-v','error','-show_entries','stream=codec_type,nb_frames','-of','json','pipe:0'],input=data,capture_output=True,check=True)
        streams=json.loads(p.stdout)['streams'];assert len(streams)==1 and streams[0]['codec_type']=='video'
        assert int(streams[0]['nb_frames'])==(18 if kind=='video' else 48)
    assert execute_canvas_node(run_id,'target')['artifact_ids']==result['artifact_ids']
    assert len(calls)==(1 if kind=='lip' else 0)


def test_segment_padding_is_explicit_and_audio_rejects_out_of_range(client,media):
    video,audio=media;vid=upload(client,'v.mp4',video,'video/mp4');aud=upload(client,'a.wav',audio,'audio/wav')
    p={'canvas_id':'c','node_id':'n','node_key':'video.segment','model_alias':'local.video-segment',
       'inputs':[{'type':'Video','artifact_ids':[vid]}],'parameters':{'start_seconds':1,'duration_seconds':1+1/24}}
    result=client.post('/experiments',json=p).json();assert result['status']=='FAILED' and 'padding' in result['error']
    p['parameters']['end_padding_seconds']=.1
    result=client.post('/experiments',json=p).json();assert result['status']=='SUCCEEDED',result.get('error')
    artifact=client.get('/artifacts/'+result['output_artifact_ids'][0]).json();assert artifact['metadata']['padding_frames']==1 and artifact['metadata']['frame_count']==25
    p={'canvas_id':'c','node_id':'a','node_key':'audio.segment','model_alias':'local.audio-segment','inputs':[{'type':'Audio','artifact_ids':[aud]}],
       'parameters':{'start_seconds':1,'duration_seconds':2}}
    assert client.post('/experiments',json=p).json()['status']=='FAILED'


def test_lipsync_workflow_publish_freezes_reachable_segment_contracts(client,media):
    vid=upload(client,'v.mp4',media[0],'video/mp4');aud=upload(client,'a.wav',media[1],'audio/wav')
    nodes=[{'id':ident,'data':{'key':'asset.select','contractVersion':2,'config':{'artifact_id':aid,'artifact_type':typ},'outputArtifactIds':[aid]}} for ident,aid,typ in [('video',vid,'Video'),('audio',aud,'Audio')]]
    nodes.extend([{'id':'vcut','data':{'key':'video.segment','model':'local.video-segment','config':{'duration_seconds':2}}},
                  {'id':'acut','data':{'key':'audio.segment','model':'local.audio-segment','config':{'duration_seconds':2}}},
                  {'id':'sync','data':{'key':'video.lip_sync','model':'fal.video.lip_sync'}},
                  {'id':'unused','data':{'key':'audio.segment','model':'local.audio-segment'}},
                  {'id':'memo','data':{'key':'utility.sticky','configText':'Keep final speech timing'}}])
    edges=[{'id':str(i),'source':s,'target':t,'sourceHandle':sp,'targetHandle':tp} for i,(s,t,sp,tp) in enumerate([
        ('video','vcut','artifact','video'),('audio','acut','artifact','audio'),('vcut','sync','video','video'),('acut','sync','audio','audio')])]
    wf=client.post('/workflows',json={'name':'Audio-first lip sync'}).json();canvas=client.get('/canvases/'+wf['draft_canvas_id']).json()
    contract={'schema_version':'workflow.contract.draft.v1','inputs':[{'key':'start','label':'Start','type':'number','default':0}],
        'bindings':[{'target':{'node_id':nid,'path':'/config/start_seconds'},'value':{'kind':'input','key':'start'}} for nid in ['vcut','acut']],
        'outputs':[{'key':'video','label':'Lip-synced video','node_id':'sync','port_key':'video','port_type':'media.video.v1','primary':True}]}
    saved=client.put('/canvases/'+canvas['id'],json={'name':canvas['name'],'document':canonicalize_canvas_document(nodes,edges),'draft_contract':contract,'expected_revision':canvas['revision']})
    assert saved.status_code==200,saved.text
    published=client.post('/workflows/'+wf['id']+'/publish',json={'expected_canvas_revision':saved.json()['revision']})
    assert published.status_code==201,published.text
    version=published.json();assert {n['id'] for n in version['graph']['nodes']}=={'video','audio','vcut','acut','sync'}
    assert version['warnings']==['Unused Canvas Node excluded: unused']
    assert len(client.get('/workflows/'+wf['id']+'/versions/1/annotations').json())==1
