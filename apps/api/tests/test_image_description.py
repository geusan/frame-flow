from __future__ import annotations

import asyncio
import base64
import io
import json
import time
from pathlib import Path
from types import SimpleNamespace

import httpx
import jsonschema
import pytest
from openai import APIConnectionError, APIStatusError
from PIL import Image
from temporalio.testing import ActivityEnvironment

from app import canvas_activities
from app.canvas_documents import canonicalize_canvas_document
from app.canvas_runs import create_canvas_run, execute_canvas_node
from app.database import SessionLocal
from app.domain import CanvasRunRequest, ExperimentRunRequest
from app.experiments import request_fingerprint, resolve_model
from app.nodes import node_registry
from app.nodes.executors.image_description import ImageDescriptionError
from app.providers import model_id_for_alias
from app.providers_generation import InputMedia
from app.providers_openai import OpenAIProviderConfig, OpenAIGenerationServices

ACTION = 'She is actively sipping: the cup rim touches her lips. Her gaze points image-left, away from the camera. Both knees are bent and both feet rest on the chair. One hand holds the handle; the other supports the cup.'
BRIEF = 'Keep the fixed character face and body. Reproduce the observed action; never substitute a camera-facing portrait.'


def png(color='red'):
    b = io.BytesIO(); Image.new('RGB', (16, 20), color).save(b, format='PNG'); return b.getvalue()


def upload(client, color='red'):
    r = client.post('/artifacts/upload', files={'file': (color+'.png', png(color), 'image/png')})
    assert r.status_code == 201
    return r.json()['artifact_id']


def node(id, key, config=None, *, version=1, model=None):
    definition = node_registry.get(key, version)
    return {'id': id, 'type': 'studio', 'position': {'x': 0, 'y': 0}, 'data': {
        'key': key, 'contractVersion': version, 'config': config or {},
        'model': model or definition.execution.model_alias,
        **({'configText': config['text']} if config and 'text' in config else {}),
        **({'outputArtifactIds': [config['artifact_id']]} if config and config.get('artifact_id') else {}),
    }}


def edge(id, source, target, output, input):
    return {'id': id, 'source': source, 'target': target, 'sourceHandle': output, 'targetHandle': input}


def experiment(aid, **changes):
    return {'canvas_id': 'test-description', 'node_id': 'describe', 'node_key': 'image.describe', 'model_alias': 'openai.chat.latest', 'prompt': BRIEF,
            'inputs': [{'type': 'Image', 'artifact_ids': [aid], 'target_port': 'image'}], **changes}


def test_vision_provider_sends_actual_image_and_reports_usage():
    calls = []
    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(output_text=ACTION, id='resp_vision', model='resolved-vision-model', status='completed', usage=SimpleNamespace(model_dump=lambda **_: {'input_tokens': 300, 'output_tokens': 100}))
    provider = OpenAIGenerationServices(OpenAIProviderConfig('test-key'), client=SimpleNamespace(responses=SimpleNamespace(create=create)))
    text, request_id, metadata = provider.generate_vision_text(logical_model='openai.chat.latest', instructions='Describe visible action only.', images=[InputMedia('image', 'Image', png(), 'image/png')], detail='high', max_output_tokens=2400)
    request = calls[0]
    assert request['store'] is False and request['max_output_tokens'] == 2400
    assert request['model'] == model_id_for_alias('openai.chat.latest')
    parts = request['input'][0]['content']
    assert parts[0] == {'type': 'input_text', 'text': 'Describe visible action only.'}
    assert parts[1]['detail'] == 'high'
    assert base64.b64decode(parts[1]['image_url'].split(',', 1)[1]) == png()
    assert text == ACTION and request_id == 'resp_vision'
    assert metadata['usage']['input_tokens'] == 300
    assert metadata['response_model'] == 'resolved-vision-model'


