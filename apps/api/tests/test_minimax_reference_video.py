import asyncio
import io
import json

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
from app.nodes.executors.reference_video import ordered_references, validate_references, ReferenceVideoExecutor, PaddedReferenceVideoExecutor
from app.providers_minimax import MiniMaxVideoService, reference_request
from app.providers_performance import MediaProviderError, ProviderMedia


def image_bytes(color='green'):
    b=io.BytesIO();Image.new('RGB',(256,256),color).save(b,format='PNG');return b.getvalue()


def upload(client,name,data,mime):
    r=client.post('/artifacts/upload',files={'file':(name,data,mime)});assert r.status_code==201,r.text;return r.json()['artifact_id']


def request_payload():
    return reference_request(prompt='Image 1 is the character. Video 1 supplies motion. Audio 1 is speech.',resolution='2K',duration=4,ratio='9:16',media=[('image','image/png',b'one'),('image','image/png',b'two'),('video','video/mp4',b'v'),('audio','audio/wav',b'a')])


def test_reference_request_order_roles_and_body_limit(monkeypatch):
    p=request_payload();assert p['model']=='MiniMax-H3' and p['ratio']=='9:16' and p['duration']==4
    assert [x.get('role') for x in p['content']]==[None,'reference_image','reference_image','reference_video','reference_audio']
    assert p['content'][1]['image_url']['url'].endswith('b25l')
    assert 'seed' not in p and 'extra' not in p
    monkeypatch.setattr('app.providers_minimax.MAX_REQUEST_BYTES',1)
    with pytest.raises(MediaProviderError,match='64 MB'):request_payload()


def test_provider_checkpoint_resume_usage_and_no_cdn_credentials(monkeypatch):
    calls=[];remembered=[];states=iter(['queued','running','succeeded','succeeded'])
    monkeypatch.setattr('app.providers_minimax.validate_public_url',lambda value:value)
    def handle(req):
        calls.append((req.method,req.url.path))
        if req.method=='POST':
            assert json.loads(req.content)==request_payload();assert req.headers['authorization']=='Bearer secret'
            return httpx.Response(200,json={'task_id':'4241'})
        if req.url.host=='api.minimax.io':
            assert req.url.path=='/v2/query/video_generation/4241'
            return httpx.Response(200,json={'task':{'id':'4241','status':next(states),'model':'MiniMax-H3','content':{'url':'https://cdn.hailuoai.com/result.mp4'},'usage':{'output_seconds':4,'input_image_count':2}}})
        assert 'authorization' not in req.headers
        return httpx.Response(200,content=b'video')
    service=MiniMaxVideoService(api_key='secret',client=httpx.Client(transport=httpx.MockTransport(handle)),poll_interval=0)
    kw={'timeout_seconds':30,'remember':remembered.append,'progress':lambda *_:None}
    r=service.generate(request_payload(),resume_id=None,**kw)
    assert remembered==['4241'] and r.usage['provider_usage']['output_seconds']==4
    assert r.usage['cost_status']=='provider_billed_unreported' and r.content==b'video'
    calls.clear();service.generate(request_payload(),resume_id='4241',**kw)
    assert all(method=='GET' for method,_ in calls)


@pytest.mark.parametrize('status,rejected',[(400,True),(401,True),(402,True),(422,True),(503,False)])
def test_submit_errors_never_auto_resubmit(status,rejected):
    remembered=[];service=MiniMaxVideoService(api_key='test',client=httpx.Client(transport=httpx.MockTransport(lambda _:httpx.Response(status))))
    with pytest.raises(MediaProviderError) as error:service.generate(request_payload(),timeout_seconds=30,resume_id=None,remember=remembered.append,progress=lambda *_:None)
    assert not error.value.retryable and error.value.rejected==rejected
    assert remembered==(['rejected'] if rejected else [])


def test_known_task_network_failure_can_resume():
    service=MiniMaxVideoService(api_key='test',client=httpx.Client(transport=httpx.MockTransport(lambda _:httpx.Response(503))))
    with pytest.raises(MediaProviderError) as error:service.generate(request_payload(),timeout_seconds=30,resume_id='existing',remember=lambda _:pytest.fail('must not submit'),progress=lambda *_:None)
    assert error.value.retryable


def test_cdn_redirect_revalidates_public_destination(monkeypatch):
    seen=[]
    def validate(url):
        seen.append(url)
        if '127.0.0.1' in url:raise ValueError('private')
    monkeypatch.setattr('app.providers_minimax.validate_public_url',validate)
    client=httpx.Client(transport=httpx.MockTransport(lambda _:httpx.Response(302,headers={'location':'https://127.0.0.1/private'})))
    with pytest.raises(MediaProviderError,match='public'):MiniMaxVideoService(api_key='test',client=client)._download('https://cdn.hailuoai.com/result')
    assert len(seen)==2


