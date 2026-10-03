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
from app.media_preview import render_video_mp4
from app.nodes import node_registry
from app.providers_google import GoogleProviderConfig
from app.providers_omni import GoogleOmniEditService, OMNI_VERTEX_MODEL, edit_request
from app.providers_performance import MediaProviderError, ProviderMedia


def png():
    stream = io.BytesIO(); Image.new('RGB', (256,256), 'pink').save(stream, format='PNG'); return stream.getvalue()


def upload(client, name, data, mime):
    r=client.post('/artifacts/upload',files={'file':(name,data,mime)}); assert r.status_code==201,r.text
    return r.json()['artifact_id']


def payload():
    return edit_request(prompt='Replace only the person; keep the performance.', image=png(), image_content_type='image/png', video=b'video', resolution='1080p')


def service(handler):
    credentials=SimpleNamespace(valid=True,token='secret')
    return GoogleOmniEditService(config=GoogleProviderConfig(project='test-project',credentials=credentials),
                                client=httpx.Client(transport=httpx.MockTransport(handler)),poll_interval=0)


def test_normalized_edit_request_and_v1_compatibility(client,monkeypatch):
    p=payload(); assert p['model']==OMNI_VERTEX_MODEL
    assert p['generation_config']=={'video_config':{'task':'edit'}}
    assert p['background'] and p['store']
    assert [x['type'] for x in p['input']]==['video','image','text']
    assert '<VIDEO_0>@Video1' in p['input'][-1]['text']
    assert '<VIDEO_REF_0>' not in p['input'][-1]['text']
    assert p['response_format']==[{'type':'video','resolution':'1080p'}]
    old,new=[node_registry.get('video.performance_transfer',v) for v in [1,2]]
    assert old.execution.provider=='fal' and new.execution.provider=='google'
    assert old.artifact_contract.schema_id=='video.performance_transferred.v1'
    assert old.ports==new.ports or [x.type for x in old.ports.inputs]==[x.type for x in new.ports.inputs]
    assert 'character_orientation' in old.config_schema['properties'] and 'character_orientation' not in new.config_schema['properties']
    assert new.editor.kind=='generic'
    for cfg in [{'character_orientation':'video'}, {'resolution':'4k'}, {'timeout_seconds':29}, {'prompt':''}]:
        with pytest.raises(ValueError): node_registry.resolve_config(new,cfg)
    assert node_registry.resolve_config(new,{})['resolution']=='1080p'
    models=client.get('/models').json()
    m=next(m for m in models if m['logical_alias']=='google.video.omni.vertex');assert m['region']=='global'
    assert m['exact_model_id']==OMNI_VERTEX_MODEL
    assert 'google.video.omni' not in {m['logical_alias'] for m in models}
    monkeypatch.setattr('app.providers_omni.MAX_BYTES',10)
    with pytest.raises(MediaProviderError,match='64 MB'):payload()


def test_checkpoint_resume_and_usage_before_download(monkeypatch):
    calls=[];remembered=[];events=[]
    monkeypatch.setattr('app.providers_omni.validate_public_url',lambda _:None)
    monkeypatch.setattr('app.providers_omni.record_provider_result',lambda *a,**k:events.append(('usage',a[3])))
    def handle(req):
        calls.append(req.method)
        if req.method=='POST':
            assert req.url.path=='/v1beta1/projects/test-project/locations/global/interactions'
            assert req.headers['authorization']=='Bearer secret'
            assert json.loads(req.content)==payload()
            return httpx.Response(200,json={'id':'interaction_1','status':'in_progress'})
        if req.url.host=='aiplatform.googleapis.com':
            return httpx.Response(200,json={'id':'interaction_1','model':OMNI_VERTEX_MODEL,'status':'completed',
                'usage':{'total_output_tokens':321},'steps':[{'type':'model_output','content':[{'type':'video','uri':'https://storage.googleapis.com/public/result.mp4'}]}]})
        assert 'authorization' not in req.headers
        assert events and events[-1][0]=='usage';events.append(('download',None))
        return httpx.Response(200,content=b'video')
    s=service(handle);kw={'timeout_seconds':30,'remember':remembered.append,'progress':lambda *_:None}
    r=s.edit(payload(),resume_id=None,**kw)
    assert r.content==b'video' and r.usage['cost_status']=='provider_billed_unreported'
    assert remembered==['interaction_1']
    calls.clear();s.edit(payload(),resume_id='interaction_1',**kw);assert 'POST' not in calls


