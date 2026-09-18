import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {createRequire} from 'node:module';
import {mkdirSync,mkdtempSync,rmSync,writeFileSync} from 'node:fs';
import {join,resolve,dirname} from 'node:path';
const require=createRequire(import.meta.url);
const cache=resolve(import.meta.dirname,'../../../node_modules/.cache');mkdirSync(cache,{recursive:true});
const output=mkdtempSync(join(cache,'e10-test-'));
try{
 execFileSync(process.execPath,[join(dirname(require.resolve('typescript/package.json')),'bin/tsc'),resolve(import.meta.dirname,'../src/features/avatar-2d/shoulder-tangent-e10.ts'),'--ignoreConfig','--outDir',output,'--target','ES2022','--module','commonjs','--skipLibCheck'],{stdio:'inherit'});
 const {tangentPose,tangentAngles,actualWidths}=require(join(output,'shoulder-tangent-e10.js'));
 const {contourPose,metrics,sampleCurves}=require(join(output,'shoulder-contour-e09.js'));
 const baseline=tangentPose('baseline'),before=JSON.stringify(baseline),candidate=tangentPose('aligned');
 assert.deepEqual(baseline,contourPose(90,'helper'),'actual E09 B comparison');
 assert.deepEqual(candidate.shoulder,baseline.shoulder);assert.deepEqual(candidate.elbow,baseline.elbow);
 assert.equal(candidate.curves.length,11);assert.equal(sampleCurves(candidate.curves).length,176);
 const distance=(a,b)=>Math.hypot(a[0]-b[0],a[1]-b[1]);
 for(let i=0;i<11;i++){
  const a=baseline.curves[i],b=candidate.curves[i];
  assert.deepEqual(b[0],a[0]);assert.deepEqual(b[3],a[3]);
  assert.deepEqual(b[3],candidate.curves[(i+1)%11][0]);
  assert.ok(Math.abs(distance(a[0],a[1])-distance(b[0],b[1]))<1e-9,'start handle length fixed');
  assert.ok(Math.abs(distance(a[3],a[2])-distance(b[3],b[2]))<1e-9,'end handle length fixed');
 }
 for(const i of [0,3,4,5,8,9,10])assert.deepEqual(candidate.curves[i],baseline.curves[i],'non-target segments unchanged');
 assert.ok(tangentAngles(candidate.curves).every(j=>j.degrees<1e-9),'G1 direction alignment at selected seams');
 assert.ok(tangentAngles(baseline.curves).some(j=>j.degrees>70),'baseline must retain observed defect');
 assert.equal(metrics(candidate).crossings,0,'no crossing in fixed sampled boundary');
 assert.deepEqual(actualWidths(candidate.curves,candidate.shoulder),actualWidths(baseline.curves,baseline.shoulder));
 assert.equal(JSON.stringify(baseline),before,'baseline remains immutable');
 assert.deepEqual(tangentPose('aligned'),candidate,'repeatable static pose');
 const report={experiment:'E10',angle:90,numericVerdict:'PASS_SCOPED_STATIC_INVARIANTS',visualVerdict:'LOCAL_SEAM_IMPROVEMENT; full skin naturalness not validated',motionPerformance:'NOT_EVALUATED_SINGLE_STATIC_POSE',baseline:{tangents:tangentAngles(baseline.curves),actualCrossSectionWidths:actualWidths(baseline.curves,baseline.shoulder),...metrics(baseline)},candidate:{tangents:tangentAngles(candidate.curves),actualCrossSectionWidths:actualWidths(candidate.curves,candidate.shoulder),...metrics(candidate)}};
 if(process.argv.includes('--record')){
  const dest=resolve(import.meta.dirname,'../../../docs/avatar-rig-research/references/evidence/E10');
  writeFileSync(join(dest,'metrics.json'),JSON.stringify(report,null,2)+'\n');
  writeFileSync(join(dest,'pose-90.json'),JSON.stringify({baseline,candidate},null,2)+'\n');
 }
 console.log(JSON.stringify(report,null,2));
}finally{rmSync(output,{recursive:true,force:true});}
