import { tangentPoseE11 } from "./shoulder-tangent-e11";
import type { Cubic } from "./shoulder-contour-e09";
export type E12Variant="baseline"|"limited";
/** Same endpoints and tangent directions as E11. Only two handle lengths in
 * neck-to-cap segment 1 may change. This static study supports 45/90/135 only.
 * Limit the sum of the two positive x projections to the available x span.
 * Ordered Bezier x controls guarantee no horizontal backtracking for this span.
 */
export function handlePoseE12(degrees:45|90|135,variant:E12Variant){
  const pose=tangentPoseE11(degrees,"aligned");
  const curves:Cubic[]=pose.curves.map(c=>c.map(p=>[...p]) as Cubic);
  const c=curves[1],gap=c[3][0]-c[0][0];
  const start=[c[1][0]-c[0][0],c[1][1]-c[0][1]];
  const end=[c[3][0]-c[2][0],c[3][1]-c[2][1]];
  if(gap<=0||start[0]<0||end[0]<0)throw new Error("E12 handle limit requires ordered endpoints and forward tangents; revise the attachment hypothesis");
  const limit=Math.min(1,gap/(start[0]+end[0]));
  const scale=variant==="limited"?limit:1;
  // Avoid introducing rounding differences where no limit is needed.
  if(scale<1){
    c[1]=[c[0][0]+scale*start[0],c[0][1]+scale*start[1]];
    c[2]=[c[3][0]-scale*end[0],c[3][1]-scale*end[1]];
  }
  return {pose:{...pose,curves},scale};
}
/** Exact minimum of the quadratic x derivative on [0,1], not a dense sweep. */
export function neckDiagnostics(c:Cubic){
  const d=[c[1][0]-c[0][0],c[2][0]-c[1][0],c[3][0]-c[2][0]];
  const a=d[0]-2*d[1]+d[2],b=2*(d[1]-d[0]);
  const t=Math.abs(a)>1e-12?-b/(2*a):-1;
  const minDx=3*Math.min(d[0],d[2],t>0&&t<1?a*t*t+b*t+d[0]:Infinity);
  return {xControlOrder:c.map(p=>p[0]),minDx,
    handles:[Math.hypot(c[1][0]-c[0][0],c[1][1]-c[0][1]),Math.hypot(c[3][0]-c[2][0],c[3][1]-c[2][1])],
    chord:Math.hypot(c[3][0]-c[0][0],c[3][1]-c[0][1])};
}
