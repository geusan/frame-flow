import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { renameWorkflowInput, bindingValue, workflowOutputOptions, workflowTargets, outputReachability } from '../src/features/workflows/draft-contract.ts';
import { migrateStoredGraph } from '../src/features/nodes/legacy-canvas-loader.ts';
import { latestNodeTemplates, nodeTemplateFromDefinition } from '../src/features/nodes/contracts.ts';

const root = new URL('../../api/app/nodes/', import.meta.url);
const definitions = readdirSync(new URL('definitions/', root)).filter(name => name.endsWith('.json')).flatMap(name => JSON.parse(readFileSync(new URL(`definitions/${name}`, root))));
const ports = JSON.parse(readFileSync(new URL('port_types.v1.json', root)));
const contract = { schema_version: 'workflow.contract.draft.v1', inputs: [{key:'topic', type:'prompt'}, {key:'place', type:'string'}], bindings: [
  {target:{node_id:'a',path:'/config/text'},value:{kind:'template',template:'{{topic}} / {{topic}} at {{place}}',input_keys:['topic','place']}},
  {target:{node_id:'b',path:'/config/text'},value:{kind:'input',key:'topic'}},
], outputs: [] };
const renamed = renameWorkflowInput(contract,0,{key:'subject'});
assert.equal(renamed.bindings[0].value.template, '{{subject}} / {{subject}} at {{place}}');
assert.deepEqual(renamed.bindings[0].value.input_keys,['subject','place']);
assert.equal(renamed.bindings[1].value.key,'subject');
assert.equal(contract.inputs[0].key,'topic');
assert.deepEqual(bindingValue('template','{{a}} {{b}} {{a}}').input_keys,['a','b']);
const templates = definitions.map(definition => nodeTemplateFromDefinition(definition, ports));
const saved = {nodes:[{id:'old',position:{x:5,y:8},data:{key:'image.motion',contractVersion:1,config:{duration_seconds:8}}}, {id:'unknown',position:{x:8,y:9},data:{key:'video.future_frame_extract',config:{opaque:true}}}], edges:[{id:'edge',source:'unknown',target:'old',sourceHandle:'future-output',targetHandle:'future-input'}]};
const loaded = migrateStoredGraph(saved,templates);
assert.equal(loaded.nodes.length,2);
assert.equal(loaded.nodes[0].data.contractVersion,1);
assert.equal(loaded.nodes[0].data.config.duration_seconds,8);
assert.deepEqual(loaded.nodes[1].data.config,{opaque:true});
assert.equal(loaded.nodes[1].data.executable,false);
assert.equal(loaded.edges[0].sourceHandle,'future-output');
assert.equal(loaded.edges[0].targetHandle,'future-input');
assert.ok(latestNodeTemplates(definitions,ports).every(template => definitions.some(definition => definition.type_key===template.data.key && definition.contract_version===template.data.contractVersion && definition.lifecycle==='ACTIVE')));
const prompt = {id:'prompt',data:{...templates.find(item=>item.data.key==='prompt.input').data}};
assert.ok(workflowTargets([prompt],definitions).some(target=>target.path==='/config/text'));
const options = workflowOutputOptions([prompt],definitions);
assert.equal(options[0].portType,'prompt.text.v1');
assert.deepEqual([...outputReachability([{node_id:'a'},{node_id:'b'}],[{source:'root',target:'a'},{source:'root',target:'b'},{source:'unused',target:'unused'}])].sort(),['a','b','root']);
console.log('Workflow authoring: shared inputs, token rename, typed outputs, reachability, pinned versions and lossless unknown graph load passed.');
const {workflowVersionDiff}=await import('../src/features/workflows/version-diff.ts');
const before={graph:{nodes:[{id:'a',config:{text:'old'}}],edges:[]}, input_schema:{inputs:[]},bindings:{bindings:[]},output_schema:{outputs:[]}};
const after=structuredClone(before);after.graph.nodes[0].config.text='new';
assert.deepEqual(workflowVersionDiff(before,after),[{path:'nodes.a.config.text',before:'old',after:'new'}]);
assert.deepEqual(workflowVersionDiff(before,structuredClone(before)),[]);
console.log('Frozen version diff compares stored configs without consulting registry defaults.');
const {inputPortMatches}=await import('../src/lib/canvas-model.ts');
const modelNode={id:'model',data:templates.find(item=>item.data.key==='character.auto_rig' && item.data.contractVersion===1).data};
assert.equal(modelNode.data.outputPorts.length,2);
assert.ok(inputPortMatches(modelNode,modelNode.data.inputPorts[0].key,0));
assert.ok(inputPortMatches(modelNode,`input-${modelNode.data.inputTypes[0]}-0`,0));
assert.ok(!inputPortMatches(modelNode,'missing',0));
const imageGenerator={id:'image',data:templates.find(item=>item.data.key==='image.generate').data};
assert.ok(inputPortMatches(imageGenerator,'prompt',0));
assert.ok(inputPortMatches(imageGenerator,'input-Prompt-0',0));
console.log('Manifest port metadata includes all outputs and supports canonical/legacy input handles.');
for (const key of ['video.frame_extract','video.animate_image']) {
  const definition = definitions.find(d=>d.type_key===key);
  const template = templates.find(t=>t.data.key===key);
  assert.equal(definition.editor.kind,'generic');
  assert.ok(template.data.executable);
  assert.equal(template.data.outputPorts.length,1);
  assert.ok(workflowTargets([{id:key,data:template.data}],definitions).length>0);
}
assert.equal(templates.find(t=>t.data.key==='video.frame_extract').data.outputPorts[0].type,'media.image.v1');
assert.equal(templates.find(t=>t.data.key==='video.animate_image').data.inputPorts.find(p=>p.key==='image').required,true);
const {nodeHumanGateMode}=await import('../src/features/nodes/contracts.ts');
assert.equal(nodeHumanGateMode(definitions.find(d=>d.type_key==='candidate.select')),'select_artifact');
assert.equal(nodeHumanGateMode(definitions.find(d=>d.type_key==='timeline.compose' && d.contract_version===1)),'approve');
assert.equal(nodeHumanGateMode(definitions.find(d=>d.type_key==='image.generate')),undefined);
console.log('Manifest human gate policy preserves legacy approval and candidate-selection semantics.');
const imageDescription = definitions.find(d => d.type_key === 'image.describe' && d.contract_version === 1);
const imageDescriptionTemplate = nodeTemplateFromDefinition(imageDescription, ports);
assert.equal(imageDescription.editor.kind, 'generic');
assert.equal(imageDescriptionTemplate.data.inputPorts.find(p => p.key === 'image').type, 'media.image.v1');
assert.equal(imageDescriptionTemplate.data.outputPorts[0].type, 'prompt.text.v1');
assert.ok(workflowTargets([{id:'describe',data:imageDescriptionTemplate.data}],definitions).some(t => t.path === '/config/instructions'));
const descriptionRoundTrip = migrateStoredGraph({nodes:[{id:'describe',position:{x:20,y:30},data:{...imageDescriptionTemplate.data,config:{instructions:'Describe visible action only.',image_detail:'high',max_output_tokens:2400}}}],edges:[]},templates);
assert.equal(descriptionRoundTrip.nodes[0].data.config.instructions, 'Describe visible action only.');
console.log('Image description: Registry library, generic editor, image/prompt ports and workflow-input exposure passed.');
for (const key of ['prompt.extract_section', 'prompt.combine']) {
  const definition = definitions.find(d => d.type_key === key && d.contract_version === 1);
  const template = nodeTemplateFromDefinition(definition, ports);
  assert.equal(definition.editor.kind, 'generic');
  assert.equal(template.data.outputPorts[0].type, 'prompt.text.v1');
  assert.ok(template.data.inputPorts.every(port => port.type === 'prompt.text.v1'));
  assert.ok(template.data.executable);
}
assert.ok(workflowTargets([{id:'section',data:templates.find(t=>t.data.key==='prompt.extract_section').data}],definitions).some(t=>t.path==='/config/heading'));
assert.equal(templates.find(t=>t.data.key==='prompt.combine').data.inputPorts.length,2);
console.log('Prompt composition: registered generic editors, two distinct typed inputs and section-heading binding passed.');
