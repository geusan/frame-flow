import {EYE_FRONT_CENTER} from './eye-projection';
import type {FacePoints} from './face-rig';
export function characterEyes(points:FacePoints,spacing=0.94){
 const clamp=(v:number,min:number,max:number)=>Math.max(min,Math.min(max,v));
 const midX=(points.leftIris[0]+points.rightIris[0])/2,midY=(points.leftIris[1]+points.rightIris[1])/2;
 const gap=(points.leftIris[0]-points.rightIris[0])*clamp(Number.isFinite(spacing)?spacing:.94,.8,1.15);
 const eye=(side:'left'|'right')=>{const mirror=side==='right';
  const width=clamp(Math.abs(points[`${side}EyeOuter`][0]-points[`${side}EyeInner`][0]),25,55)/800*1000;
  const height=clamp(points[`${side}EyeLower`][1]-points[`${side}EyeUpper`][1],12,32)/330*600;
  const center={x:midX+(mirror?-gap/2:gap/2),y:points[`${side}Iris`][1]};
  return {center,width,height,x:center.x-(mirror?1000-EYE_FRONT_CENTER.x:EYE_FRONT_CENTER.x)*width/1000,y:center.y-EYE_FRONT_CENTER.y*height/600};
 };
 return {left:eye('left'),right:eye('right'),midX,midY,gap,faceWidth:Math.max(70,Math.abs(points.cheekLeft[0]-points.cheekRight[0]))};
}
export function characterFixation(layout:ReturnType<typeof characterEyes>,gx:number,gy:number,distance=60){
 const clamp=(v:number)=>Number.isFinite(v)?Math.max(-1,Math.min(1,v)):0;
 const z=layout.faceWidth*Math.max(2,Math.min(20,(Number.isFinite(distance)?distance:60)/10));
 const target={x:layout.midX+z*Math.tan(clamp(gx)*32*Math.PI/180),y:layout.midY+z*Math.tan(clamp(gy)*18*Math.PI/180),z};
 const solve=(side:'left'|'right')=>{const origin=layout[side].center,dx=target.x-origin.x,dy=target.y-origin.y;return {yaw:Math.atan2(dx,z),pitch:Math.atan2(dy,Math.hypot(dx,z)),origin};};
 return {target,left:solve('left'),right:solve('right')};
}
