import {projectEyeSurface} from './eye-projection';
import {affineTriangle} from './face-triangulation';
import type {FacePoint} from './face-rig';
const RINGS=5,SEGMENTS=32;
const vertices:FacePoint[]=[[0,0]];const triangles:[number,number,number][]=[];
for(let r=1;r<=RINGS;r++)for(let s=0;s<SEGMENTS;s++){const a=s/SEGMENTS*Math.PI*2;vertices.push([r/RINGS*Math.cos(a),r/RINGS*Math.sin(a)]);}
for(let s=0;s<SEGMENTS;s++)triangles.push([0,1+s,1+(s+1)%SEGMENTS]);
for(let r=1;r<RINGS;r++)for(let s=0;s<SEGMENTS;s++){const a=1+(r-1)*SEGMENTS+s,b=1+(r-1)*SEGMENTS+(s+1)%SEGMENTS,c=1+r*SEGMENTS+s,d=1+r*SEGMENTS+(s+1)%SEGMENTS;triangles.push([a,c,d],[a,d,b]);}
export function drawIrisSurface(ctx:CanvasRenderingContext2D,image:HTMLImageElement,rx:number,ry:number,pupil:number,gx:number,gy:number,rotation?:{yaw:number;pitch:number}){
 const source=vertices.map(([u,v])=>[623+u*258,630+v*300] as FacePoint);
 const target=vertices.map(([u,v])=>{const p=projectEyeSurface(u*rx,v*ry,gx,gy,350,rotation);return [p.x,p.y] as FacePoint;});
 for(const triangle of triangles){const from=triangle.map(i=>source[i]),to=triangle.map(i=>target[i]),matrix=affineTriangle(from,to);if(!matrix)continue;
  ctx.save();ctx.beginPath();const cx=to.reduce((s,p)=>s+p[0],0)/3,cy=to.reduce((s,p)=>s+p[1],0)/3;
  to.forEach(([x,y],i)=>{const px=x+(x-cx)*.008,py=y+(y-cy)*.008;if(i)ctx.lineTo(px,py);else ctx.moveTo(px,py);});ctx.closePath();ctx.clip();ctx.transform(...matrix);ctx.drawImage(image,0,0);ctx.restore();
 }
 const contour=(scale:number)=>{ctx.beginPath();for(let s=0;s<=64;s++){const a=s/64*Math.PI*2,p=projectEyeSurface(Math.cos(a)*rx*scale,Math.sin(a)*ry*scale,gx,gy,350,rotation);if(s)ctx.lineTo(p.x,p.y);else ctx.moveTo(p.x,p.y);}ctx.closePath();};
 contour(1);ctx.strokeStyle='#38200d';ctx.lineWidth=5;ctx.stroke();contour(pupil);ctx.fillStyle='#110c08';ctx.fill();
}
