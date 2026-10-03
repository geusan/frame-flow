import asyncio
import base64
import io
import json
from types import SimpleNamespace

import httpx
import pytest
from PIL import Image

from app import canvas_activities
from app.canvas_documents import canonicalize_canvas_document
from app.canvas_runs import create_canvas_run, execute_canvas_node
from app.database import SessionLocal
from app.domain import CanvasRunRequest, ExperimentRunRequest
from app.experiments import request_fingerprint, resolve_model
from app.media_preview import render_audio_wav, render_video_mp4
from app.nodes import node_registry
from app.nodes.executors.omni_animation import animation_timing
from app.providers_google import GoogleProviderConfig
from app.providers_omni import GoogleOmniAnimationService, OMNI_VERTEX_MODEL, animation_request
from app.providers_performance import MediaProviderError, ProviderMedia


def png():
    stream=io.BytesIO();Image.new('RGB',(256,256),'pink').save(stream,format='PNG');return stream.getvalue()


def upload(client,name,data,mime):
    r=client.post('/artifacts/upload',files={'file':(name,data,mime)});assert r.status_code==201,r.text;return r.json()['artifact_id']


def payload():
    return animation_request(prompt='Turn the left palm up.',image=png(),image_content_type='image/png',resolution='1080p',aspect_ratio='9:16',duration_seconds=10)


def test_request_is_image_and_text_only_with_first_frame_and_duration(monkeypatch):
    p=payload();assert [v['type'] for v in p['input']]==['image','text']
    assert '<FIRST_FRAME>@Image1' in p['input'][1]['text'] and '10-second' in p['input'][1]['text']
    assert '<VIDEO_' not in json.dumps(p) and 'Audio 1' not in json.dumps(p)
    assert p['generation_config']=={'video_config':{'task':'image_to_video'}}
    assert p['response_format']==[{'type':'video','resolution':'1080p','aspect_ratio':'9:16'}]
    monkeypatch.setattr('app.providers_omni.MAX_BYTES',2)
    with pytest.raises(MediaProviderError,match='64 MB'):payload()


def test_new_contract_preserves_veo_and_source_edit_versions(client):
    v1,v2=[node_registry.get('video.animate_image',v) for v in [1,2]]
    assert v1.ports==v2.ports and v1.definition_digest!=v2.definition_digest
    assert v1.execution.model_alias=='google.video.quality'
    assert v1.config_schema['properties']['duration_seconds']['enum']==[4,6,8]
    assert v2.execution.model_alias=='google.video.omni.vertex' and v2.editor.kind=='generic'
    assert node_registry.get('video.performance_transfer',2).execution.executor=='performance-edit'
    for config in [{'duration_seconds':2},{'duration_seconds':11},{'duration_seconds':4.5},{'seed':1},{'output_count':2}]:
        with pytest.raises(ValueError):node_registry.resolve_config(v2,config)
    assert node_registry.resolve_config(v2,{})=={'resolution':'1080p','aspect_ratio':'9:16','duration_seconds':8,'timeout_seconds':1800}
    assert any(d['type_key']==v2.type_key and d['contract_version']==2 for d in client.get('/node-definitions').json())


def test_async_animation_resumes_same_interaction_and_records_task(monkeypatch):
    calls=[];saved=[];context=[]
    monkeypatch.setattr('app.providers_omni.record_provider_result',lambda *a,**kw:context.append(kw['context']))
    def handler(req):
        calls.append(req.method)
        if req.method=='POST':
            assert json.loads(req.content)==payload();return httpx.Response(200,json={'id':'animation_1','status':'in_progress'})
        return httpx.Response(200,json={'id':'animation_1','status':'completed','output_video':{'data':base64.b64encode(b'video').decode()}})
    s=GoogleOmniAnimationService(config=GoogleProviderConfig(project='test',credentials=SimpleNamespace(valid=True,token='secret')),
        client=httpx.Client(transport=httpx.MockTransport(handler)),poll_interval=0)
    kw={'timeout_seconds':30,'remember':saved.append,'progress':lambda *_:None}
    assert s.generate(payload(),resume_id=None,**kw).content==b'video'
    assert saved==['animation_1'] and context[-1]['task']=='image_to_video'
    calls.clear();s.generate(payload(),resume_id='animation_1',**kw);assert calls==['GET']


@pytest.fixture(scope='module')
def clip():return render_video_mp4('ab'*32,4)