@pytest.mark.parametrize('status,text', [('completed',''), ('incomplete','Partial action')])
def test_provider_rejects_empty_or_incomplete_observations(status, text):
    service = OpenAIGenerationServices(OpenAIProviderConfig('test'), client=SimpleNamespace(responses=SimpleNamespace(create=lambda **_: SimpleNamespace(status=status, output_text=text))))
    with pytest.raises(ValueError, match='incomplete or empty'):
        service.generate_vision_text(logical_model='openai.chat.latest', instructions='Describe', images=[], detail='high', max_output_tokens=256)


@pytest.mark.parametrize('temporal', [False, True])
def test_description_executor_local_temporal_parity_and_cache(client, monkeypatch, temporal):
    monkeypatch.setenv('GENERATION_PROVIDER_MODE', 'live')
    aid = upload(client); calls = []
    def describe(**kwargs):
        calls.append(kwargs)
        assert kwargs['images'][0].data == png()
        return ACTION, 'vision-request', {'usage': {'input_tokens': 30}, 'response_model': 'vision-exact'}
    monkeypatch.setattr('app.nodes.executors.image_description.get_openai_generation_services', lambda: SimpleNamespace(generate_vision_text=describe))
    nodes = [node('image','asset.select', {'artifact_id':aid,'artifact_type':'Image'},version=2), node('brief','prompt.input', {'text':BRIEF}), node('describe','image.describe')]
    edges = [edge('a','image','describe','artifact','image'),edge('b','brief','describe','prompt','prompt')]
    c = client.post('/canvases',json={'name':'Image action','document':canonicalize_canvas_document(nodes,edges)}).json()
    with SessionLocal() as db:
        run_id = create_canvas_run(db,CanvasRunRequest(canvas_id=c['id'],canvas_revision=c['revision'],target_node_id='describe')).id
    result = asyncio.run(ActivityEnvironment().run(canvas_activities.execute_canvas_node_activity,run_id,'describe')) if temporal else execute_canvas_node(run_id,'describe')
    artifact = client.get('/artifacts/'+result['artifact_ids'][0]).json()
    text = client.get('/artifacts/'+artifact['id']+'/content').text
    assert ACTION in text and text.endswith(BRIEF)
    assert artifact['type']=='Text' and artifact['schema_id']=='prompt.image_description.v1'
    assert artifact['input_artifact_ids']==[aid]
    assert artifact['metadata']['input_artifact_roles'][aid]=='described_image'
    assert artifact['metadata']['definition_digest']==node_registry.get('image.describe',1).definition_digest
    assert artifact['metadata']['execution_mode']=='image-description.v1:live'
    assert artifact['metadata']['normalized_config']==node_registry.resolve_config(node_registry.get('image.describe',1),{})
    assert artifact['metadata']['cost_status']=='provider_billed_unreported'
    schema=json.loads((Path(__file__).parents[3]/'packages/schemas/prompt.image_description.v1.schema.json').read_text())
    jsonschema.validate(text,schema)
    repeated=execute_canvas_node(run_id,'describe')
    assert repeated['artifact_ids']==result['artifact_ids'] and len(calls)==1


@pytest.mark.parametrize('status,retryable', [(400,False),(401,False),(429,True),(503,True)])
def test_description_http_error_classification(client, monkeypatch, status, retryable):
    monkeypatch.setenv('GENERATION_PROVIDER_MODE','live'); aid=upload(client)
    def fail(**kwargs):
        raise APIStatusError('provider error',response=httpx.Response(status,request=httpx.Request('POST','https://api.openai.com/v1/responses')),body=None)
    monkeypatch.setattr('app.nodes.executors.image_description.get_openai_generation_services',lambda:SimpleNamespace(generate_vision_text=fail))
    from app.experiments import run_experiment
    with SessionLocal() as db:
        result=run_experiment(db,ExperimentRunRequest(**experiment(aid)))
        assert result.status=='FAILED' and getattr(result,'_failure_retryable') is retryable


