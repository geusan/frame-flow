import asyncio
import json
from pathlib import Path

import pytest
from temporalio.testing import ActivityEnvironment

from app import canvas_activities
from app.canvas_documents import canonicalize_canvas_document
from app.canvas_runs import create_canvas_run, execute_canvas_node
from app.database import SessionLocal
from app.domain import CanvasRunRequest, ExperimentRunRequest
from app.experiments import request_fingerprint, resolve_model
from app.nodes import node_registry
from app.nodes.executors.prompt_section import PromptSectionError, extract_prompt_section

MASTER = 'Keep the canonical bust volume and forward projection, shoulder/ribcage/waist/hip/limb proportions. Fit clothes to the body without flattening, shrinking or enlarging it. Recreate the observed action and lighting.'
DOCUMENT = f'### 1. English Master Prompt\n\n{MASTER}\n\n### 2. Korean Translation\n번역: 제작 검토용\n\n### 3. Technical / Visual Blueprint\nReview-only blueprint.'


@pytest.mark.parametrize('document,expected', [
    (DOCUMENT, MASTER),
    ('## 1. English Master Prompt ##\r\nText\r\n### Detail\r\nKept\r\n## Next\r\nExcluded', 'Text\n### Detail\nKept'),
    ('```md\n### 1. English Master Prompt\nfake\n```\n'+DOCUMENT, MASTER),
    ('### 1. English Master Prompt\nfinal body', 'final body'),
])
def test_section_extraction_preserves_only_selected_body(document, expected):
    assert extract_prompt_section(document, '1. English Master Prompt') == expected


@pytest.mark.parametrize('document', ['', 'no section, never use the whole document', '### 1. English Master Prompt\n\n### 2. Korean Translation\ntext', DOCUMENT+'\n### 1. English Master Prompt\nDuplicated'])
def test_missing_empty_duplicate_sections_fail_without_fallback(document):
    with pytest.raises(PromptSectionError) as error:
        extract_prompt_section(document, '1. English Master Prompt')
    assert error.value.retryable is False


def test_manifest_defaults_and_cache_contract():
    d=node_registry.get('prompt.extract_section',1)
    assert d.editor.kind=='generic' and d.execution.kind=='local'
    assert d.ports.inputs[0].type==d.ports.outputs[0].type=='prompt.text.v1'
    config=node_registry.resolve_config(d,{})
    assert config=={'heading':'1. English Master Prompt'}
    for bad in [{'heading':''},{'heading':1},{'heading':'x'*201},{'script':'malicious'}]:
        with pytest.raises(ValueError):node_registry.resolve_config(d,bad)
    p=ExperimentRunRequest(canvas_id='c',node_id='extract',node_key=d.type_key,model_alias=d.execution.model_alias,prompt=DOCUMENT)
    alias,exact=resolve_model(p.model_alias,p.node_key,1)
    digest=request_fingerprint(p,alias,exact)
    for update in [{'prompt':DOCUMENT+' changed'},{'parameters':{'heading':'2. Korean Translation'}}]:
        assert request_fingerprint(p.model_copy(update=update),alias,exact)!=digest


@pytest.mark.parametrize('temporal',[False,True])
def test_local_temporal_parity_lineage_and_replay(client,temporal):
    from app.service import create_artifact
    with SessionLocal() as db:
        source=create_artifact(db,'Prompt',schema_id='prompt.text.v1',content=DOCUMENT.encode(),content_type='text/plain',filename='master.txt')
        db.commit()
        artifact=source.id
    nodes=[{'id':'source','data':{'key':'prompt.input','configText':DOCUMENT,'outputArtifactIds':[artifact]}}, {'id':'extract','data':{'key':'prompt.extract_section','contractVersion':1,'config':{},'model':'local.prompt-section'}}]
    edges=[{'id':'edge','source':'source','target':'extract','sourceHandle':'prompt','targetHandle':'prompt'}]
    c=client.post('/canvases',json={'name':'Select final prompt','document':canonicalize_canvas_document(nodes,edges)}).json()
    with SessionLocal() as db:
        rid=create_canvas_run(db,CanvasRunRequest(canvas_id=c['id'],canvas_revision=c['revision'],target_node_id='extract')).id
    result=asyncio.run(ActivityEnvironment().run(canvas_activities.execute_canvas_node_activity,rid,'extract')) if temporal else execute_canvas_node(rid,'extract')
    output=client.get('/artifacts/'+result['artifact_ids'][0]).json()
    content=client.get('/artifacts/'+output['id']+'/content').text
    assert content==MASTER
    assert output['type']=='Text' and output['schema_id']=='prompt.section.v1'
    assert output['input_artifact_ids']==[artifact]
    assert output['metadata']['input_artifact_roles'][artifact]=='source_prompt'
    assert output['metadata']['normalized_config']=={'heading':'1. English Master Prompt'}
    assert output['metadata']['definition_digest']==node_registry.get('prompt.extract_section',1).definition_digest
    assert output['metadata']['execution_mode']=='prompt-section.v1'
    assert execute_canvas_node(rid,'extract')['artifact_ids']==result['artifact_ids']


def test_failed_selection_is_non_retryable(client):
    from app.experiments import run_experiment
    with SessionLocal() as db:
        result=run_experiment(db,ExperimentRunRequest(canvas_id='c',node_id='extract',node_key='prompt.extract_section',model_alias='local.prompt-section',prompt='No heading'))
        assert result.status=='FAILED' and result._failure_retryable is False
