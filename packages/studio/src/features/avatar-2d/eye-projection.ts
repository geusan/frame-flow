// Neutral pupil center aligned to the visible sclera, excluding the outer lash wing.
export const EYE_FRONT_CENTER={x:448,y:317} as const;
/** Orthographic projection of an iris disk fixed in a rotating spherical eyeball.
 * SVG coordinates: +x right, +y down, +z towards viewer. No gaze-dependent iris resizing.
 * The iris disk is a plane section of the sphere: depth² + irisRadius² = globeRadius².
 */
export function projectEye(gazeX:number,gazeY:number,irisRadius:number,globeRadius=350){
  const clamp=(v:number)=>Number.isFinite(v)?Math.max(-1,Math.min(1,v)):0;
  const gx=clamp(gazeX),gy=clamp(gazeY),magnitude=Math.max(1,Math.hypot(gx,gy));
  const yaw=gx/magnitude*42*Math.PI/180,pitch=gy/magnitude*22*Math.PI/180;
  const cy=Math.cos(yaw),sy=Math.sin(yaw),cp=Math.cos(pitch),sp=Math.sin(pitch);
  const radius=Math.max(1,Math.min(globeRadius*.85,irisRadius));
  const depth=Math.sqrt(globeRadius*globeRadius-radius*radius);
  // Ry(yaw) Rx(-pitch), first two columns project the iris's local axes.
  const a=cy,b=0,c=-sy*sp,d=cp;
  const x=EYE_FRONT_CENTER.x+depth*sy*cp,y=EYE_FRONT_CENTER.y+depth*sp,z=depth*cy*cp;
  return {x,y,z,depth,yaw,pitch,normal:[sy*cp,sp,cy*cp],matrix:[a,b,c,d,x,y],foreshortening:cy*cp};
}

/** Map texture coordinates onto the front spherical surface, then rotate around the fixed globe center. */
export function projectEyeSurface(u:number,v:number,gazeX:number,gazeY:number,globeRadius=350,rotation?:{yaw:number;pitch:number}){
 const orientation=rotation??projectEye(gazeX,gazeY,1,globeRadius),{yaw,pitch}=orientation;
 const x=globeRadius*Math.sin(u/globeRadius),y=globeRadius*Math.sin(v/globeRadius),z=Math.sqrt(Math.max(0,globeRadius**2-x*x-y*y));
 const py=y*Math.cos(pitch)+z*Math.sin(pitch),pz=-y*Math.sin(pitch)+z*Math.cos(pitch);
 const px=x*Math.cos(yaw)+pz*Math.sin(yaw),depth=-x*Math.sin(yaw)+pz*Math.cos(yaw);
 return {x:EYE_FRONT_CENTER.x+px,y:EYE_FRONT_CENTER.y+py,z:depth};
}
export function binocularGaze(values:Record<string,number>){
 const n=(key:string)=>Number.isFinite(values[key])?Math.max(0,Math.min(1,values[key])):0;
 // Anatomical in/out have opposite horizontal signs for the two eyes.
 return {x:(n('eyeLookOutLeft')-n('eyeLookInLeft')+n('eyeLookInRight')-n('eyeLookOutRight'))/2,y:(n('eyeLookDownLeft')-n('eyeLookUpLeft')+n('eyeLookDownRight')-n('eyeLookUpRight'))/2};
}

/** One finite target in cm. Eye separation is a stylized 6.4 cm; distance is authored, not measured. */
export function fixationTarget(gazeX:number,gazeY:number,distance=60){
 const finite=(n:number)=>Number.isFinite(n)?Math.max(-1,Math.min(1,n)):0;
 const z=Number.isFinite(distance)?Math.max(20,Math.min(200,distance)):60;
 const target={x:z*Math.tan(finite(gazeX)*32*Math.PI/180),y:z*Math.tan(finite(gazeY)*18*Math.PI/180),z};
 const eye=(x:number)=>({yaw:Math.atan2(target.x-x,z),pitch:Math.atan2(target.y,Math.hypot(target.x-x,z)),origin:x});
 return {target,left:eye(3.2),right:eye(-3.2)};
}