@pytest.mark.parametrize('code,rejected',[(400,True),(401,True),(403,True),(404,True),(429,True),(503,False)])
def test_submission_never_blindly_retries(code,rejected):
    calls=[];remembered=[]
    def handle(req):calls.append(req);return httpx.Response(code)
    with pytest.raises(MediaProviderError) as error:
        service(handle).edit(payload(),timeout_seconds=30,resume_id=None,remember=remembered.append,progress=lambda *_:None)
    assert len(calls)==1 and not error.value.retryable and error.value.rejected==rejected
    assert remembered==(['rejected'] if rejected else [])


def test_query_retry_and_terminal_failure_are_distinct():
    with pytest.raises(MediaProviderError) as error:
        service(lambda _:httpx.Response(503)).edit(payload(),timeout_seconds=30,resume_id='existing',remember=lambda _:pytest.fail('resubmission'),progress=lambda *_:None)
    assert error.value.retryable
    with pytest.raises(MediaProviderError) as error:
        service(lambda _:httpx.Response(200,json={'status':'failed'})).edit(payload(),timeout_seconds=30,resume_id='existing',remember=lambda _:pytest.fail('resubmission'),progress=lambda *_:None)
    assert not error.value.retryable


def test_inline_output_and_invalid_redirect(monkeypatch):
    s=service(lambda _:httpx.Response(302,headers={'location':'https://127.0.0.1/private'}))
    result=s.result({'output_video':{'data':base64.b64encode(b'video').decode()},'usage':{}},'i1')
    assert result.content==b'video'
    def validate(url):
        if '127.0.0.1' in url:raise ValueError('private')
    monkeypatch.setattr('app.providers_omni.validate_public_url',validate)
    with pytest.raises(MediaProviderError,match='public'):s.download('https://example.com/video')


@pytest.fixture(scope='module')
def clip(): return render_video_mp4('aa'*32,4)


@pytest.mark.parametrize('temporal',[False,True])
@pytest.mark.parametrize('fixture',[False,True])
def test_executor_result_artifact_cache_local_temporal(client,monkeypatch,clip,temporal,fixture):
    monkeypatch.setattr(canvas_activities,'refresh_provider_environment',lambda:None)
    monkeypatch.setattr(canvas_activities.activity,'heartbeat',lambda *_:None)
    monkeypatch.setenv('GENERATION_PROVIDER_MODE','fixture' if fixture else 'live')
    image=upload(client,'identity.png',png(),'image/png');video=upload(client,'motion.mp4',clip,'video/mp4');calls=[]
    class MockService:
        def edit(self,p,**kwargs):
            calls.append(p);kwargs['remember']('interaction_1')
            return ProviderMedia(clip,'video/mp4','interaction_1',{'cost_status':'provider_billed_unreported'})
        def close(self):pass
    monkeypatch.setattr('app.nodes.executors.performance_edit.GoogleOmniEditService',MockService)
    nodes=[{'id':ident,'data':{'key':'asset.select','contractVersion':2,'config':{'artifact_id':aid,'artifact_type':typ},'outputArtifactIds':[aid]}}
           for ident,aid,typ in [('identity',image,'Image'),('motion',video,'Video')]]
    nodes += [{'id':'edit','data':{'key':'video.performance_transfer','contractVersion':2,'model':'google.video.omni.vertex','config':{'prompt':'Replace the person.'}}}]
    edges=[{'id':ident,'source':ident,'target':'edit','sourceHandle':'artifact','targetHandle':port} for ident,port in [('identity','image'),('motion','video')]]
    saved=client.post('/canvases',json={'name':'Omni edit','document':canonicalize_canvas_document(nodes,edges)}).json()
    with SessionLocal() as db:rid=create_canvas_run(db,CanvasRunRequest(canvas_id=saved['id'],canvas_revision=saved['revision'],target_node_id='edit')).id
    result=asyncio.run(canvas_activities.execute_canvas_node_activity(rid,'edit')) if temporal else execute_canvas_node(rid,'edit')
    a=client.get('/artifacts/'+result['artifact_ids'][0]).json();m=a['metadata']
    assert a['schema_id']=='video.performance_transferred.v2'
    assert m['input_artifact_roles']=={image:'character_identity',video:'driving_performance'}
    assert m['source_duration_ms']==m['duration_ms']==4000
    assert m['exact_model_id']==OMNI_VERTEX_MODEL and m['audio_policy']=='silent'
    assert m['definition_digest']==node_registry.get('video.performance_transfer',2).definition_digest
    assert m['fixture']==fixture
    assert execute_canvas_node(rid,'edit')['artifact_ids']==result['artifact_ids']
    assert len(calls)==(0 if fixture else 1)