def test_connection_errors_can_retry(client,monkeypatch):
    monkeypatch.setenv('GENERATION_PROVIDER_MODE','live'); aid=upload(client)
    def fail(**kwargs): raise APIConnectionError(request=httpx.Request('POST','https://api.openai.com/v1/responses'))
    monkeypatch.setattr('app.nodes.executors.image_description.get_openai_generation_services',lambda:SimpleNamespace(generate_vision_text=fail))
    from app.experiments import run_experiment
    with SessionLocal() as db:
        result=run_experiment(db,ExperimentRunRequest(**experiment(aid)))
        assert result._failure_retryable is True


def test_input_validation_and_fixture_contract(client):
    aid=upload(client)
    result=client.post('/experiments',json=experiment(aid)).json()
    assert result['status']=='SUCCEEDED'
    artifact=client.get('/artifacts/'+result['output_artifact_ids'][0]).json()
    assert artifact['type']=='Text' and artifact['schema_id']=='prompt.image_description.v1'
    assert artifact['metadata']['cost_status']=='fixture'
    for inputs in [[],[{'type':'Image','artifact_ids':[aid,upload(client,'blue')]}]]:
        result=client.post('/experiments',json=experiment(aid,inputs=inputs)).json()
        assert result['status']=='FAILED' and 'exactly one Image' in result['error']
    invalid=client.post('/artifacts/upload',files={'file':('broken.png',b'not an image','image/png')}).json()['artifact_id']
    result=client.post('/experiments',json=experiment(invalid)).json()
    assert result['status']=='FAILED' and 'valid image' in result['error']


def test_manifest_config_binding_and_cache_identity():
    definition=node_registry.get('image.describe',1)
    assert definition.editor.kind=='generic'
    assert definition.ports.inputs[0].type=='media.image.v1' and definition.ports.outputs[0].type=='prompt.text.v1'
    assert definition.config_schema['properties']['instructions']['x-workflow-input']['enabled']
    config=node_registry.resolve_config(definition,{})
    assert config['image_detail']=='high' and config['max_output_tokens']==2400
    for bad in [{'image_detail':'fake'},{'instructions':''},{'max_output_tokens':1},{'secret':'bad'}]:
        with pytest.raises(ValueError):node_registry.resolve_config(definition,bad)
    payload=ExperimentRunRequest(**experiment('source'))
    alias,exact=resolve_model(payload.model_alias,payload.node_key,1)
    original=request_fingerprint(payload,alias,exact)
    for change in [{'prompt':'Different constraints'},{'parameters':{'image_detail':'low'}},{'parameters':{'instructions':'Different focus'}},{'inputs':[{'type':'Image','artifact_ids':['other']}]}]:
        assert request_fingerprint(payload.model_copy(update=change),alias,exact)!=original


