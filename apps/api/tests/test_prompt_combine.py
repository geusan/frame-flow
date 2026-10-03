import asyncio
import hashlib
import time
from types import SimpleNamespace

import pytest
from temporalio.testing import ActivityEnvironment

from app import canvas_activities
from app.canvas_documents import canonicalize_canvas_document
from app.canvas_runs import create_canvas_run, execute_canvas_node
from app.database import SessionLocal
from app.domain import CanvasRunRequest, ExperimentRunRequest
from app.experiments import request_fingerprint, resolve_model
from app.nodes import node_registry
from app.nodes.executors.prompt_combine import PromptCombineError, prompt_part

CHARACTER = 'FIXED CHARACTER: canonical face and short white/pink bob. Preserve bust volume/projection, shoulders, ribcage, waist, hips and limb proportions. Fit clothing to this unchanged body; do not flatten, shrink or enlarge it.\n'
WASH = 'Refine only the situation and character rendering in that situation. The separately provided character definition is read-only context. Do not rewrite its intrinsic traits. Return the usual three NOTTALGGAK sections.'


def test_parts_are_unmodified_and_wrong_ports_fail():
    text='  fixed text\n'
    assert prompt_part([{'target_port':'fixed','config_text':text}], 'fixed') == (text, [])
    for items in [[],[{'target_port':'variable','output_text':'wrong'}],[{'target_port':'fixed','output_text':' '}],[{'target_port':'fixed','output_text':'a'},{'target_port':'fixed','output_text':'b'}]]:
        with pytest.raises(PromptCombineError) as error:prompt_part(items,'fixed')
        assert error.value.retryable is False


def test_config_ports_and_request_hash():
    d=node_registry.get('prompt.combine',1)
    assert [p.key for p in d.ports.inputs]==['fixed','variable']
    assert all(p.required and p.type=='prompt.text.v1' for p in d.ports.inputs)
    assert node_registry.resolve_config(d,{})=={'separator':'\n\n'}
    for config in [{'separator':1},{'separator':'x'*201},{'extra':True}]:
        with pytest.raises(ValueError):node_registry.resolve_config(d,config)
    p=ExperimentRunRequest(canvas_id='c',node_id='combine',node_key='prompt.combine',model_alias='local.prompt-combine',inputs=[{'target_port':'fixed','config_text':CHARACTER},{'target_port':'variable','output_text':'scene'}])
    alias,exact=resolve_model(p.model_alias,p.node_key,1);before=request_fingerprint(p,alias,exact)
    assert request_fingerprint(p.model_copy(update={'parameters':{'separator':'\n'}}),alias,exact)!=before
    assert request_fingerprint(p.model_copy(update={'inputs':[{'target_port':'fixed','config_text':'changed'},{'target_port':'variable','output_text':'scene'}]}),alias,exact)!=before


@pytest.mark.parametrize('temporal',[False,True])
def test_combination_local_temporal_parity(client,temporal):
    nodes=[{'id':'fixed','data':{'key':'prompt.input','configText':CHARACTER}}, {'id':'scene','data':{'key':'prompt.input','configText':'  Scene rendering.\n'}}, {'id':'combine','data':{'key':'prompt.combine','model':'local.prompt-combine','config':{'separator':'\n\n'}}}]
    edges=[{'id':'a','source':'fixed','target':'combine','sourceHandle':'prompt','targetHandle':'fixed'},{'id':'b','source':'scene','target':'combine','sourceHandle':'prompt','targetHandle':'variable'}]
    c=client.post('/canvases',json={'name':'Combine','document':canonicalize_canvas_document(nodes,edges)}).json()
    with SessionLocal() as db:rid=create_canvas_run(db,CanvasRunRequest(canvas_id=c['id'],canvas_revision=c['revision'],target_node_id='combine')).id
    result=asyncio.run(ActivityEnvironment().run(canvas_activities.execute_canvas_node_activity,rid,'combine')) if temporal else execute_canvas_node(rid,'combine')
    artifact=client.get('/artifacts/'+result['artifact_ids'][0]).json()
    assert client.get('/artifacts/'+artifact['id']+'/content').text==CHARACTER+'\n\n  Scene rendering.\n'
    assert artifact['schema_id']=='prompt.combined.v1' and artifact['type']=='Text'
    assert artifact['metadata']['fixed_prompt_sha256']==hashlib.sha256(CHARACTER.encode()).hexdigest()
    assert artifact['metadata']['normalized_config']=={'separator':'\n\n'}
    assert execute_canvas_node(rid,'combine')['artifact_ids']==result['artifact_ids']


