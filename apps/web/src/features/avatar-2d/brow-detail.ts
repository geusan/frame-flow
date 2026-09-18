import type {FacePoint,FacePoints} from './face-rig';
export type BrowSide='left'|'right';
export type BrowControl={x:number;y:number;gain:number};
export type BrowDetail={version:1;left:BrowControl[];right:BrowControl[]};
export const freshBrowDetail=():BrowDetail=>({version:1,left:Array.from({length:9},()=>({x:0,y:0,gain:1})),right:Array.from({length:9},()=>({x:0,y:0,gain:1}))});
export function parseBrowDetail(value:unknown):BrowDetail{const result=freshBrowDetail(),v=value as BrowDetail;if(!v||v.version!==1)return result;for(const side of ['left','right'] as const){if(!Array.isArray(v[side])||v[side].length!==9)continue;v[side].forEach((p,i)=>{for(const key of ['x','y','gain'] as const){const n=p?.[key];if(Number.isFinite(n))result[side][i][key]=Math.max(key==='gain'?0:key==='x'?-1.5:-5,Math.min(key==='gain'?2:key==='x'?1.5:5,n));}});}return result;}
const coarse=(p:FacePoints,side:BrowSide,t:number):FacePoint=>{const a=p[`${side}BrowInner`],m=p[`${side}BrowMid`],b=p[`${side}BrowOuter`];return [0,1].map(k=>(1-t)**2*a[k]+2*t*(1-t)*(2*m[k]-(a[k]+b[k])/2)+t*t*b[k]) as FacePoint;};
/** Nine independently editable offsets and response gains, layered over the legacy animation anchors. */
export function browControls(points:FacePoints,neutral:FacePoints,side:BrowSide,detail:BrowDetail):FacePoint[]{return detail[side].map((control,i)=>{const r=coarse(neutral,side,i/8),p=coarse(points,side,i/8);return [r[0]+(p[0]-r[0])*control.gain+control.x,r[1]+(p[1]-r[1])*control.gain+control.y];});}
export function browCurve(points:FacePoints,neutral:FacePoints,side:BrowSide,detail:BrowDetail,t:number):FacePoint{
 const base=coarse(points,side,t),controls=browControls(points,neutral,side,detail),deltas=controls.map((p,i)=>{const q=coarse(points,side,i/8);return [p[0]-q[0],p[1]-q[1]];});
 const u=Math.max(0,Math.min(1,t))*8,i=Math.min(7,Math.floor(u)),f=u-i,s=f*f*(3-2*f);
 return [base[0]+deltas[i][0]*(1-s)+deltas[i+1][0]*s,base[1]+deltas[i][1]*(1-s)+deltas[i+1][1]*s];
}
