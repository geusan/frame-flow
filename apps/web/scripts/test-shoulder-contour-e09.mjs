import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {createRequire} from 'node:module';
import {mkdirSync,mkdtempSync,rmSync,writeFileSync} from 'node:fs';
import {join,resolve,dirname} from 'node:path';
const require=createRequire(import.meta.url);
const cache=resolve(import.meta.dirname,'../../../node_modules/.cache');mkdirSync(cache,{recursive:true});
const output=mkdtempSync(join(cache,'e09-test-'));
try {
 execFileSync(process.execPath,[join(dirname(require.resolve('typescript/package.json')),'bin/tsc'),resolve(import.meta.dirname,'../../../packages/studio/src/features/avatar-2d/shoulder-contour-e09.ts'),'--ignoreConfig','--outDir',output,'--target','ES2022','--module','commonjs','--skipLibCheck'],{stdio:'inherit'});
 const {contourPose,metrics,sampleCurves,VARIANTS,REST_ELEVATION}=require(join(output,'shoulder-contour-e09.js'));
 const rows=[];
 // Static protocol only. Deliberately no intermediate-angle sweep after visual failure.
 for(const angle of [0,REST_ELEVATION,45,90,135,160]) {
  const base=contourPose(angle,'minimal');
  for(const variant of VARIANTS) {
   const pose=contourPose(angle,variant),m=metrics(pose);
   assert.equal(pose.curves.length,11);assert.equal(sampleCurves(pose.curves).length,176);
   for(let i=0;i<pose.curves.length;i++)assert.deepEqual(pose.curves[i][3],pose.curves[(i+1)%pose.curves.length][0],'shared boundary endpoints');
   assert.ok(sampleCurves(pose.curves).flat().every(Number.isFinite));
   assert.ok(Math.abs(m.upperLength-Math.hypot(64,180))<1e-9);
   assert.deepEqual(pose.shoulder,base.shoulder);assert.deepEqual(pose.elbow,base.elbow);
   for(const i of [0,3,4,5,8,9,10])assert.deepEqual(pose.curves[i],base.curves[i],'nonlocal boundary unchanged');
   assert.deepEqual(contourPose(angle,variant),pose,'same static input is deterministic');
   assert.deepEqual(contourPose(NaN,variant),contourPose(REST_ELEVATION,variant));
   assert.deepEqual(contourPose(-1,variant),contourPose(0,variant));
   assert.deepEqual(contourPose(161,variant),contourPose(160,variant));
   rows.push({angle,variant,...m,geometryVerdict:m.crossings?'FAIL_SELF_INTERSECTION':'NO_SAMPLED_CROSSING_ONLY'});
  }
 }
 const report={experiment:'E09',scope:'six static poses only; boundary study, no interior skin mesh',protocolAssertions:'pass',visualVerdict:'FAIL; see experiments.md',motion:'not evaluated: static visual gate failed',rows};
 const evidence=resolve(import.meta.dirname,'../../../docs/avatar-rig-research/references/evidence/E09');
 if(process.argv.includes('--record'))writeFileSync(join(evidence,'static-metrics.json'),JSON.stringify(report,null,2)+'\n');
 console.table(rows.map(({angle,variant,crossings,rootToPit,pitDrop})=>({angle:angle.toFixed(2),variant,crossings,rootToPit:rootToPit.toFixed(2),pitDrop:pitDrop.toFixed(2)})));
 console.log('Protocol checks passed. E09 STATIC GEOMETRY/VISUAL FAILURES ARE REPORTED, NOT PASSED. No motion or skin validation.');
} finally {rmSync(output,{recursive:true,force:true});}
