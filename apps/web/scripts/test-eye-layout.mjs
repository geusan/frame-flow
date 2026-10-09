import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {createRequire} from 'node:module';
import {mkdtempSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join,resolve,dirname} from 'node:path';
const require=createRequire(import.meta.url),out=mkdtempSync(join(tmpdir(),'eye-layout-test-'));
try{
execFileSync(process.execPath,[join(dirname(require.resolve('typescript/package.json')),'bin/tsc'),resolve(import.meta.dirname,'../../../packages/studio/src/features/avatar-2d/eye-layout.ts'),'--ignoreConfig','--outDir',out,'--target','ES2022','--module','commonjs','--skipLibCheck'],{stdio:'inherit'});
const {freshFaceRig}=require(join(out,'face-rig.js'));
const {characterEyes,characterFixation}=require(join(out,'eye-layout.js'));
const {EYE_FRONT_CENTER}=require(join(out,'eye-projection.js'));
const points=freshFaceRig('test').poses.neutral.points;
for(const spacing of [.8,.94,1,1.15]){const layout=characterEyes(points,spacing);assert.ok(Math.abs(layout.gap-78*spacing)<1e-8);for(const side of ['left','right']){const p=layout[side];assert.ok(Math.abs(p.x+(side==='right'?1000-EYE_FRONT_CENTER.x:EYE_FRONT_CENTER.x)*p.width/1000-p.center.x)<1e-8);}const f=characterFixation(layout,.4,.3);for(const side of ['left','right']){const e=f[side];assert.ok(Math.abs(e.origin.x+Math.tan(e.yaw)*f.target.z-f.target.x)<1e-8);assert.ok(Math.abs(e.origin.y+Math.tan(e.pitch)*Math.hypot(f.target.x-e.origin.x,f.target.z)-f.target.y)<1e-8);}}
const narrow=characterFixation(characterEyes(points,.8),0,0),wide=characterFixation(characterEyes(points,1.15),0,0);assert.ok(Math.abs(wide.left.yaw)>Math.abs(narrow.left.yaw));
const scaled=Object.fromEntries(Object.entries(points).map(([k,p])=>[k,[p[0]*2,p[1]*2]]));assert.ok(Math.abs(characterFixation(characterEyes(scaled),0,0).left.yaw-characterFixation(characterEyes(points),0,0).left.yaw)<1e-8);
console.log('Character eye layout: artwork anchors, spacing, scale invariance and target intersection passed');

}finally{rmSync(out,{recursive:true,force:true});}
