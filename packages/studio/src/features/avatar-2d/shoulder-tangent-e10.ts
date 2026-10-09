import { contourPose, type P, type Cubic } from "./shoulder-contour-e09";

/** E10 is ONLY a 90-degree authored boundary experiment. No angle interpolator.
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
export function tangentPose(variant:E10Variant) {
  const pose=contourPose(90,"helper");
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
export function tangentAngles(curves:Cubic[]) {
  return TANGENT_JOINS.map(j=>{
    const p=curves[j][0],a=unit(sub(p,curves[j-1][2])),b=unit(sub(curves[j][1],p));
    return {join:j,degrees:Math.atan2(Math.abs(a[0]*b[1]-a[1]*b[0]),a[0]*b[0]+a[1]*b[1])*180/Math.PI};
  });
}
export function bezier(c:Cubic,t:number):P {
  const u=1-t;
  return [0,1].map(k=>u*u*u*c[0][k]+3*u*u*t*c[1][k]+3*u*t*t*c[2][k]+t*t*t*c[3][k]) as P;
}
/** Actual intersections with the rigid upper/inner curves at 90°, not handle widths. */
export function actualWidths(curves:Cubic[],shoulder:P) {
  const yAt=(c:Cubic,x:number)=>{
    let low=0,high=1;const ascending=c[3][0]>c[0][0];
    for(let n=0;n<55;n++){const mid=(low+high)/2;if((bezier(c,mid)[0]<x)===ascending)low=mid;else high=mid;}
    return bezier(c,(low+high)/2)[1];
  };
  return [100,150].map(along=>({along,width:yAt(curves[5],shoulder[0]+along)-yAt(curves[3],shoulder[0]+along)}));
}
