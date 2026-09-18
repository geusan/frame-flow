import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { CONNECTIONS, JOINTS, REST, freshProfile, parseProfile, neutralPose, solvePose, smoothPose, sub, length, hipOrigin } from '../src/features/avatar-2d/rig.ts';
import { PARTS } from '../src/features/avatar-2d/parts.ts';

const profile = freshProfile();
assert.deepEqual(parseProfile(profile), profile);
profile.anchors.head[0] += 10;
assert.notEqual(profile.anchors.head[0], REST.head[0], 'edits cannot mutate the bundled neutral rig');
assert.throws(() => parseProfile({ ...profile, asset: 'different-avatar' }), /아바타/);
assert.throws(() => parseProfile({ ...profile, anchors: { ...profile.anchors, leftElbow: [NaN, 20] } }), /범위/);
assert.throws(() => parseProfile({ ...profile, anchors: { ...profile.anchors, leftElbow: profile.anchors.leftWrist } }), /간격/);
for (const part of PARTS.filter((p) => /arm|leg/.test(p.id))) {
  const side = part.id.startsWith('left') ? 'left' : 'right';
  assert.ok(part.chain.every((j) => j.startsWith(side)), 'limb weights must never cross body sides');
  assert.ok(part.chain.every((j) => part.id.includes('arm') ? /Shoulder|Elbow|Wrist/.test(j) : /Hip|Knee|Ankle/.test(j)), 'hands cannot be weighted to thighs');
}
const motion = JSON.parse(readFileSync(new URL('../public/avatars/cat-2d-v1/reference-motion.json', import.meta.url)));
assert.equal(motion.schema_version, 'avatar.performance.v1');
assert.equal(motion.frames.length, 854);
const aspect = motion.width / motion.height, origin = hipOrigin(motion.frames[0], aspect);
let current = neutralPose(), prior = current;
const limbEdges = CONNECTIONS.filter(([a,b]) => /Shoulder|Elbow|Hip|Knee/.test(a) && /Elbow|Wrist|Knee|Ankle/.test(b));
for (const frame of motion.frames) {
  const next = solvePose(frame, REST, aspect, prior, origin);
  for (const j of JOINTS) assert.ok(next.joints[j].every(Number.isFinite));
  for (const [a,b] of limbEdges) assert.ok(Math.abs(length(sub(next.joints[b],next.joints[a])) - length(sub(REST[b],REST[a]))) < 1e-6, 'target bone lengths survive source proportion changes');
  current = smoothPose(current, next, 1/24, .08);
  for (const [a,b] of limbEdges) assert.ok(Math.abs(length(sub(current.joints[b],current.joints[a])) - length(sub(REST[b],REST[a]))) < 1e-6, 'smoothing cannot shrink or stretch limbs');
  prior = next;
}
assert.equal(solvePose({pose:[],time:0}, REST, aspect, current),current);
const occluded = structuredClone(motion.frames[0]); occluded.pose[12][3]=0;
assert.equal(solvePose(occluded, REST, aspect, current),current);
const upright = structuredClone(motion.frames[0]); upright.pose[2]=[.55,.2,0,1];upright.pose[5]=[.45,.2,0,1];upright.pose[0]=[.5,.23,-.1,1];
const head=solvePose(upright,REST,aspect);
assert.equal(head.headTilt,0,'neutral face cannot inherit the old 90-degree head error');
assert.equal(head.headTurn,0);
console.log('2D avatar: 854 reference frames, limb lengths, smoothing, missing tracking, neutral head and rig validation passed.');


// A source pixel belongs to exactly one layer. This prevents both doubled hair
// silhouettes and the earlier loss of neck/shoulder skin during head extraction.
const {partitionArtwork}=await import('../src/features/avatar-2d/artwork-partition.ts');
const pixels=new Uint8ClampedArray(4*2*360), region=new Uint8ClampedArray(pixels.length);
for(let y=0;y<360;y++)for(let x=0;x<2;x++){const k=(y*2+x)*4;pixels.set(x===0?[35,32,30,255]:[247,205,173,255],k);region[k+3]=255;}
const partition=partitionArtwork(pixels,region,2,360);
for(let i=0;i<pixels.length;i+=4){
  assert.equal(partition.head[i+3]+partition.body[i+3],pixels[i+3]);
  assert.deepEqual([...partition.head.slice(i,i+3)],[...pixels.slice(i,i+3)]);
  assert.deepEqual([...partition.body.slice(i,i+3)],[...pixels.slice(i,i+3)]);
}
assert.equal(partition.head[(300*2)*4+3],255,'original lower hair stays on the head');
assert.equal(partition.head[(300*2+1)*4+3],0,'shoulder skin must not move with the head');
assert.equal(partition.body[(300*2+1)*4+3],255,'that shoulder skin is retained on the body');
assert.ok(PARTS.every(p=>p.paint!=='joint'),'no independent skin discs can protrude from an attachment');
assert.equal(PARTS.length,6);
console.log('Original-pixel ownership, skin retention and no duplicate skin geometry passed.');
const {torsoTransform,neckTransform,rotate,add}=await import('../src/features/avatar-2d/rig.ts');
for(const f of motion.frames){
  const p=solvePose(f,REST,aspect,undefined,origin);
  for(const side of ['left','right']){
    const joint=`${side}Shoulder`;
    const bodyAttachment=torsoTransform(REST[joint],REST,p).point;
    assert.ok(length(sub(bodyAttachment,p.joints[joint]))<1e-6,'torso and upper arm share one shoulder pivot');
  }
  const bottom=[REST.neck[0],REST.neck[1]+25];
  assert.ok(length(sub(neckTransform(bottom,REST,p).point,torsoTransform(bottom,REST,p).point))<1e-6,'lower neck stays attached to the torso');
  const top=[REST.head[0],REST.neck[1]-50];
  const expected=add(p.joints.head,rotate([p.headTurn*32,top[1]-REST.head[1]],p.headTilt));
  assert.ok(length(sub(neckTransform(top,REST,p).point,expected))<1e-6,'upper neck follows the jaw without an independent skin disc');
}
console.log('Shared shoulder pivots and neck-to-jaw/torso attachment passed for every reference frame.');
