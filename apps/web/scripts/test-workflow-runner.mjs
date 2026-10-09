import assert from 'node:assert/strict';
import { httpImageUrl, missingWorkflowInputs, workflowPresentation, workflowRunInputs, workflowRunOutputs, rerunRequest, isActiveRun } from '../../../packages/studio/src/features/workflows/run-model.ts';

assert.equal(httpImageUrl(' https://example.com/outfit.png?size=large '), 'https://example.com/outfit.png?size=large');
for (const value of ['javascript:alert(1)', 'file:///tmp/image.png', 'data:image/png;base64,abc', 'https://user:password@example.com/image.png', 'not a URL']) assert.equal(httpImageUrl(value), null);
assert.deepEqual(missingWorkflowInputs([{key:'image',label:'옷 이미지',required:true},{key:'flag',label:'flag',required:true},{key:'count',label:'count',required:true}], {image:'',flag:false,count:0}), ['옷 이미지']);

const definition = {type_key:'some.source',contract_version:1,definition_digest:'pinned',execution:{kind:'source'},config_schema:{properties:{asset:{'x-workflow-input':{type:'artifact'}},character:{'x-workflow-input':{type:'character'}}}}};
const newerDefinition = {...definition,contract_version:2,definition_digest:'new',config_schema:{properties:{renamed:{'x-workflow-input':{type:'artifact'}}}}};
const version = {id:'v1',version_number:1,workflow_definition_id:'wf',bindings:{bindings:[{target:{node_id:'variable',path:'/config/asset'}}]},graph:{nodes:[
  {id:'fixed',type_key:'some.source',contract_version:1,definition_digest:'pinned',config:{asset:'face'},ui:{label:'얼굴'}},
  {id:'variable',type_key:'some.source',contract_version:1,definition_digest:'pinned',config:{asset:'outfit'},ui:{label:'옷'}},
  {id:'unknown',type_key:'missing',contract_version:7,config:{},ui:{label:'알 수 없는 단계'}},
],edges:[]},output_schema:{outputs:[{key:'result',label:'결과',node_id:'output',primary:true}]}};
const presentation = workflowPresentation(version,[newerDefinition,definition],[{id:'face',type:'Image',url:'/face.png'}],[{id:'character',name:'Character',images:[{artifact_id:'face'}]}]);
assert.deepEqual(presentation.references.map(x=>[x.label,x.artifactId,x.characterName]),[['얼굴','face','Character']]);
assert.deepEqual(presentation.functions.map(x=>x.id),['unknown']);
const run={workflow_definition_id:'wf',workflow_version_id:'v1',inputs:{image:'old-outfit'},node_runs:[{canvas_node_id:'output',status:'SUCCEEDED',output:{kind:'image',url:'/result.png'}}]};
assert.equal(workflowRunOutputs(run,version)[0].node.output.url,'/result.png');
assert.deepEqual(workflowRunOutputs(run,{...version,id:'v2'}),[]);
const inputVersion = {...version,input_schema:{inputs:[{key:'image',label:'당시 옷 사진',type:'artifact',validation:{artifact_types:['Image']}}]}};
const savedInput = workflowRunInputs(run,inputVersion,[])[0];
assert.equal(savedInput.artifactId,'old-outfit');
assert.equal(savedInput.artifactType,'Image'); // Still previewable when absent from the current asset library.
assert.equal(savedInput.label,'당시 옷 사진');
const currentVersion = {...inputVersion,id:'v2',input_schema:{inputs:[{key:'image',label:'새 버전 영상',type:'artifact',validation:{artifact_types:['Video']}}]}};
assert.equal(workflowRunInputs(run,currentVersion,[])[0].artifactType,undefined);
assert.equal(workflowRunInputs(run,currentVersion,[])[0].label,'image');
assert.equal(workflowRunInputs({...run,inputs:{image:'another-photo'}},inputVersion,[])[0].artifactId,'another-photo');
assert.deepEqual(workflowRunInputs({...run,inputs:{flag:false,count:0}},inputVersion,[]).map(input=>input.value),[false,0]);
const retry=rerunRequest(run,'wf',[version,{...version,id:'v2',version_number:2}]);
assert.deepEqual(retry,{version:1,inputs:{image:'old-outfit'}});
retry.inputs.image='changed';assert.equal(run.inputs.image,'old-outfit');
assert.throws(()=>rerunRequest(run,'different-workflow',[version]));
assert.throws(()=>rerunRequest(run,'wf',[]));
assert.ok(isActiveRun('QUEUED'));assert.ok(!isActiveRun('SUCCEEDED'));
console.log('Workflow runner: URL validation, required inputs, pinned references, saved input previews, declared outputs and immutable rerun inputs passed.');