def test_character_is_readonly_context_and_unchanged_in_final_prompt(client,monkeypatch):
    from test_image_description import upload, node, edge, png
    monkeypatch.setenv('GENERATION_PROVIDER_MODE','live')
    ids=[upload(client,c) for c in ['red','green','blue','white','yellow']]
    seen_refinement=[];seen_images=[]
    def describe(**kwargs):
        return ('Scene one' if kwargs['images'][0].artifact_id==ids[3] else 'Scene two'),'vision',{'usage':{},'response_model':'vision'}
    def refine(**kwargs):
        assert CHARACTER in kwargs['prompt'] and WASH in kwargs['prompt']
        seen_refinement.append(kwargs['prompt'])
        scene=('Scene one' if 'Scene one' in kwargs['prompt'] else 'Scene two')+'; knit drapes over the fixed bust, with shadows matching the scene.'
        return '### 1. English Master Prompt\n'+scene+'\n\n### 2. Korean Translation\n검토용 번역\n\n### 3. Technical / Visual Blueprint\n검토용 설계','refinement'
    def generate(**kwargs):
        seen_images.append(kwargs)
        assert kwargs['prompt'].startswith(CHARACTER+'\n\n')
        assert kwargs['prompt'].count(CHARACTER)==1
        assert WASH not in kwargs['prompt']
        assert all(x not in kwargs['prompt'] for x in ['NOTTALGGAK','English Master Prompt','Korean Translation','Blueprint','검토용'])
        return [png()],'image'
    service=SimpleNamespace(generate_vision_text=describe,generate_text=refine,generate_images=generate)
    for module in ['image_description','text_generation','image_generation']:monkeypatch.setattr('app.nodes.executors.'+module+'.get_openai_generation_services',lambda:service)
    nodes=[node('ref'+str(i),'asset.select',{'artifact_id':id,'artifact_type':'Image'},version=2) for i,id in enumerate(ids[:4])]
    nodes += [node('character','prompt.input',{'text':CHARACTER}),node('wash','prompt.input',{'text':WASH}),node('describe','image.describe'),node('context','prompt.combine'),node('skill','skill.execute',{'skill_id':'nottalggak-prompt-machine'},version=2,model='openai.chat.latest'),node('section','prompt.extract_section'),node('combine','prompt.combine'),node('bundle','prompt.input',{'text':''}),node('image','image.generate',model='openai.image.default')]
    edges=[edge('ref'+str(i),'ref'+str(i),'bundle','artifact','images') for i in range(4)]
    edges += [edge('photo','ref3','describe','artifact','image'),edge('wash','wash','describe','prompt','prompt'),edge('readonly','character','context','prompt','fixed'),edge('observation','describe','context','prompt','variable'),edge('context','context','skill','prompt','prompt'),edge('extract','skill','section','prompt','prompt'),edge('fixed','character','combine','prompt','fixed'),edge('scene','section','combine','prompt','variable'),edge('final','combine','bundle','prompt','prompt'),edge('render','bundle','image','prompt','prompt')]
    contract={'schema_version':'workflow.contract.draft.v1','inputs':[{'key':'outfit','label':'Photo','type':'artifact','required':True,'validation':{'artifact_types':['Image']}}],'bindings':[{'target':{'node_id':'ref3','path':'/config/artifact_id'},'value':{'kind':'input','key':'outfit'}}],'outputs':[{'key':'image','label':'Image','node_id':'image','port_key':'image','port_type':'media.image.v1','primary':True}]}
    c=client.post('/canvases',json={'name':'Fixed character + refined scene','document':canonicalize_canvas_document(nodes,edges),'draft_contract':contract}).json()
    w=client.post('/workflows',json={'name':'Fixed character + refined scene','source_canvas_id':c['id']}).json();c=client.get('/canvases/'+c['id']).json()
    published=client.post('/workflows/'+w['id']+'/publish',json={'expected_canvas_revision':c['revision']});assert published.status_code==201,published.text
    version=published.json()
    for image_id in ids[3:]:
        response=client.post('/workflows/'+w['id']+'/runs',json={'version':1,'inputs':{'outfit':image_id}});assert response.status_code==201,response.text
        run=response.json();until=time.monotonic()+5
        while time.monotonic()<until:
            run=client.get('/canvas-runs/'+run['id']).json()
            if run['status'] in ['SUCCEEDED','FAILED']:break
            time.sleep(.03)
        assert run['status']=='SUCCEEDED',[(n['canvas_node_id'],n.get('error')) for n in run['node_runs'] if n.get('error')]
        by_id={n['canvas_node_id']:n for n in run['node_runs']}
        final=by_id['combine']['output']['text'];scene=by_id['section']['output']['text']
        assert final==CHARACTER+'\n\n'+scene==seen_images[-1]['prompt']
        assert [i.artifact_id for i in seen_images[-1]['reference_images']]==ids[:3]+[image_id]
        artifact=client.get('/artifacts/'+by_id['combine']['output_artifact_ids'][0]).json()
        assert artifact['input_artifact_ids']==by_id['section']['output_artifact_ids']
        assert artifact['metadata']['fixed_prompt_sha256']==hashlib.sha256(CHARACTER.encode()).hexdigest()
        assert client.get('/workflows/'+w['id']+'/versions/1').json()['content_hash']==version['content_hash']
    assert len(seen_images)==len(seen_refinement)==2
    assert seen_images[0]['prompt']!=seen_images[1]['prompt']
