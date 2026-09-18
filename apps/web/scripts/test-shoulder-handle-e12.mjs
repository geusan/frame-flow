import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {createRequire} from 'node:module';
import {mkdirSync,mkdtempSync,rmSync,writeFileSync} from 'node:fs';
import {join,resolve,dirname} from 'node:path';
const require=createRequire(import.meta.url);
const cache=resolve(import.meta.dirname,'../../../node_modules/.cache');mkdirSync(cache,{recursive:true});
const output=mkdtempSync(join(cache,'e12-test-'));
try{
 execFileSync(process.execPath,[join(dirname(require.resolve('typescript/package.json')),'bin/tsc'),resolve(import.meta.dirname,'../src/features/avatar-2d/shoulder-handle-e12.ts'),'--ignoreConfig','--outDir',output,'--target','ES2022','--module','commonjs','--skipLibCheck'],{stdio:'inherit'});
 const {handlePoseE12,neckDiagnostics}=require(join(output,'shoulder-handle-e12.js'));
 const {tangentPoseE11,crossSectionWidths}=require(join(output,'shoulder-tangent-e11.js'));
 const {tangentAngles}=require(join(output,'shoulder-tangent-e10.js'));
 const {metrics,sampleCurves}=require(join(output,'shoulder-contour-e09.js'));
 const reports=[];
 const parallel=(u,v)=>{
  assert.ok(u[0]*v[0]+u[1]*v[1]>0,'tangent direction must not reverse');
  assert.ok(Math.abs(u[0]*v[1]-u[1]*v[0])<1e-8,'handle remains parallel');
 };
 for(const angle of [45,90,135]){
  const base=handlePoseE12(angle,'baseline'),original=JSON.stringify(base);
  const next=handlePoseE12(angle,'limited'),a=base.pose,b=next.pose;
  assert.deepEqual(a,tangentPoseE11(angle,'aligned'));
  assert.equal(b.curves.length,11);assert.equal(sampleCurves(b.curves).length,176);
  for(let i=0;i<11;i++){
   assert.deepEqual(b.curves[i][0],a.curves[i][0]);assert.deepEqual(b.curves[i][3],a.curves[i][3]);
   assert.deepEqual(b.curves[i][3],b.curves[(i+1)%11][0]);
   if(i!==1)assert.deepEqual(b.curves[i],a.curves[i],'all ten non-target curves identical');
  }
  const ac=a.curves[1],bc=b.curves[1];
  for(const [anchor,handle] of [[0,1],[3,2]])parallel(ac[handle].map((n,k)=>n-ac[anchor][k]),bc[handle].map((n,k)=>n-bc[anchor][k]));
  assert.ok(tangentAngles(b.curves).every(j=>j.degrees<1e-9));
  assert.equal(metrics(b).crossings,0);
  assert.deepEqual(crossSectionWidths(a),crossSectionWidths(b));
  assert.deepEqual(b.shoulder,a.shoulder);assert.deepEqual(b.elbow,a.elbow);
  const diagnostics=neckDiagnostics(bc);
  assert.ok(diagnostics.minDx>0,'analytic derivative: no x backtracking over entire neck segment');
  for(let i=1;i<4;i++)assert.ok(bc[i][0]>=bc[i-1][0]-1e-10,'ordered x control polygon');
  if(angle===135){
   assert.ok(neckDiagnostics(ac).minDx<0,'preserved comparison must retain backtracking');
   assert.ok(next.scale>0&&next.scale<1);
   // At 135 both coordinate control sequences are monotone. The convex-hull
   // property bounds the whole curve within the endpoints: no hidden notch.
   for(let i=1;i<4;i++)assert.ok(bc[i][1]<=bc[i-1][1]+1e-10);
  }else{assert.equal(next.scale,1);assert.deepEqual(a,b,'45/90 poses unchanged');}
  assert.equal(JSON.stringify(base),original);assert.deepEqual(handlePoseE12(angle,'limited'),next);
  reports.push({angle,scale:next.scale,baseline:neckDiagnostics(ac),candidate:diagnostics,
   crossings:metrics(b).crossings,tangents:tangentAngles(b.curves),actualWidths:crossSectionWidths(b),baselinePose:a,candidatePose:b});
 }
 assert.throws(()=>handlePoseE12(136,'limited'),'only registered static angles');
 if(process.argv.includes('--record')){
  const dest=resolve(import.meta.dirname,'../../../docs/avatar-rig-research/references/evidence/E12');
  writeFileSync(join(dest,'results.json'),JSON.stringify({experiment:'E12',numeric:'PASS_STATIC_SCOPE',visual:'135_DEGREE_LOCAL_SPUR_REMOVED; see experiments.md for visual evidence',motion:'not evaluated',reports},null,2)+'\n');
 }
 console.table(reports.map(r=>({angle:r.angle,scale:r.scale,beforeMinDx:r.baseline.minDx,afterMinDx:r.candidate.minDx,oldHandles:r.baseline.handles.join('/'),newHandles:r.candidate.handles.join('/')})));
 console.log('Static 135-degree spur regression and preservation checks passed. Not a full skin/motion validation.');
}finally{rmSync(output,{recursive:true,force:true});}