def test_ambiguous_submission_and_duration_validation(client,monkeypatch,clip):
    monkeypatch.setenv('GENERATION_PROVIDER_MODE','live');calls=[]
    class Broken:
        def edit(self,*args,**kwargs):calls.append(1);raise MediaProviderError('Submission outcome unknown')
        def close(self):pass
    monkeypatch.setattr('app.nodes.executors.performance_edit.GoogleOmniEditService',Broken)
    image=upload(client,'i.png',png(),'image/png');video=upload(client,'v.mp4',clip,'video/mp4')
    p={'canvas_id':'c','node_id':'n','node_key':'video.performance_transfer','node_contract_version':2,'model_alias':'google.video.omni.vertex',
       'parameters':{'prompt':'Edit'},'inputs':[{'type':'Image','artifact_ids':[image]},{'type':'Video','artifact_ids':[video]}]}
    first=client.post('/experiments',json=p).json();second=client.post('/experiments',json=p).json()
    assert first['status']==second['status']=='FAILED' and len(calls)==1
    assert 'unresolved outcome' in second['error']
    long_video=upload(client,'long.mp4',render_video_mp4('bb'*32,11),'video/mp4')
    p['node_id']='long';p['inputs'][1]['artifact_ids']=[long_video]
    r=client.post('/experiments',json=p).json();assert r['status']=='FAILED' and '3–10' in r['error'] and len(calls)==1


def test_publish_bindings_reachability_annotation_and_hash(client,clip):
    image=upload(client,'i.png',png(),'image/png');video=upload(client,'v.mp4',clip,'video/mp4')
    nodes=[{'id':ident,'data':{'key':'asset.select','contractVersion':2,'config':{'artifact_id':aid,'artifact_type':typ}}} for ident,aid,typ in [('image',image,'Image'),('video',video,'Video')]]
    nodes += [{'id':'edit','data':{'key':'video.performance_transfer','contractVersion':2,'model':'google.video.omni.vertex'}},
              {'id':'unused','data':{'key':'video.segment'}},{'id':'memo','data':{'key':'utility.sticky','configText':'Compare'}}]
    edges=[{'id':p,'source':p,'target':'edit','sourceHandle':'artifact','targetHandle':p} for p in ['image','video']]
    wf=client.post('/workflows',json={'name':'Omni'}).json();c=client.get('/canvases/'+wf['draft_canvas_id']).json()
    contract={'schema_version':'workflow.contract.draft.v1','inputs':[{'key':'instruction','label':'Edit','type':'prompt','default':'Change character'}],
        'bindings':[{'target':{'node_id':'edit','path':'/config/prompt'},'value':{'kind':'input','key':'instruction'}}],
        'outputs':[{'key':'video','label':'Omni','node_id':'edit','port_key':'video','port_type':'media.video.v1','primary':True}]}
    r=client.put('/canvases/'+c['id'],json={'name':'Omni','document':canonicalize_canvas_document(nodes,edges),'draft_contract':contract,'expected_revision':c['revision']});assert r.status_code==200,r.text
    r=client.post('/workflows/'+wf['id']+'/publish',json={'expected_canvas_revision':r.json()['revision']});assert r.status_code==201,r.text
    v=r.json();assert {n['id'] for n in v['graph']['nodes']}=={'image','video','edit'}
    assert v['warnings']==['Unused Canvas Node excluded: unused']
    annotations=client.get('/workflows/'+wf['id']+'/versions/1/annotations').json();assert len(annotations)==1
    client.post('/workflows/'+wf['id']+'/annotations',json={'body':'Review eye highlights'})
    assert client.get('/workflows/'+wf['id']+'/versions/1').json()['content_hash']==v['content_hash']
    p=ExperimentRunRequest(canvas_id='c',node_id='n',node_key='video.performance_transfer',node_contract_version=2,model_alias='google.video.omni.vertex',parameters={'prompt':'Edit'},inputs=[{'type':'Video','artifact_ids':[video]}])
    alias,exact=resolve_model(p.model_alias,p.node_key,2);assert exact==OMNI_VERTEX_MODEL
    old=request_fingerprint(p,alias,exact)
    assert old!=request_fingerprint(p.model_copy(update={'parameters':{'prompt':'Other'}}),alias,exact)
    assert old!=request_fingerprint(p.model_copy(update={'inputs':[{'type':'Video','artifact_ids':['other']}]}),alias,exact)
