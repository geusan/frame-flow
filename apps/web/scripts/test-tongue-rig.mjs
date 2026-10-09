import assert from 'node:assert/strict';
import {tongueShape} from '../../../packages/studio/src/features/avatar-2d/tongue-rig.ts';
import {freshMouthRig,parseMouthRig,neutralTongue,parseTongue,mouthContours} from '../../../packages/studio/src/features/avatar-2d/mouth-rig.ts';
import {freshFaceRig,neutralRigFace} from '../../../packages/studio/src/features/avatar-2d/face-rig.ts';
import {DEFAULT_FEATURE_ALIGNMENT} from '../../../packages/studio/src/features/avatar-2d/feature-alignment.ts';
const rest=freshFaceRig('test').poses.neutral.points,rig=freshMouthRig(),closed=mouthContours(rest,neutralRigFace(),DEFAULT_FEATURE_ALIGNMENT,rig),open=mouthContours(rest,{...neutralRigFace(),jawOpen:.7},DEFAULT_FEATURE_ALIGNMENT,rig),pose={x:0,y:0,out:1,curl:0};
assert.equal(tongueShape(closed,pose).extension,0);assert.equal(tongueShape(closed,pose).width,0);const a=tongueShape(open,pose);assert.ok(a.tipY>a.rootY);assert.ok(tongueShape(open,{...pose,x:1}).tipX>a.tipX);assert.ok(tongueShape(open,{...pose,x:-1}).tipX<a.tipX);assert.ok(tongueShape(open,{...pose,y:-1}).tipY<a.tipY);assert.ok(tongueShape(open,{...pose,curl:1}).tipY<a.tipY);
assert.deepEqual(parseTongue(null),neutralTongue());assert.deepEqual(parseMouthRig({version:1}).tonguePose,neutralTongue());assert.equal(parseTongue({out:99}).out,1);assert.equal(parseTongue({x:NaN}).x,0);
console.log('Tongue rig: independent axes, extension, tip curl, closed-mouth hiding and legacy defaults passed');