@pytest.mark.parametrize('temporal',[False,True])
@pytest.mark.parametrize('fixture',[False,True])
def test_animation_local_temporal_contract_lineage_and_cache(client,monkeypatch,clip,temporal,fixture):
    monkeypatch.setattr(canvas_activities,'refresh_provider_environment',lambda:None)
    monkeypatch.setattr(canvas_activities.activity,'heartbeat',lambda *_:None)
    monkeypatch.setenv('GENERATION_PROVIDER_MODE','fixture' if fixture else 'live')
    image=upload(client,'i.png',png(),'image/png');calls=[]
    class MockService:
        def generate(self,p,**kw):
            calls.append(p);kw['remember']('animation_1');assert [v['type'] for v in p['input']]==['image','text']
            return ProviderMedia(clip,'video/mp4','animation_1',{'cost_status':'provider_billed_unreported'})
        def close(self):pass
    monkeypatch.setattr('app.nodes.executors.omni_animation.GoogleOmniAnimationService',MockService)
    nodes=[{'id':'image','data':{'key':'asset.select','contractVersion':2,'config':{'artifact_id':image,'artifact_type':'Image'},'outputArtifactIds':[image]}},
           {'id':'prompt','data':{'key':'prompt.input','configText':'Raise the free left palm.'}},
           {'id':'target','data':{'key':'video.animate_image','contractVersion':2,'model':'google.video.omni.vertex','config':{'duration_seconds':4}}}]
    edges=[{'id':key,'source':key,'target':'target','sourceHandle':sp,'targetHandle':key} for key,sp in [('image','artifact'),('prompt','prompt')]]
    c=client.post('/canvases',json={'name':'Image only','document':canonicalize_canvas_document(nodes,edges)}).json()
    with SessionLocal() as db:rid=create_canvas_run(db,CanvasRunRequest(canvas_id=c['id'],canvas_revision=c['revision'],target_node_id='target')).id
    r=asyncio.run(canvas_activities.execute_canvas_node_activity(rid,'target')) if temporal else execute_canvas_node(rid,'target')
    a=client.get('/artifacts/'+r['artifact_ids'][0]).json();m=a['metadata']
    assert a['schema_id']=='video.image_animation.v2' and m['input_artifact_roles'][image]=='first_frame'
    assert m['requested_duration_ms']==m['video_duration_ms']==4000 and m['image_input_mode']=='first_frame'
    assert m['task']=='image_to_video' and m['exact_model_id']==OMNI_VERTEX_MODEL and m['fixture']==fixture
    assert m['definition_digest']==node_registry.get('video.animate_image',2).definition_digest
    assert execute_canvas_node(rid,'target')['artifact_ids']==r['artifact_ids'] and len(calls)==(0 if fixture else 1)


def test_video_audio_references_rejected_before_submission(client,monkeypatch,clip):
    monkeypatch.setenv('GENERATION_PROVIDER_MODE','live')
    monkeypatch.setattr('app.nodes.executors.omni_animation.GoogleOmniAnimationService',lambda:pytest.fail('must reject before submission'))
    image=upload(client,'i.png',png(),'image/png');video=upload(client,'v.mp4',clip,'video/mp4');audio=upload(client,'a.wav',render_audio_wav('ff'*32,4),'audio/wav')
    for typ,aid in [('Video',video),('Audio',audio)]:
        r=client.post('/experiments',json={'canvas_id':'c','node_id':typ,'node_key':'video.animate_image','node_contract_version':2,
            'model_alias':'google.video.omni.vertex','prompt':'Move','parameters':{'duration_seconds':4},
            'inputs':[{'type':'Image','artifact_ids':[image]},{'type':typ,'artifact_ids':[aid]}]}).json()
        assert r['status']=='FAILED' and 'video/audio references are not allowed' in r['error']


def test_requested_duration_is_checked_without_changing_frames():
    def probe(seconds):return {'format':{'duration':str(seconds)},'streams':[{'codec_type':'video','duration':str(seconds)}]}
    assert animation_timing(probe(10.5),10)['provider_padding_ms']==500
    for value in [9.5,11.1]:
        with pytest.raises(MediaProviderError,match='bounds'):animation_timing(probe(value),10)


def test_publish_bindings_reachability_and_request_hash(client):
    image=upload(client,'i.png',png(),'image/png')
    nodes=[{'id':'image','data':{'key':'asset.select','contractVersion':2,'config':{'artifact_id':image,'artifact_type':'Image'}}},
        {'id':'prompt','data':{'key':'prompt.input','configText':'Move'}},
        {'id':'target','data':{'key':'video.animate_image','contractVersion':2,'model':'google.video.omni.vertex'}},
        {'id':'unused','data':{'key':'video.segment'}},{'id':'memo','data':{'key':'utility.sticky','configText':'Image-only'}}]
    edges=[{'id':key,'source':key,'target':'target','sourceHandle':sp,'targetHandle':key} for key,sp in [('image','artifact'),('prompt','prompt')]]
    wf=client.post('/workflows',json={'name':'Image-only Omni'}).json();c=client.get('/canvases/'+wf['draft_canvas_id']).json()
    contract={'schema_version':'workflow.contract.draft.v1','inputs':[{'key':'length','label':'Length','type':'integer','default':10}],
        'bindings':[{'target':{'node_id':'target','path':'/config/duration_seconds'},'value':{'kind':'input','key':'length'}}],
        'outputs':[{'key':'video','label':'Video','node_id':'target','port_key':'video','port_type':'media.video.v1','primary':True}]}
    saved=client.put('/canvases/'+c['id'],json={'name':'Image-only','document':canonicalize_canvas_document(nodes,edges),'draft_contract':contract,'expected_revision':c['revision']});assert saved.status_code==200,saved.text
    v=client.post('/workflows/'+wf['id']+'/publish',json={'expected_canvas_revision':saved.json()['revision']});assert v.status_code==201,v.text
    assert v.json()['warnings']==['Unused Canvas Node excluded: unused']
    assert len(client.get('/workflows/'+wf['id']+'/versions/1/annotations').json())==1
    p=ExperimentRunRequest(canvas_id='c',node_id='n',node_key='video.animate_image',node_contract_version=2,model_alias='google.video.omni.vertex',prompt='Move',parameters={'duration_seconds':10})
    alias,exact=resolve_model(p.model_alias,p.node_key,2)
    assert request_fingerprint(p,alias,exact)!=request_fingerprint(p.model_copy(update={'parameters':{'duration_seconds':9}}),alias,exact)
