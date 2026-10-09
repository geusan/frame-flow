import type {FacePoints,FacePointId} from './face-rig';
export const DEFAULT_FEATURE_ALIGNMENT={browVisible:1,browThickness:1,browWidth:1,leftBrowHeight:0,rightBrowHeight:0,browTilt:0,mouthWidth:1,mouthHeight:0,mouthOpening:1};
export type FeatureAlignment=typeof DEFAULT_FEATURE_ALIGNMENT;
export const FEATURE_LIMITS:Record<keyof FeatureAlignment,[number,number]>={browVisible:[0,1],browThickness:[.5,1.8],browWidth:[.8,1.2],leftBrowHeight:[-5,5],rightBrowHeight:[-5,5],browTilt:[-4,4],mouthWidth:[.8,1.5],mouthHeight:[-5,5],mouthOpening:[.6,1.5]};
export function parseFeatureAlignment(value:unknown):FeatureAlignment{
 const result={...DEFAULT_FEATURE_ALIGNMENT},input=value as Partial<FeatureAlignment>|null;
 if(!input||typeof input!=='object')return result;
 for(const key of Object.keys(result) as (keyof FeatureAlignment)[]){const v=input[key];if(typeof v==='number'&&Number.isFinite(v))result[key]=Math.max(FEATURE_LIMITS[key][0],Math.min(FEATURE_LIMITS[key][1],v));}return result;
}
/** Align feature targets to the current eye layout, without changing saved source landmarks. */
export function alignFaceFeatures(rest:FacePoints,solved:FacePoints,eyeCenters:{left:{center:{x:number}};right:{center:{x:number}};midX:number},settings:FeatureAlignment):FacePoints{
 const result=structuredClone(solved);
 for(const side of ['left','right'] as const){const center=rest[`${side}BrowMid`][0],shift=eyeCenters[side].center.x-rest[`${side}Iris`][0],height=settings[side==='left'?'leftBrowHeight':'rightBrowHeight'];
  for(const end of ['Inner','Mid','Outer'] as const){const key=`${side}Brow${end}` as FacePointId;result[key]=[center+shift+(solved[key][0]-center)*settings.browWidth,solved[key][1]+height+(end==='Inner'?1:end==='Outer'?-1:0)*settings.browTilt];}
 }
 const mx=(rest.mouthLeft[0]+rest.mouthRight[0])/2,my=(rest.mouthInnerUpper[1]+rest.mouthInnerLower[1])/2;
 for(const key of Object.keys(rest) as FacePointId[])if(key.startsWith('mouth'))result[key]=[eyeCenters.midX+(solved[key][0]-mx)*settings.mouthWidth,my+settings.mouthHeight+(solved[key][1]-my)*settings.mouthOpening];
 return result;
}
