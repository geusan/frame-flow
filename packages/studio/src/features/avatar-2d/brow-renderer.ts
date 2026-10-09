import {browCurve,freshBrowDetail,type BrowDetail} from './brow-detail';
import {RIG_HEAD_IMAGE} from './avatar-artwork';
import {FACE_CROP,type FacePoints} from './face-rig';
const root='/avatars/cat-2d-v1/brows-v1';
export class BrowRenderer{
 private sprite:HTMLImageElement|null=null;private pending:Promise<void>|null=null;private centers:number[]=[];private hair:HTMLCanvasElement|null=null;
 load(){return this.pending??=Promise.all([`${root}/brow.png`,RIG_HEAD_IMAGE].map(async file=>{const im=new Image();im.src=file;await im.decode();return im;})).then(([sprite,clean])=>{
  this.sprite=sprite;
  const c=document.createElement('canvas');c.width=1254;c.height=1254;const ctx=c.getContext('2d')!;ctx.drawImage(sprite,0,0);const data=ctx.getImageData(0,0,1254,1254).data;
  for(let n=0;n<32;n++){const x=Math.round(161+(n+.5)*931/32);let total=0,ySum=0;for(let y=551;y<691;y++){const a=data[(y*1254+x)*4+3];total+=a;ySum+=y*a;}this.centers.push(total?ySum/total:620);}
  const h=document.createElement('canvas');h.width=360;h.height=290;const hc=h.getContext('2d')!;hc.drawImage(clean,420,145,180,145,0,0,360,290);const pixels=hc.getImageData(0,0,360,290);
  for(let y=0;y<290;y++)for(let x=0;x<360;x++){const i=(y*360+x)*4,shade=Math.max(pixels.data[i],pixels.data[i+1],pixels.data[i+2]);pixels.data[i+3]=y<72?Math.round(Math.max(0,Math.min(1,(115-shade)/40))*255):0;}hc.putImageData(pixels,0,0);this.hair=h;
 }).catch(e=>{this.pending=null;throw e;});}
 draw(ctx:CanvasRenderingContext2D,points:FacePoints,thickness=1,detail:BrowDetail=freshBrowDetail(),neutral:FacePoints=points){if(!this.sprite)return;
  for(const side of ['left','right'] as const){const a=points[`${side}BrowInner`],b=points[`${side}BrowOuter`];
   const at=(t:number)=>browCurve(points,neutral,side,detail,t);
   const width=Math.hypot(b[0]-a[0],b[1]-a[1]),sy=width/931*thickness;
   for(let n=0;n<32;n++){const p=at(n/32),q=at((n+1)/32),angle=Math.atan2(q[1]-p[1],q[0]-p[0]),len=Math.hypot(q[0]-p[0],q[1]-p[1]);ctx.save();ctx.translate((p[0]-FACE_CROP.x)*2,(p[1]-FACE_CROP.y)*2);ctx.rotate(angle);if(side==='right')ctx.scale(1,-1);ctx.drawImage(this.sprite,161+n*931/32,551,931/32,140,0,(551-this.centers[n])*sy*2,len*2+.25,140*sy*2);ctx.restore();}
  }
  if(this.hair)ctx.drawImage(this.hair,0,0);
 }
}
