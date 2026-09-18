import assert from 'node:assert/strict';
import {freshBrowDetail,browControls,browCurve,parseBrowDetail} from '../src/features/avatar-2d/brow-detail.ts';
import {freshFaceRig,solveFacePoints,neutralRigFace} from '../src/features/avatar-2d/face-rig.ts';
const rest=freshFaceRig('test'),p=rest.poses.neutral.points,d=freshBrowDetail();assert.equal(d.left.length,9);assert.notEqual(d.left[0],d.right[0]);
const old=browControls(p,p,'left',d);d.left[4].y=-3;const next=browControls(p,p,'left',d);assert.equal(next[4][1],old[4][1]-3);for(let i=0;i<9;i++)if(i!==4)assert.deepEqual(next[i],old[i]);assert.deepEqual(browControls(p,p,'right',d),browControls(p,p,'right',freshBrowDetail()));
for(let i=0;i<9;i++)assert.deepEqual(browCurve(p,p,'left',d,i/8),next[i]);
const animated=solveFacePoints(rest,{...neutralRigFace(),browInnerUp:1});d.left[0].gain=0;assert.deepEqual(browControls(animated,p,'left',d)[0],old[0]);assert.notDeepEqual(browControls(animated,p,'left',d)[1],old[1]);
assert.deepEqual(parseBrowDetail(null),freshBrowDetail());assert.deepEqual(parseBrowDetail({version:1,left:[],right:[]}),freshBrowDetail());d.left[3].y=100;assert.equal(parseBrowDetail(d).left[3].y,5);
console.log('Brow detail: 18 controls, local edits, interpolation, independent response and legacy defaults passed');
