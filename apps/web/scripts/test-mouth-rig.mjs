import assert from 'node:assert/strict';
import {mouthContours,freshMouthRig,parseMouthRig} from '../../../packages/studio/src/features/avatar-2d/mouth-rig.ts';
import {freshFaceRig,neutralRigFace} from '../../../packages/studio/src/features/avatar-2d/face-rig.ts';
import {DEFAULT_FEATURE_ALIGNMENT} from '../../../packages/studio/src/features/avatar-2d/feature-alignment.ts';
const rest=freshFaceRig('test').poses.neutral.points,rig=freshMouthRig(),zero=neutralRigFace(),a=DEFAULT_FEATURE_ALIGNMENT;
const closed=mouthContours(rest,zero,a,rig);assert.deepEqual(closed.upper,closed.lower);assert.equal(closed.upper.length,9);
const open=mouthContours(rest,{...zero,jawOpen:1},a,rig),half=mouthContours(rest,{...zero,jawOpen:.5},a,rig);assert.ok(Math.abs((open.lower[4][1]-open.upper[4][1])/2-(half.lower[4][1]-half.upper[4][1]))<1e-8);
const smile=mouthContours(rest,{...zero,mouthSmileLeft:1},a,rig);assert.deepEqual(smile.upper[0],closed.upper[0]);assert.ok(smile.upper[8][1]<closed.upper[8][1]);assert.deepEqual(smile.upper,smile.lower);assert.ok(smile.upper[4][1]>smile.upper[8][1],"smile raises corner relative to center");
const mixed=mouthContours(rest,{...zero,jawOpen:1,mouthSmileLeft:1,mouthSmileRight:1},a,rig);assert.ok(Math.abs((mixed.lower[4][1]-mixed.upper[4][1])-(open.lower[4][1]-open.upper[4][1]))<1e-8);
rig.upper[4]=2;const edited=mouthContours(rest,{...zero,jawOpen:1},a,rig);assert.notDeepEqual(edited.upper[4],open.upper[4]);assert.deepEqual(edited.upper[3],open.upper[3]);assert.deepEqual(parseMouthRig(null),freshMouthRig());
for(let b=0;b<=1;b+=.1){const c=mouthContours(rest,{...zero,jawOpen:b,mouthSmileLeft:.8,mouthFrownRight:.7},a,rig);assert.ok(c.upper.every((p,i)=>p[1]<=c.lower[i][1]+1e-8));}
console.log('Mouth rig: closure, continuous opening, independent corners, combined smile/open and parsing passed');
