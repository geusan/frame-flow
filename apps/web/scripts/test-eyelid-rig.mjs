import assert from 'node:assert/strict';
import {freshEyelidRig,eyelidCurves,parseEyelidRig} from '../src/features/avatar-2d/eyelid-rig.ts';
const rig=freshEyelidRig();const open=eyelidCurves(0,0,rig.left),half=eyelidCurves(.5,0,rig.left),closed=eyelidCurves(1,1,rig.left);
assert.equal(open.upper.length,9);assert.equal(open.lower.length,9);assert.deepEqual(closed.upper,closed.lower);
for(let i=0;i<9;i++){assert.ok(half.lower[i][1]-half.upper[i][1]<=(open.lower[i][1]-open.upper[i][1])*.5+1e-7);assert.deepEqual(open.upper[i][0],closed.upper[i][0]);}
rig.left.upper[4]=-20;assert.equal(eyelidCurves(0,0,rig.left).upper[4][1],open.upper[4][1]-20);assert.deepEqual(eyelidCurves(0,0,rig.right),open);
for(let b=0;b<=1;b+=.05){const c=eyelidCurves(b,.7,rig.left);assert.ok(c.upper.every((p,i)=>p[1]<=c.lower[i][1]+1e-8));}
rig.left.upper[0]=30;rig.left.lower[4]=100;const p=parseEyelidRig(rig);assert.equal(p.left.upper[0],0);assert.equal(p.left.lower[4],30);assert.deepEqual(parseEyelidRig(null),freshEyelidRig());
console.log('Eyelid rig: contours, exact closure, fixed corners, independent eyes and validation passed');