@pytest.mark.parametrize("extract_master", [False, True])
def test_full_published_chain_keeps_action_and_ordered_image_references(client,monkeypatch,extract_master):
    monkeypatch.setenv('GENERATION_PROVIDER_MODE','live')
    refs=[upload(client,color) for color in ['red','green','blue','white','yellow']]
    vision_calls=[];image_calls=[]
    def describe(**kwargs):
        vision_calls.append(kwargs);assert [i.artifact_id for i in kwargs['images']]==[refs[4]]
        return ACTION,'vision-id',{'usage':{},'response_model':'vision-model'}
    def improve(**kwargs):
        assert ACTION in kwargs['prompt'] and BRIEF in kwargs['prompt']
        return '### 1. English Master Prompt\n'+ACTION+'\n'+BRIEF+'\n\n### 2. Korean Translation\n검토용 번역\n\n### 3. Technical / Visual Blueprint\nReview-only blueprint.','skill-id'
    def generate(**kwargs):
        image_calls.append(kwargs)
        assert ACTION in kwargs['prompt']
        if extract_master:
            assert kwargs['prompt'] == ACTION+'\n'+BRIEF
            assert 'Korean Translation' not in kwargs['prompt'] and 'Blueprint' not in kwargs['prompt']
        else:
            assert 'Korean Translation' in kwargs['prompt']
        assert [i.artifact_id for i in kwargs['reference_images']]==[refs[0],refs[1],refs[2],refs[4]]
        return [png()],'image-id'
    service=SimpleNamespace(generate_vision_text=describe,generate_text=improve,generate_images=generate)
    for module in ['image_description','text_generation','image_generation']:
        monkeypatch.setattr('app.nodes.executors.'+module+'.get_openai_generation_services',lambda:service)
    nodes=[node('ref'+str(i),'asset.select',{'artifact_id':aid,'artifact_type':'Image'},version=2) for i,aid in enumerate(refs[:4])]
    nodes += [node('brief','prompt.input',{'text':BRIEF}),node('describe','image.describe'),node('skill','skill.execute',{'skill_id':'nottalggak-prompt-machine'},version=2,model='openai.chat.latest'),node('bundle','prompt.input',{'text':''}),node('image','image.generate',model='openai.image.default'),node('unused','prompt.input',{'text':'excluded'})]
    # Reference attachments precede ancestry traversal so the image provider sees canonical indices 1..4.
    edges=[edge('ref'+str(i),'ref'+str(i),'bundle','artifact','images') for i in range(4)]
    edges += [edge('vision-image','ref3','describe','artifact','image'),edge('brief-analysis','brief','describe','prompt','prompt'),edge('analysis-skill','describe','skill','prompt','prompt'),edge('skill-bundle','skill','bundle','prompt','prompt'),edge('bundle-image','bundle','image','prompt','prompt')]
    if extract_master:
        nodes.append(node('extract', 'prompt.extract_section'))
        next(e for e in edges if e['id']=='skill-bundle')['source']='extract'
        edges.append(edge('skill-extract','skill','extract','prompt','prompt'))
    contract={'schema_version':'workflow.contract.draft.v1','inputs':[{'key':'outfit','label':'Outfit','type':'artifact','required':True,'validation':{'artifact_types':['Image']}}],'bindings':[{'target':{'node_id':'ref3','path':'/config/artifact_id'},'value':{'kind':'input','key':'outfit'}}],'outputs':[{'key':'image','label':'Dressed character','node_id':'image','port_key':'image','port_type':'media.image.v1','primary':True},{'key':'description','label':'Observed action','node_id':'describe','port_key':'prompt','port_type':'prompt.text.v1','primary':False}]}
    canvas=client.post('/canvases',json={'name':'Action transfer','document':canonicalize_canvas_document(nodes,edges),'draft_contract':contract}).json()
    workflow=client.post('/workflows',json={'name':'Action transfer','source_canvas_id':canvas['id']}).json()
    saved=client.get('/canvases/'+canvas['id']).json()
    published=client.post('/workflows/'+workflow['id']+'/publish',json={'expected_canvas_revision':saved['revision']})
    assert published.status_code==201,published.text
    version=published.json();assert 'unused' not in [n['id'] for n in version['graph']['nodes']]
    run=client.post('/workflows/'+workflow['id']+'/runs',json={'version':1,'inputs':{'outfit':refs[4]}}).json()
    until=time.monotonic()+5
    while time.monotonic()<until:
        run=client.get('/canvas-runs/'+run['id']).json()
        if run['status'] in ['SUCCEEDED','FAILED']:break
        time.sleep(.03)
    assert run['status']=='SUCCEEDED',[(n['canvas_node_id'],n.get('error')) for n in run['node_runs'] if n.get('error')]
    assert len(vision_calls)==len(image_calls)==1
    assert run['inputs']['outfit']==refs[4]
    assert run['model_snapshot']['describe']['definition_digest']==node_registry.get('image.describe',1).definition_digest
    unchanged=client.get('/workflows/'+workflow['id']+'/versions/1').json()
    assert unchanged['content_hash']==version['content_hash']
