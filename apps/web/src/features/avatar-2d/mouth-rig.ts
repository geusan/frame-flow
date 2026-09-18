export type TonguePose={x:number;y:number;out:number;curl:number};
export const neutralTongue=():TonguePose=>({x:0,y:0,out:0,curl:0});
export function parseTongue(value:unknown):TonguePose{const p=neutralTongue(),v=value as TonguePose;if(!v||typeof v!=='object')return p;for(const k of ['x','y','out','curl'] as const){const n=v[k];if(Number.isFinite(n))p[k]=Math.max(k==='out'?0:-1,Math.min(1,n));}return p;}
import type {FacePoints,RigFaceValues,FacePoint} from './face-rig';
import type {FeatureAlignment} from './feature-alignment';
export type MouthRig={version:1;upper:number[];lower:number[];teeth:boolean;tongue:boolean;upperLipGain?:number;tonguePose?:TonguePose};
export const freshMouthRig=():MouthRig=>({version:1,upper:Array(9).fill(0),lower:Array(9).fill(0),teeth:true,tongue:true,upperLipGain:1,tonguePose:neutralTongue()});
export function parseMouthRig(value:unknown):MouthRig{const r=freshMouthRig(),v=value as MouthRig;if(!v||v.version!==1)return r;r.tonguePose=parseTongue(v.tonguePose);for(const edge of ['upper','lower'] as const)if(Array.isArray(v[edge])&&v[edge].length===9)r[edge]=v[edge].map((n,i)=>i===0||i===8?0:Number.isFinite(n)?Math.max(-2,Math.min(2,n)):0);if(Number.isFinite(v.upperLipGain))r.upperLipGain=Math.max(0,Math.min(3,v.upperLipGain!));for(const k of ['teeth','tongue'] as const)if(typeof v[k]==='boolean')r[k]=v[k];return r;}
export function mouthContours(rest:FacePoints,values:RigFaceValues,alignment:FeatureAlignment,rig:MouthRig){
 const unit=(v:number)=>Number.isFinite(v)?Math.max(0,Math.min(1,v)):0;
 const jaw=unit(values.jawOpen),sr=unit(values.mouthSmileRight),sl=unit(values.mouthSmileLeft),fr=unit(values.mouthFrownRight),fl=unit(values.mouthFrownLeft);
 const pucker=unit(values.mouthPucker??0),funnel=unit(values.mouthFunnel??0),rollUpper=unit(values.mouthRollUpper??0),rollLower=unit(values.mouthRollLower??0),pressLeft=unit(values.mouthPressLeft??0),pressRight=unit(values.mouthPressRight??0),stretchLeft=unit(values.mouthStretchLeft??0),stretchRight=unit(values.mouthStretchRight??0),lowerLeft=unit(values.mouthLowerDownLeft??0),lowerRight=unit(values.mouthLowerDownRight??0);
 const close=unit(values.mouthClose??0),shrugUpper=unit(values.mouthShrugUpper??0),shrugLower=unit(values.mouthShrugLower??0),dimpleLeft=unit(values.mouthDimpleLeft??0),dimpleRight=unit(values.mouthDimpleRight??0),forward=unit(values.jawForward??0);
 const cx=(rest.leftIris[0]+rest.rightIris[0])/2+3*(unit(values.mouthLeft??0)-unit(values.mouthRight??0))+3*(unit(values.jawLeft??0)-unit(values.jawRight??0)),cy=(rest.mouthInnerUpper[1]+rest.mouthInnerLower[1])/2+alignment.mouthHeight+forward,half=(rest.mouthLeft[0]-rest.mouthRight[0])/2*alignment.mouthWidth*(1-.45*pucker-.25*funnel)*(1+.08*forward);
 const right:FacePoint=[cx-half*(1+.35*sr-.08*fr+.35*stretchRight+.15*dimpleRight),cy-3*sr+2.5*fr-.8*dimpleRight],left:FacePoint=[cx+half*(1+.35*sl-.08*fl+.35*stretchLeft+.15*dimpleLeft),cy-3*sl+2.5*fl-.8*dimpleLeft];
 const liftLeft=unit((values.mouthUpperUpLeft??0)*(rig.upperLipGain??1)),liftRight=unit((values.mouthUpperUpRight??0)*(rig.upperLipGain??1));
 const upper:FacePoint[]=[],lower:FacePoint[]=[];
 for(let i=0;i<9;i++){const t=i/8,e=Math.sin(Math.PI*t),x=right[0]*(1-t)+left[0]*t,cornerY=right[1]*(1-t)+left[1]*t,seam=cornerY+(cy-cornerY)*e+e*(.15+(rig.upper[i]+rig.lower[i])*.5-1.5*shrugUpper+1.5*shrugLower);
 const press=pressRight*(1-t)+pressLeft*t,compression=(1-close)*(1-press)*(1-.65*Math.max(rollUpper,rollLower));
 const up=jaw*alignment.mouthOpening*e*(-3+rig.upper[i])-6*e*(liftRight*(1-t)+liftLeft*t)-4*funnel*e;
 const down=jaw*alignment.mouthOpening*e*(11+rig.lower[i])+6*e*(lowerRight*(1-t)+lowerLeft*t)+4*funnel*e;
 upper.push([x,seam+up*compression]);lower.push([x,seam+down*compression]);}

 return {upper,lower,jaw,cx,cy,aperture:Math.max(...lower.map((p,i)=>p[1]-upper[i][1])),upperLift:Math.max(liftLeft,liftRight),lowerLift:Math.max(lowerLeft,lowerRight),funnel,pucker,press:Math.max(pressLeft,pressRight),rollUpper,rollLower,shrugUpper,shrugLower};
}
