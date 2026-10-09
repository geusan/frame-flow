import { actualWidths } from "./shoulder-tangent-e10";
import { contourPose, type P, type Cubic } from "./shoulder-contour-e09";

/** E11: frozen copy of the E10 policy, evaluated at three static poses only.
 * Change tangent direction, preserving endpoints and each handle's length.
 * No additional bones, curve spans, mesh samples, garment or physics.
 */
export const TANGENT_JOINS = [1, 2, 3, 6, 7, 8] as const;
export type E10Variant = "baseline" | "aligned";
const sub=(a:P,b:P):P=>[a[0]-b[0],a[1]-b[1]];
const norm=(p:P)=>Math.hypot(...p);
const unit=(p:P):P=>{const n=norm(p);if(n<1e-10)throw new Error("Undefined tangent");return [p[0]/n,p[1]/n];};
const step=(p:P,d:P,length:number):P=>[p[0]+d[0]*length,p[1]+d[1]*length];
const bisector=(a:P,b:P):P=>{const u=unit(a),v=unit(b);return unit([u[0]+v[0],u[1]+v[1]]);};
export function tangentPoseE11(degrees:45|90|135, variant:E10Variant) {
  if(![45,90,135].includes(degrees))throw new Error("E11 only supports static 45/90/135-degree poses");
  const pose=contourPose(degrees,"helper");
  const curves:Cubic[]=pose.curves.map(c=>c.map(p=>[...p]) as Cubic);
  if(variant==="aligned") {
    for(const j of TANGENT_JOINS) {
      const prev=curves[j-1],next=curves[j],p=next[0];
      // At the fixed boundaries use their existing direction. At the cap and
      // axillary turn author a bisector of adjacent endpoint chords. This
      // defines a direction, not a new attachment location or cached pose.
      const direction=j===1||j===6 ? unit(sub(p,prev[2]))
        :j===3||j===8 ? unit(sub(next[1],p))
        :bisector(sub(p,prev[0]),sub(next[3],p));
      if(j!==1&&j!==6)prev[2]=step(p,direction,-norm(sub(p,prev[2])));
      if(j!==3&&j!==8)next[1]=step(p,direction,norm(sub(next[1],p)));
    }
  }
  return {...pose,curves};
}

/** Project to the arm frame before applying E10's true curve-intersection metric. */
export function crossSectionWidths(pose:ReturnType<typeof tangentPoseE11>) {
  const a=pose.degrees*Math.PI/180;
  const local=pose.curves.map(c=>c.map(p=>{
    const x=p[0]-pose.shoulder[0],y=p[1]-pose.shoulder[1];
    return [x*Math.sin(a)+y*Math.cos(a),-x*Math.cos(a)+y*Math.sin(a)] as P;
  }) as Cubic);
  return actualWidths(local,[0,0]);
}
