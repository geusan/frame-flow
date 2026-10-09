import assert from 'node:assert/strict';
import {mouthContours,freshMouthRig} from '../../../packages/studio/src/features/avatar-2d/mouth-rig.ts';
import {freshFaceRig,neutralRigFace,solveFaceValues,EXTRA_MOUTH_CHANNELS,FaceRigCapture} from '../../../packages/studio/src/features/avatar-2d/face-rig.ts';
import {DEFAULT_FEATURE_ALIGNMENT as a} from '../../../packages/studio/src/features/avatar-2d/feature-alignment.ts';
const p=freshFaceRig('test'),rest=p.poses.neutral.points,rig=freshMouthRig(),zero=neutralRigFace(),shape=v=>mouthContours(rest,{...zero,...v},a,rig),closed=shape({}),width=c=>c.upper[8][0]-c.upper[0][0];
assert.ok(width(shape({mouthPucker:1}))<width(closed)*.6);assert.ok(shape({mouthFunnel:1}).aperture>7);
const lower=shape({mouthLowerDownLeft:1,mouthLowerDownRight:1});assert.equal(lower.jaw,0);assert.deepEqual(lower.upper,closed.upper);assert.ok(lower.lower[4][1]>closed.lower[4][1]+5);
assert.equal(shape({jawOpen:1,mouthPressLeft:1,mouthPressRight:1}).aperture,0);
assert.ok(shape({jawOpen:1,mouthRollUpper:1,mouthRollLower:1}).aperture<shape({jawOpen:1}).aperture*.4);
const stretch=shape({mouthStretchLeft:1});assert.deepEqual(stretch.upper[0],closed.upper[0]);assert.ok(stretch.upper[8][0]>closed.upper[8][0]);
for(const k of EXTRA_MOUTH_CHANNELS){const values=solveFaceValues({[k]:.8},{},p);assert.ok(values[k]>.9);const c=shape(values);assert.ok(c.upper.every((v,i)=>v[1]<=c.lower[i][1]+1e-8));}
const capture=new FaceRigCapture();capture.begin('neutral',0);for(let i=0;i<24;i++)capture.receive({mouthPucker:.2},true,i*20,p);assert.equal(solveFaceValues({mouthPucker:.2},capture.baseline,p).mouthPucker,0);
console.log('Additional mouth actions: lower lip, pucker, funnel, press, roll, stretch, calibration and contours passed');
