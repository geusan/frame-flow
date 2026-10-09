import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {createRequire} from 'node:module';
import {mkdirSync,mkdtempSync,rmSync,writeFileSync} from 'node:fs';
import {join,resolve,dirname} from 'node:path';
const require=createRequire(import.meta.url),cache=resolve(import.meta.dirname,'../../../node_modules/.cache');mkdirSync(cache,{recursive:true});const out=mkdtempSync(join(cache,'e13-test-'));
try{
 execFileSync(process.execPath,[join(dirname(require.resolve('typescript/package.json')),'bin/tsc'),resolve(import.meta.dirname,'../../../packages/studio/src/features/avatar-2d/shoulder-attachment-e13.ts'),resolve(import.meta.dirname,'../../../packages/studio/src/features/avatar-2d/shoulder-handle-e12.ts'),'--ignoreConfig','--outDir',out,'--target','ES2022','--module','commonjs','--skipLibCheck'],{stdio:'inherit'});
 const {attachmentPoseE13,PROPOSED_CAP}=require(join(out,'shoulder-attachment-e13.js'));
 const {tangentPoseE13Base,crossSectionWidths}=require(join(out,'shoulder-base-e13.js'));
 const {tangentPoseE11}=require(join(out,'shoulder-tangent-e11.js'));
 const {tangentAngles}=require(join(out,'shoulder-tangent-e10.js'));
 const {neckDiagnostics}=require(join(out,'shoulder-handle-e12.js'));
 const {metrics,sampleCurves}=require(join(out,'shoulder-contour-e09.js'));
 for(const angle of [45,90,135])assert.deepEqual(tangentPoseE13Base(angle,'aligned'),tangentPoseE11(angle,'aligned'),'frozen policy parity');
 const a=attachmentPoseE13('baseline'),before=JSON.stringify(a),b=attachmentPoseE13('relocated');
 assert.equal(a.applicable,false);assert.equal(a.scale,null);assert.ok(a.gap<0);
 assert.equal(b.applicable,true);assert.deepEqual(b.pose.cap,PROPOSED_CAP);assert.ok(b.scale>0&&b.scale<1);
 for(let i=0;i<11;i++){
  assert.deepEqual(b.pose.curves[i][3],b.pose.curves[(i+1)%11][0]);
  if(i!==1&&i!==2)assert.deepEqual(b.pose.curves[i],a.pose.curves[i],'nine non-target curves identical');
 }
 assert.deepEqual(b.pose.curves[1][0],a.pose.curves[1][0]);assert.deepEqual(b.pose.curves[2][3],a.pose.curves[2][3]);
 assert.deepEqual(b.pose.shoulder,a.pose.shoulder);assert.deepEqual(b.pose.elbow,a.pose.elbow);
 assert.deepEqual(crossSectionWidths(a.pose),crossSectionWidths(b.pose));
 assert.ok(tangentAngles(b.pose.curves).every(t=>t.degrees<1e-9));
 assert.equal(metrics(b.pose).crossings,0);assert.equal(sampleCurves(b.pose.curves).length,176);
 assert.ok(neckDiagnostics(b.pose.curves[1]).minDx>0);
 const c=b.pose.curves[1];for(let i=1;i<4;i++){assert.ok(c[i][0]>=c[i-1][0]-1e-9);assert.ok(c[i][1]<=c[i-1][1]+1e-9);}
 assert.equal(JSON.stringify(a),before);assert.deepEqual(attachmentPoseE13('relocated'),b);
 const report={experiment:'E13',numeric:'PASS_STATIC_SCOPE',visual:'local neck defect improved; full shoulder/axilla unverified',motion:'not evaluated',baseline:a,candidate:b,baselineDiagnostics:neckDiagnostics(a.pose.curves[1]),candidateDiagnostics:neckDiagnostics(b.pose.curves[1]),widths:crossSectionWidths(b.pose),tangents:tangentAngles(b.pose.curves)};
 if(process.argv.includes('--record'))writeFileSync(resolve(import.meta.dirname,'../../../docs/avatar-rig-research/references/evidence/E13/results.json'),JSON.stringify(report,null,2)+'\n');
 console.log(JSON.stringify({baselineGap:a.gap,newCap:b.pose.cap,scale:b.scale,minDx:report.candidateDiagnostics.minDx,widths:report.widths},null,2));
 console.log('Static invariants passed; not a full skin/motion validation.');
}finally{rmSync(out,{recursive:true,force:true});}
