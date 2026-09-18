import assert from 'node:assert/strict';
import {FACE_MOTION_CHANNELS,REMAINING_FACE_CHANNELS,freshFaceRig,neutralRigFace,solveFaceValues,solveFacePoints,FaceRigCapture} from '../src/features/avatar-2d/face-rig.ts';
import {mouthContours,freshMouthRig} from '../src/features/avatar-2d/mouth-rig.ts';
import {DEFAULT_FEATURE_ALIGNMENT} from '../src/features/avatar-2d/feature-alignment.ts';
import {eyelidCurves,freshEyelidRig} from '../src/features/avatar-2d/eyelid-rig.ts';
assert.equal(FACE_MOTION_CHANNELS.length,51);assert.equal(new Set(FACE_MOTION_CHANNELS).size,51);assert.equal(REMAINING_FACE_CHANNELS.length,19);
const p=freshFaceRig('test'),zero=neutralRigFace(),rest=solveFacePoints(p,zero),m=v=>mouthContours(p.poses.neutral.points,{...zero,...v},DEFAULT_FEATURE_ALIGNMENT,freshMouthRig());
for(const k of REMAINING_FACE_CHANNELS){assert.ok(solveFaceValues({[k]:.8},{},p)[k]>.9);if(k.startsWith('brow')||k.startsWith('cheek')||k.startsWith('nose')||k.startsWith('jaw'))assert.notDeepEqual(solveFacePoints(p,{...zero,[k]:1}),rest,k);if(k.startsWith('mouth')&&k!=='mouthClose')assert.notDeepEqual(m({[k]:1}),m({}),k);}
assert.equal(m({jawOpen:1,mouthClose:1}).aperture,0);const lid=freshEyelidRig().left;assert.notDeepEqual(eyelidCurves(0,0,lid,1),eyelidCurves(0,0,lid));
const capture=new FaceRigCapture();capture.begin('neutral',0);for(let i=0;i<24;i++)capture.receive(Object.fromEntries(FACE_MOTION_CHANNELS.map(k=>[k,.2])),true,i,p);for(const k of FACE_MOTION_CHANNELS)assert.equal(solveFaceValues({[k]:.2},capture.baseline,p)[k],0);
console.log('All 51 motion channels: unique catalog, 19 new mappings, calibration, mouth close and squint passed');
