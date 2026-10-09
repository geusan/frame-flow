import { contourPose, sampleCurves, type Cubic, type P } from "./shoulder-contour-e09";
const line=(a:P,b:P):Cubic=>[a,[a[0]+(b[0]-a[0])/3,a[1]+(b[1]-a[1])/3],[a[0]+2*(b[0]-a[0])/3,a[1]+2*(b[1]-a[1])/3],b];
/** A static diagnostic partition, NOT a new skin reconstruction. Original
 * external curves are unchanged. One shared internal cap-pit closing segment
 * is introduced for BOTH order conditions. Its validity is not assumed.
 */
export function occlusionSurfaces(){
 const pose=contourPose(0,"helper"),c=pose.curves;
 const torso=[c[0],c[1],line(pose.cap,pose.pit),...c.slice(7)];
 const arm=[...c.slice(2,7),line(pose.pit,pose.cap)];
 return {pose,torso,arm};
}
export type Surface="arm"|"torso";
export const paintOrder=(front:Surface):Surface[]=>front==="arm"?["torso","arm"]:["arm","torso"];
// SVG default nonzero fill rule. Unlike even-odd parity, winding is sensitive
// to opposite orientation where the original contour overlaps itself.
export function winding(p:P,polygon:P[]){
 let n=0;
 for(let i=0;i<polygon.length;i++){
  const a=polygon[i],b=polygon[(i+1)%polygon.length];
  const cross=(b[0]-a[0])*(p[1]-a[1])-(p[0]-a[0])*(b[1]-a[1]);
  if(a[1]<=p[1]&&b[1]>p[1]&&cross>0)n++;
  if(a[1]>p[1]&&b[1]<=p[1]&&cross<0)n--;
 }
 return n;
}
export function ownershipAudit(){
 const s=occlusionSurfaces(),polygons={arm:sampleCurves(s.arm),torso:sampleCurves(s.torso)},old=sampleCurves(s.pose.curves);
 let overlap=0,added=0,removed=0,difference=0;let addedExample:P|null=null;
 const width=340,height=490,coverage=new Uint8Array(width*height);let index=0;
 // Fixed diagnostic raster quadrature; geometry density stays 16 per curve.
 // Region and 0.5px cell size are recorded. Counts estimate projected area,
 // not skin area or renderer-pixel equality.
 for(let y=305.25;y<550;y+=.5)for(let x=505.25;x<675;x+=.5){
  const p:P=[x,y],a=winding(p,polygons.arm)!==0,t=winding(p,polygons.torso)!==0;
  const owner=(front:Surface)=>paintOrder(front).filter(k=>k==="arm"?a:t).at(-1)??null;
  const b=owner("arm"),c=owner("torso"),original=winding(p,old)!==0;
  coverage[index++]=b===null?0:1;
  if(a&&t)overlap++;
  if((b!==null)!==(c!==null))difference++;
  if(b!==null&&!original){added++;addedExample??=p;}
  if(original&&b===null)removed++;
 }
 // Flood-fill uncovered pixels from the ROI border; remaining uncovered
 // components are holes enclosed by the fixed projected surfaces.
 const visit=(seed:number,mark:number)=>{
   const queue=[seed];coverage[seed]=mark;let count=0,sx=0,sy=0;
   for(let q=0;q<queue.length;q++){
     const i=queue[q],x=i%width,y=Math.floor(i/width);count++;sx+=x;sy+=y;
     for(const j of [x>0?i-1:-1,x+1<width?i+1:-1,y>0?i-width:-1,y+1<height?i+width:-1])if(j>=0&&coverage[j]===0){coverage[j]=mark;queue.push(j);}
   }
   return {area:count*.25,centroid:[505.25+.5*sx/count,305.25+.5*sy/count]};
 };
 for(let i=0;i<coverage.length;i++)if((i<width||i>=width*(height-1)||i%width===0||i%width===width-1)&&coverage[i]===0)visit(i,2);
 const holes=[];for(let i=0;i<coverage.length;i++)if(coverage[i]===0)holes.push(visit(i,3));
 return {holes,grid:{bounds:[505,305,675,550],step:.5},overlapArea:overlap*.25,addedVsOriginalArea:added*.25,removedVsOriginalArea:removed*.25,orderSilhouetteDifferenceArea:difference*.25,addedExample};
}
