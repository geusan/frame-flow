import assert from 'node:assert/strict';
import {fixationTarget,EYE_FRONT_CENTER,projectEye,projectEyeSurface,binocularGaze} from '../src/features/avatar-2d/eye-projection.ts';
const front=projectEye(0,0,180),side=projectEye(1,0,180),left=projectEye(-1,0,180),diagonal=projectEye(1,1,180);
assert.equal(front.x,EYE_FRONT_CENTER.x);assert.equal(front.y,EYE_FRONT_CENTER.y);assert.equal(front.foreshortening,1);
assert.ok(side.foreshortening<.8);assert.ok(diagonal.foreshortening<1);
assert.ok(Math.abs((side.x-EYE_FRONT_CENTER.x)+(left.x-EYE_FRONT_CENTER.x))<1e-8);
for(const p of [front,side,left,diagonal]){assert.ok(Math.abs((p.x-EYE_FRONT_CENTER.x)**2+(p.y-EYE_FRONT_CENTER.y)**2+p.z**2-p.depth**2)<1e-7);assert.ok(Math.abs(p.normal.reduce((s,x)=>s+x*x,0)-1)<1e-10);const [a,b,c,d]=p.matrix;assert.ok(Math.abs(a*d-b*c-p.foreshortening)<1e-10);}
assert.deepEqual(projectEye(NaN,Infinity,180),front);
console.log('Eye projection: spherical orbit, mirror symmetry, diagonal foreshortening and finite input passed');

for(const [u,v] of [[0,0],[150,0],[-150,100],[0,180]]){const p=projectEyeSurface(u,v,.7,.4);assert.ok(Math.abs((p.x-EYE_FRONT_CENTER.x)**2+(p.y-EYE_FRONT_CENTER.y)**2+p.z*p.z-350*350)<1e-6,"every iris vertex must stay on sphere");}
assert.deepEqual(binocularGaze({eyeLookOutLeft:1,eyeLookInRight:1}),{x:1,y:0});
assert.deepEqual(binocularGaze({eyeLookInLeft:1,eyeLookOutRight:1}),{x:-1,y:0});
assert.deepEqual(binocularGaze({eyeBlinkLeft:1}),{x:0,y:0});
const c=projectEyeSurface(0,0,1,0),l=projectEyeSurface(-150,0,1,0),r=projectEyeSurface(150,0,1,0);assert.ok(Math.abs((r.x-c.x)-(c.x-l.x))>10,"spherical surface is not a translated/affine iris plane");

for(const [gx,gy,d] of [[0,0,60],[.8,.3,20],[-.6,-.5,200]]){const f=fixationTarget(gx,gy,d);for(const eye of [f.left,f.right]){assert.ok(Math.abs(eye.origin+Math.tan(eye.yaw)*f.target.z-f.target.x)<1e-9);assert.ok(Math.abs(Math.tan(eye.pitch)*Math.hypot(f.target.x-eye.origin,f.target.z)-f.target.y)<1e-9);}}
assert.ok(fixationTarget(0,0).left.yaw<0&&fixationTarget(0,0).right.yaw>0);
assert.ok(Math.abs(fixationTarget(0,0,20).left.yaw)>Math.abs(fixationTarget(0,0,200).left.yaw));
