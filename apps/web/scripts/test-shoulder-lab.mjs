import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {createRequire} from 'node:module';
import {mkdirSync,mkdtempSync,rmSync} from 'node:fs';
import {join,resolve,dirname} from 'node:path';
const require=createRequire(import.meta.url);
const cache=resolve(import.meta.dirname,'../../../node_modules/.cache');
mkdirSync(cache,{recursive:true});
const output=mkdtempSync(join(cache,'shoulder-test-'));
try {
  execFileSync(process.execPath,[join(dirname(require.resolve('typescript/package.json')),'bin/tsc'),resolve(import.meta.dirname,'../src/features/avatar-2d/shoulder-lab-model.ts'),resolve(import.meta.dirname,'../src/features/avatar-2d/shoulder-surface.ts'),'--ignoreConfig','--outDir',output,'--target','ES2022','--module','commonjs','--skipLibCheck'],{stdio:'inherit'});
  const {manualLeftShoulderPose,restShoulderElevation,sweepElevation,parseShoulderReview,emptyReview}=require(join(output,'shoulder-lab-model.js'));
  const {REST,JOINTS,sub,length,angle,angleDelta}=require(join(output,'rig.js'));
  const original=JSON.stringify(REST);
  const baseline=restShoulderElevation();
  const neutral=manualLeftShoulderPose(baseline);
  for(const joint of JOINTS) assert.ok(length(sub(neutral.joints[joint],REST[joint]))<1e-9,'baseline reproduces the original rig');
  const elbowRestAngle=angleDelta(angle(sub(REST.leftWrist,REST.leftElbow)),angle(sub(REST.leftElbow,REST.leftShoulder)));
  for(let degree=0;degree<=160;degree+=.25){
    const p=manualLeftShoulderPose(degree);
    for(const joint of JOINTS.filter(j=>!['leftShoulder','leftElbow','leftWrist'].includes(j))) assert.deepEqual(p.joints[joint],REST[joint],`${joint} must stay frozen`);
    for(const [a,b] of [['leftShoulder','leftElbow'],['leftElbow','leftWrist']]) assert.ok(Math.abs(length(sub(p.joints[b],p.joints[a]))-length(sub(REST[b],REST[a])))<1e-8);
    const localElbow=angleDelta(angle(sub(p.joints.leftWrist,p.joints.leftElbow)),angle(sub(p.joints.leftElbow,p.joints.leftShoulder)));
    assert.ok(Math.abs(angleDelta(localElbow,elbowRestAngle))<1e-8,'elbow relative angle is locked');
    assert.equal(p.headTurn,0);assert.equal(p.headTilt,0);assert.equal(p.blink,0);assert.equal(p.mouth,0);assert.deepEqual(p.depth,{});
  }
  assert.equal(JSON.stringify(REST),original,'manual control cannot mutate the source rig');
  assert.ok(Math.abs(manualLeftShoulderPose(0).joints.leftElbow[0]-REST.leftShoulder[0])<1e-8,'0 degrees points down');
  assert.ok(Math.abs(manualLeftShoulderPose(90).joints.leftElbow[1]-manualLeftShoulderPose(90).joints.leftShoulder[1])<1e-8,'90 degrees points horizontally outward');
  assert.ok(manualLeftShoulderPose(160).joints.leftElbow[1]<REST.leftShoulder[1],'160 degrees points overhead');
  assert.deepEqual(manualLeftShoulderPose(-10),manualLeftShoulderPose(0));assert.deepEqual(manualLeftShoulderPose(900),manualLeftShoulderPose(160));
  assert.deepEqual(manualLeftShoulderPose(NaN),neutral);
  for(const start of [0,baseline,90,160]){
    assert.ok(Math.abs(sweepElevation(0,start)-start)<1e-9,'sweep must start without jumping');
    assert.ok(Math.abs(sweepElevation(12,start)-start)<1e-8);
    for(let t=0;t<24;t+=.03){const a=sweepElevation(t,start);assert.ok(a>=0&&a<=160);}
  }
  const review={...emptyReview(),observations:[{id:'test',angle:90,note:'Check shoulder silhouette',createdAt:'2026-09-09T00:00:00Z'}]};
  assert.deepEqual(parseShoulderReview(JSON.parse(JSON.stringify(review))),review);
  assert.throws(()=>parseShoulderReview({...review,side:'right'}));assert.throws(()=>parseShoulderReview({...review,asset:'other'}));
  assert.throws(()=>parseShoulderReview({...review,observations:[{...review.observations[0],angle:Infinity}]}));
  const {artworkGrid,CONNECTED_LEFT_BODY,ShoulderSurface,garmentPoint}=require(join(output,'shoulder-surface.js'));
  for(let degree=0;degree<=160;degree+=.25){
    const pose=manualLeftShoulderPose(degree);
    for(const point of [[512,387],[555,370],[512,450],[590,450],[570,530]])assert.deepEqual(garmentPoint(point,REST,pose),point,'neckline, chest shading and hem remain anchored to torso');
    for(const point of [[580,315],[595,345],[605,400]]){const shift=sub(garmentPoint(point,REST,pose),point);assert.ok(Math.abs(shift[0])<=1.8 && Math.abs(shift[1])<=8,'outer strap displacement is bounded');}
  }
  const grid=artworkGrid(CONNECTED_LEFT_BODY.polygon,12,true);
  const surface=new ShoulderSurface(grid.points,grid.indices,REST);
  let minArea=Infinity,maxStretch=0,maxStep=0,previous;
  const area=(p,a,b,c)=>(p[b][0]-p[a][0])*(p[c][1]-p[a][1])-(p[b][1]-p[a][1])*(p[c][0]-p[a][0]);
  for(let degree=0;degree<=160;degree+=.25){
    const q=surface.deform(manualLeftShoulderPose(degree));
    if(previous) q.forEach((p,i)=>{maxStep=Math.max(maxStep,length(sub(p,previous[i])));});
    previous=q;
    for(let k=0;k<grid.indices.length;k+=3){
      const [a,b,c]=grid.indices.slice(k,k+3);
      const ratio=area(q,a,b,c)/area(grid.points,a,b,c);minArea=Math.min(minArea,ratio);
      for(const [i,j] of [[a,b],[b,c],[c,a]]){const stretch=length(sub(q[i],q[j]))/length(sub(grid.points[i],grid.points[j]));maxStretch=Math.max(maxStretch,stretch);}
    }
  }
  assert.ok(minArea>.1,'no inverted or collapsed triangles across the full angle sweep');
  assert.ok(maxStretch<6,'bound local edge stretch; this is not a visual naturalness assertion');
  assert.ok(maxStep<8,'no large discontinuous vertex jumps between adjacent quarter-degree inputs');
  const neutralSurface=surface.deform(neutral);
  neutralSurface.forEach((p,i)=>assert.ok(length(sub(p,grid.points[i]))<1e-8,'neutral artwork is unchanged'));
  const adjacency=grid.points.map(()=>new Set());
  for(let k=0;k<grid.indices.length;k+=3){const [a,b,c]=grid.indices.slice(k,k+3);for(const [i,j] of [[a,b],[b,c],[c,a]]){adjacency[i].add(j);adjacency[j].add(i);}}
  const reached=new Set(),queue=[grid.indices[0]];while(queue.length){const i=queue.pop();if(reached.has(i))continue;reached.add(i);queue.push(...[...adjacency[i]].filter(j=>!reached.has(j)));}
  assert.equal(reached.size,new Set(grid.indices).size,'arm and torso form one connected surface');
  console.log(JSON.stringify({minArea,maxStretch,maxStep}));
  console.log('Shoulder lab: 641 angles; connected topology, positive triangle areas, neutral artwork, fixed limb lengths/elbow angle, non-target joint isolation, sweep and review validation passed.');
} finally {rmSync(output,{recursive:true,force:true});}
