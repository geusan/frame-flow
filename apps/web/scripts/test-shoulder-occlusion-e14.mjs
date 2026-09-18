import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {createRequire} from 'node:module';
import {mkdirSync,mkdtempSync,rmSync,writeFileSync} from 'node:fs';
import {join,resolve,dirname} from 'node:path';
const require=createRequire(import.meta.url),cache=resolve(import.meta.dirname,'../../../node_modules/.cache');mkdirSync(cache,{recursive:true});const out=mkdtempSync(join(cache,'e14-test-'));
try{
 execFileSync(process.execPath,[join(dirname(require.resolve('typescript/package.json')),'bin/tsc'),resolve(import.meta.dirname,'../src/features/avatar-2d/shoulder-occlusion-e14.ts'),'--ignoreConfig','--outDir',out,'--target','ES2022','--module','commonjs','--skipLibCheck'],{stdio:'inherit'});
 const {occlusionSurfaces,ownershipAudit,paintOrder,winding}=require(join(out,'shoulder-occlusion-e14.js'));
 const {contourPose,metrics,sampleCurves}=require(join(out,'shoulder-contour-e09.js'));
 const s=occlusionSurfaces(),original=JSON.stringify(s),c=s.pose.curves;
 assert.deepEqual(s.pose,contourPose(0,'helper'));
 assert.deepEqual(s.arm.slice(0,5),c.slice(2,7));assert.deepEqual(s.torso.slice(0,2),c.slice(0,2));assert.deepEqual(s.torso.slice(3),c.slice(7));
 assert.deepEqual(s.arm.at(-1),[...s.torso[2]].reverse(),'shared diagnostic closure exactly reversed');
 for(const k of ['arm','torso'])for(let i=0;i<s[k].length;i++)assert.deepEqual(s[k][i][3],s[k][(i+1)%s[k].length][0]);
 assert.deepEqual(paintOrder('arm'),['torso','arm']);assert.deepEqual(paintOrder('torso'),['arm','torso']);
 const audit=ownershipAudit();assert.ok(audit.overlapArea>0,'real overlapping diagnostic regions');assert.equal(audit.orderSilhouetteDifferenceArea,0);assert.ok(audit.holes.length>0,'known unresolved hole must remain visible');
 for(const h of audit.holes)for(const k of ['arm','torso'])assert.equal(winding(h.centroid,sampleCurves(s[k])),0,'hole centroid belongs to neither surface');
 assert.equal(metrics(s.pose).crossings,2,'original geometry failure preserved');assert.equal(JSON.stringify(s),original);assert.deepEqual(occlusionSurfaces(),s);
 const report={experiment:'E14',staticSkinVerdict:'FAIL_HOLE_REMAINS_IN_BOTH_ORDERS',motion:'not evaluated: static skin gate failed',audit,originalCrossings:metrics(s.pose).crossings,externalCurveSamples:176,splitCurveSamples:sampleCurves(s.arm).length+sampleCurves(s.torso).length,surfaces:s};
 if(process.argv.includes('--record'))writeFileSync(resolve(import.meta.dirname,'../../../docs/avatar-rig-research/references/evidence/E14/results.json'),JSON.stringify(report,null,2)+'\n');
 console.log(JSON.stringify(audit,null,2));console.log('Diagnostic invariants pass. STATIC SKIN FAIL: order does not repair the uncovered hole.');
}finally{rmSync(out,{recursive:true,force:true});}
