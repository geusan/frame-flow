import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';import {createRequire} from 'node:module';import {mkdtempSync,rmSync} from 'node:fs';import {tmpdir} from 'node:os';import {join,resolve,dirname} from 'node:path';
const require=createRequire(import.meta.url),out=mkdtempSync(join(tmpdir(),'feature-align-test-'));
try{execFileSync(process.execPath,[join(dirname(require.resolve('typescript/package.json')),'bin/tsc'),resolve(import.meta.dirname,'../src/features/avatar-2d/feature-alignment.ts'),resolve(import.meta.dirname,'../src/features/avatar-2d/eye-layout.ts'),'--ignoreConfig','--outDir',out,'--target','ES2022','--module','commonjs','--skipLibCheck'],{stdio:'inherit'});
const {freshFaceRig,neutralRigFace,solveFacePoints}=require(join(out,'face-rig.js'));const {characterEyes}=require(join(out,'eye-layout.js'));const {alignFaceFeatures,DEFAULT_FEATURE_ALIGNMENT,parseFeatureAlignment}=require(join(out,'feature-alignment.js'));
const rig=freshFaceRig('test'),rest=rig.poses.neutral.points,layout=characterEyes(rest,.9),base=alignFaceFeatures(rest,rest,layout,DEFAULT_FEATURE_ALIGNMENT);
assert.ok(Math.abs(base.leftBrowMid[0]-rest.leftBrowMid[0]-(layout.left.center.x-rest.leftIris[0]))<1e-8);
const raised=alignFaceFeatures(rest,rest,layout,{...DEFAULT_FEATURE_ALIGNMENT,leftBrowHeight:-3});assert.equal(raised.leftBrowMid[1],base.leftBrowMid[1]-3);assert.deepEqual(raised.rightBrowMid,base.rightBrowMid);assert.deepEqual(raised.leftIris,rest.leftIris);
const open=solveFacePoints(rig,{...neutralRigFace(),jawOpen:.7,mouthSmileLeft:.8,mouthSmileRight:.8}),a=alignFaceFeatures(rest,open,layout,DEFAULT_FEATURE_ALIGNMENT),wide=alignFaceFeatures(rest,open,layout,{...DEFAULT_FEATURE_ALIGNMENT,mouthWidth:1.4,mouthOpening:1.2});assert.ok(Math.abs((wide.mouthLeft[0]-wide.mouthRight[0])/(a.mouthLeft[0]-a.mouthRight[0])-1.4)<1e-8);assert.ok(wide.mouthInnerLower[1]-wide.mouthInnerUpper[1]>a.mouthInnerLower[1]-a.mouthInnerUpper[1]);assert.deepEqual(wide.nose,rest.nose);
assert.equal(parseFeatureAlignment({mouthWidth:99}).mouthWidth,1.5);assert.equal(parseFeatureAlignment({mouthWidth:NaN}).mouthWidth,1);assert.deepEqual(parseFeatureAlignment(null),DEFAULT_FEATURE_ALIGNMENT);
console.log('Feature alignment: eye-following brows, independent heights, mouth width/opening and validation passed');
}finally{rmSync(out,{recursive:true,force:true});}