def test_manifest_models_validation_and_request_hash(client):
    d=node_registry.get('video.reference_generate',1);assert d.editor.kind=='generic'
    assert [p.type for p in d.ports.inputs]==['prompt.text.v1','media.image.v1','media.video.v1','media.audio.v1']
    assert d.ports.inputs[1].required and d.ports.inputs[1].multiple
    for cfg in [{'duration_seconds':3},{'duration_seconds':4.5},{'resolution':'1080p'},{'seed':3}]:
        with pytest.raises(ValueError):node_registry.resolve_config(d,cfg)
    model,exact=resolve_model('minimax.video.h3',d.type_key);assert exact=='MiniMax-H3'
    assert resolve_model('video.fast','video.animate_image')==('google.video.fast','veo-3.1-fast-generate-001')
    p=ExperimentRunRequest(canvas_id='c',node_id='n',node_key=d.type_key,model_alias=model,prompt='Move',inputs=[{'type':'Image','artifact_ids':['a','b']}])
    assert request_fingerprint(p,model,exact)!=request_fingerprint(p.model_copy(update={'inputs':[{'type':'Image','artifact_ids':['b','a']}]}),model,exact)
    assert request_fingerprint(p,model,exact)!=request_fingerprint(p.model_copy(update={'parameters':{'duration_seconds':5}}),model,exact)
    assert any(x['type_key']==d.type_key for x in client.get('/node-definitions').json())
    assert next(x for x in client.get('/models').json() if x['logical_alias']==model)['provider']=='MiniMax'
    # The old first-frame contract remains Google-only and is not reinterpreted.
    assert node_registry.get('video.animate_image',1).execution.model_families==['google.video.fast','google.video.quality']


@pytest.fixture(scope='module')
def generated_video():return render_video_mp4('ab' * 32,4)


@pytest.mark.parametrize('temporal',[False,True])
@pytest.mark.parametrize('fixture',[False,True])
@pytest.mark.parametrize('version',[1,2])
def test_native_result_contract_lineage_cache_local_temporal(client,monkeypatch,generated_video,temporal,fixture,version):
    monkeypatch.setattr(canvas_activities,'refresh_provider_environment',lambda:None)
    monkeypatch.setattr(canvas_activities.activity,'heartbeat',lambda *_:None)
    monkeypatch.setenv('GENERATION_PROVIDER_MODE','fixture' if fixture else 'live')
    a=upload(client,'first.png',image_bytes(),'image/png');b=upload(client,'second.png',image_bytes('red'),'image/png');aud=upload(client,'speech.wav',render_audio_wav('cd' * 32,3),'audio/wav');calls=[]
    class MockService:
        def generate(self,payload,**kw):
            calls.append(payload);kw['remember']('task_1');assert [v.get('role') for v in payload['content']]==[None,'reference_image','reference_image','reference_audio']
            return ProviderMedia(generated_video,'video/mp4','task_1',{'cost_status':'provider_billed_unreported','provider_usage':{'output_seconds':4}})
        def close(self):pass
    monkeypatch.setattr('app.nodes.executors.reference_video.MiniMaxVideoService',MockService)
    nodes=[{'id':ident,'data':{'key':'asset.select','contractVersion':2,'config':{'artifact_id':aid,'artifact_type':typ},'outputArtifactIds':[aid]}} for ident,aid,typ in [('a',a,'Image'),('b',b,'Image'),('audio',aud,'Audio')]]
    nodes += [{'id':'prompt','data':{'key':'prompt.input','configText':'Keep the character from Image 1. Audio 1 supplies speech.'}}, {'id':'target','data':{'key':'video.reference_generate','contractVersion':version,'model':'minimax.video.h3'}}]
    edges=[{'id':str(i),'source':s,'target':'target','sourceHandle':sp,'targetHandle':tp} for i,(s,sp,tp) in enumerate([('prompt','prompt','prompt'),('b','artifact','images'),('a','artifact','images'),('audio','artifact','audios')])]
    saved=client.post('/canvases',json={'name':'H3 setup','document':canonicalize_canvas_document(nodes,edges)}).json()
    with SessionLocal() as db:run_id=create_canvas_run(db,CanvasRunRequest(canvas_id=saved['id'],canvas_revision=saved['revision'],target_node_id='target')).id
    result=asyncio.run(canvas_activities.execute_canvas_node_activity(run_id,'target')) if temporal else execute_canvas_node(run_id,'target')
    artifact=client.get('/artifacts/'+result['artifact_ids'][0]).json();m=artifact['metadata'];assert artifact['schema_id']==f'video.reference_generated.v{version}'
    assert m['ordered_reference_artifact_ids']=={'images':[b,a],'videos':[],'audios':[aud]}
    assert m['input_artifact_roles']=={b:'identity_appearance_reference',a:'identity_appearance_reference',aud:'speech_reference'}
    assert m['exact_model_id']=='MiniMax-H3' and m['definition_digest']==node_registry.get('video.reference_generate',version).definition_digest
    assert m['normalized_config']['duration_seconds']==4 and m['duration_ms']==4000
    assert m['fixture']==fixture and m['cost_status']==('fixture' if fixture else 'provider_billed_unreported')
    assert execute_canvas_node(run_id,'target')['artifact_ids']==result['artifact_ids'];assert len(calls)==(0 if fixture else 1)


