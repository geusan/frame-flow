import {eyelidCurves,traceLid,freshEyelidRig,type EyelidSide} from './eyelid-rig';
import {drawIrisSurface} from './iris-surface';
import type {RigFaceValues} from './face-rig';
export type EyeAppearance={enabled:boolean;size:number;pupil:number;spacing?:number;focusDistance?:number};
export const DEFAULT_EYE:EyeAppearance={enabled:true,size:1,pupil:.38,focusDistance:60,spacing:.94};
const root='/avatars/cat-2d-v1/left-eye-v1';
const make=()=>{const c=document.createElement('canvas');c.width=500;c.height=300;return c;};
/** Shared spherical projection used by the authoring eye; transparent output for the head texture. */
export class LeftEyeRenderer{
 readonly canvas=make();private content=make();private mask=make();private images:HTMLImageElement[]=[];private aperture:HTMLCanvasElement|null=null;private loading:Promise<void>|null=null;
 load(){return this.loading??=Promise.all(['sclera.png','iris-surface-v2.png','closed-lid.png'].map(async file=>{const image=new Image();image.src=`${root}/${file}`;await image.decode();return image;})).then(images=>{this.images=images;const c=document.createElement('canvas');c.width=923;c.height=388;const ctx=c.getContext('2d')!;ctx.drawImage(images[0],221,463,923,388,0,0,923,388);const data=ctx.getImageData(0,0,923,388);for(let i=0;i<data.data.length;i+=4){data.data[i+3]*=(.2126*data.data[i]+.7152*data.data[i+1]+.0722*data.data[i+2])/255;data.data[i]=data.data[i+1]=data.data[i+2]=255;}ctx.putImageData(data,0,0);this.aperture=c;}).catch(e=>{this.loading=null;throw e;});}
 render(values:RigFaceValues,appearance:EyeAppearance,rotation?:{yaw:number;pitch:number},lid:EyelidSide=freshEyelidRig().left){
  if(!this.aperture)return null;const ctx=this.canvas.getContext('2d')!;ctx.setTransform(.5,0,0,.5,0,0);ctx.clearRect(0,0,1000,600);
  const b=values.eyeBlinkLeft,opening=Math.max(0,1-b),w=310*appearance.size,ih=365*appearance.size;
  const curves=eyelidCurves(b,values.eyeWideLeft,lid,values.eyeSquintLeft);
  const aperture=(c:CanvasRenderingContext2D)=>{c.beginPath();traceLid(c,curves.upper);traceLid(c,[...curves.lower].reverse(),false);c.closePath();};
  if(opening>.001){ctx.save();aperture(ctx);ctx.clip();const white=ctx.createLinearGradient(0,180,0,450);white.addColorStop(0,'#cfc6be');white.addColorStop(.45,'#f6f1ec');white.addColorStop(1,'#fffdfb');ctx.fillStyle=white;ctx.fillRect(100,100,800,450);ctx.restore();const sc=this.content.getContext('2d')!;sc.setTransform(.5,0,0,.5,0,0);sc.clearRect(0,0,1000,600);sc.globalCompositeOperation='source-over';
   drawIrisSurface(sc,this.images[1],w/2,ih/2,appearance.pupil,values.eyeLookOutLeft-values.eyeLookInLeft,values.eyeLookDownLeft-values.eyeLookUpLeft,rotation);
   sc.fillStyle='#fff8eb';sc.globalAlpha=.9;sc.beginPath();sc.ellipse(435,244,22,32,-.6,0,Math.PI*2);sc.fill();sc.beginPath();sc.arc(408,282,8,0,Math.PI*2);sc.fill();sc.globalAlpha=1;
   const mc=this.mask.getContext('2d')!;mc.setTransform(.5,0,0,.5,0,0);mc.clearRect(0,0,1000,600);aperture(mc);mc.fillStyle='#fff';mc.fill();sc.setTransform(1,0,0,1,0,0);sc.globalCompositeOperation='destination-in';sc.drawImage(this.mask,0,0);sc.globalCompositeOperation='source-over';ctx.drawImage(this.content,0,0,1000,600);
  }
  ctx.strokeStyle='#211b18';ctx.lineCap='round';ctx.lineJoin='round';ctx.lineWidth=opening>.02?26:14;ctx.beginPath();traceLid(ctx,curves.upper);ctx.stroke();if(opening>.02){ctx.lineWidth=4;ctx.beginPath();traceLid(ctx,curves.lower);ctx.stroke();}const outer=curves.upper[8];ctx.lineWidth=12;ctx.beginPath();ctx.moveTo(...outer);ctx.lineTo(outer[0]+25,outer[1]-12);ctx.stroke();ctx.beginPath();ctx.moveTo(outer[0]-12,outer[1]+2);ctx.lineTo(outer[0]+10,outer[1]-16);ctx.stroke();return this.canvas;
 }
}