def test_provider_tail_padding_has_explicit_v2_contract():
    info={'format':{'duration':'4.459'},'streams':[{'codec_type':'video','duration':'4.458333'}]}
    with pytest.raises(MediaProviderError,match='250ms'):
        ReferenceVideoExecutor().result_timing(info,{'duration_seconds':4})
    timing=PaddedReferenceVideoExecutor().result_timing(info,{'duration_seconds':4})
    assert timing['requested_duration_ms']==4000 and timing['duration_ms']==4459 and timing['provider_padding_ms']==458
    with pytest.raises(MediaProviderError,match='bounds'):
        PaddedReferenceVideoExecutor().result_timing({'format':{'duration':'5.2'},'streams':[{'codec_type':'video','duration':'5.2'}]},{'duration_seconds':4})
    old,new=[node_registry.get('video.reference_generate',v) for v in [1,2]]
    assert old.definition_digest!=new.definition_digest
    assert old.ports==new.ports
    assert node_registry.resolve_config(old,{})==node_registry.resolve_config(new,{})


def test_media_limits_reject_before_claim(client,monkeypatch):
    monkeypatch.setenv('GENERATION_PROVIDER_MODE','live')
    monkeypatch.setattr('app.nodes.executors.reference_video.MiniMaxVideoService',lambda:pytest.fail('invalid media must fail before provider access'))
    small=io.BytesIO();Image.new('RGB',(32,32)).save(small,format='PNG');aid=upload(client,'small.png',small.getvalue(),'image/png')
    p={'canvas_id':'c','node_id':'n','node_key':'video.reference_generate','model_alias':'minimax.video.h3','prompt':'Move','inputs':[{'type':'Image','artifact_ids':[aid]}]}
    r=client.post('/experiments',json=p).json();assert r['status']=='FAILED' and '256' in r['error']


def test_ambiguous_task_is_not_billed_twice(client,monkeypatch):
    monkeypatch.setenv('GENERATION_PROVIDER_MODE','live');calls=[]
    class BrokenService:
        def generate(self,*args,**kwargs):
            calls.append(1);raise MediaProviderError('Submission outcome is unknown')
        def close(self):pass
    monkeypatch.setattr('app.nodes.executors.reference_video.MiniMaxVideoService',BrokenService)
    aid=upload(client,'image.png',image_bytes(),'image/png')
    payload={'canvas_id':'c','node_id':'n','node_key':'video.reference_generate','model_alias':'minimax.video.h3','prompt':'Move','inputs':[{'type':'Image','artifact_ids':[aid]}]}
    first=client.post('/experiments',json=payload).json();second=client.post('/experiments',json=payload).json()
    assert first['status']==second['status']=='FAILED' and len(calls)==1
    assert 'unresolved outcome' in second['error']


def test_reference_publish_binding_annotation_and_unreachable_nodes(client):
    aid=upload(client,'character.png',image_bytes(),'image/png')
    nodes=[{'id':'image','data':{'key':'asset.select','contractVersion':2,'config':{'artifact_id':aid,'artifact_type':'Image'},'outputArtifactIds':[aid]}},
           {'id':'prompt','data':{'key':'prompt.input','configText':'Keep Image 1 consistent.'}},
           {'id':'target','data':{'key':'video.reference_generate','model':'minimax.video.h3'}},
           {'id':'unused','data':{'key':'video.segment'}}, {'id':'memo','data':{'key':'utility.sticky','configText':'Reference comparison'}}]
    edges=[{'id':'image','source':'image','target':'target','sourceHandle':'artifact','targetHandle':'images'},{'id':'prompt','source':'prompt','target':'target','sourceHandle':'prompt','targetHandle':'prompt'}]
    wf=client.post('/workflows',json={'name':'H3 compare'}).json();c=client.get('/canvases/'+wf['draft_canvas_id']).json()
    contract={'schema_version':'workflow.contract.draft.v1','inputs':[{'key':'length','label':'Length','type':'integer','default':4}],
              'bindings':[{'target':{'node_id':'target','path':'/config/duration_seconds'},'value':{'kind':'input','key':'length'}}],
              'outputs':[{'key':'video','label':'H3','node_id':'target','port_key':'video','port_type':'media.video.v1','primary':True}]}
    saved=client.put('/canvases/'+c['id'],json={'name':c['name'],'document':canonicalize_canvas_document(nodes,edges),'draft_contract':contract,'expected_revision':c['revision']});assert saved.status_code==200,saved.text
    result=client.post('/workflows/'+wf['id']+'/publish',json={'expected_canvas_revision':saved.json()['revision']});assert result.status_code==201,result.text
    version=result.json();assert {n['id'] for n in version['graph']['nodes']}=={'image','prompt','target'}
    assert version['warnings']==['Unused Canvas Node excluded: unused']
    assert len(client.get('/workflows/'+wf['id']+'/versions/1/annotations').json())==1
