/** E09: boundary-only authoring study. Not a skin mesh, not a production rig.
 * All variants share the same cubic topology and rigid arm. No textures,
 * underpaint, garment, physics, mesh refinement or E08 solver is involved.
 * Coordinates remain in the 1024 x 1536 artwork frame. Hidden skin is a hypothesis.
 */
export type P = [number, number];
export type Variant = "minimal" | "helper" | "corrected";
export type Cubic = [P, P, P, P];
export const VARIANTS: Variant[] = ["minimal", "helper", "corrected"];
export const STATIC_ANGLES = [0, 19.5731258304102, 45, 90, 135, 160];
export const SAMPLE_COUNT = 16; // fixed in all three conditions; no interior mesh
const S: P = [623, 346];
const REST_ANGLE = Math.atan2(64, 180) * 180 / Math.PI;
const mix = (a: P, b: P, t: number): P => [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
const add = (a: P, b: P): P => [a[0] + b[0], a[1] + b[1]];
const smooth = (t: number) => { t = Math.max(0, Math.min(1, t)); return t * t * (3 - 2 * t); };
const line = (a: P, b: P): Cubic => [a, mix(a,b,1/3), mix(a,b,2/3), b];

// Sparse authored LOCAL residuals, not samples cached from a deformation solver.
// order: cap tangent, inner-arm tangent, axillary turn, thorax tangent.
// These are provisional design choices; exact key reproduction is not visual validation.
export const CORRECTIONS: { angle: number; offsets: [P,P,P,P] }[] = [
  { angle: 0, offsets: [[0,0],[0,0],[0,0],[0,0]] },
  { angle: REST_ANGLE, offsets: [[0,0],[0,0],[0,0],[0,0]] },
  { angle: 45, offsets: [[0,-3],[-3,-5],[-1,-4],[0,-4]] },
  { angle: 90, offsets: [[0,-8],[-9,-9],[-3,-8],[0,-9]] },
  { angle: 135, offsets: [[-4,-7],[-9,-3],[-3,-7],[0,-8]] },
  { angle: 160, offsets: [[-5,-3],[-5,0],[-2,-4],[0,-5]] },
];
function residuals(degrees: number): P[] {
  const i = CORRECTIONS.findIndex(k => k.angle >= degrees);
  if (i <= 0) return CORRECTIONS[0].offsets;
  const a=CORRECTIONS[i-1], b=CORRECTIONS[i];
  return a.offsets.map((p,j)=>mix(p,b.offsets[j],smooth((degrees-a.angle)/(b.angle-a.angle))));
}
export function contourPose(input: number, variant: Variant) {
  const degrees = Number.isFinite(input) ? Math.max(0,Math.min(160,input)) : REST_ANGLE;
  const radians=degrees*Math.PI/180, delta=(REST_ANGLE-degrees)*Math.PI/180;
  // Preserve the existing one-axis skeleton, including its coupled lift, across A/B/C.
  const lift=smooth((degrees-30)/130);
  const shoulder: P=[S[0]-9*lift,S[1]-32*lift];
  const rigid=(p: P): P=>[shoulder[0]+(p[0]-S[0])*Math.cos(delta)-(p[1]-S[1])*Math.sin(delta),shoulder[1]+(p[0]-S[0])*Math.sin(delta)+(p[1]-S[1])*Math.cos(delta)];
  const arm=(along:number,width:number):P=>[shoulder[0]+Math.sin(radians)*along+Math.cos(radians)*width,shoulder[1]+Math.cos(radians)*along-Math.sin(radians)*width];
  const raised=smooth((degrees-REST_ANGLE)/(160-REST_ANGLE));
  // Minimal: two influences. Neck/side are thorax-owned; arm boundary is rigid.
  let cap=rigid([627,313]);
  let capTangent=mix([579,313],cap,.65);
  let pit=mix([611,397],rigid([611,397]),.5);
  let innerTangent=mix(arm(64,-29),pit,.5);
  let thoraxTangent: P=[605,430];
  if(variant!=="minimal") {
    // Helper 1: deltoid envelope. Upper contour rolls around the shoulder;
    // the arm's cross sections remain rigid. Influence ends at 64 px down arm.
    cap=mix(cap,arm(-15,32),raised);
    capTangent=mix(capTangent,add(cap,[-18,-8]),raised);
    // Helper 2: axillary attachment remains beside the upper thorax, not at
    // a rotated distal point. It owns the two local boundary tangents only.
    pit=[611-5*raised,397-42*raised];
    innerTangent=mix(arm(64,-29),pit,.65);
    thoraxTangent=[605-3*raised,430-28*raised];
  }
  if(variant==="corrected") {
    const r=residuals(degrees);
    capTangent=add(capTangent,r[0]);innerTangent=add(innerTangent,r[1]);
    pit=add(pit,r[2]);thoraxTangent=add(thoraxTangent,r[3]);
  }
  const outerRoot=arm(64,32),outerElbow=arm(Math.hypot(64,180),24);
  const innerElbow=arm(Math.hypot(64,180),-24),innerRoot=arm(64,-29);
  const start:P=[512,313], neck:P=[579,313], side:P=[596,449], waist:P=[581,545], bottom:P=[512,545];
  const curves: Cubic[]=[
    line(start,neck),
    [neck,capTangent,add(cap,[-5,-5]),cap],
    [cap,arm(7,39),arm(40,35),outerRoot],
    [outerRoot,arm(100,30),arm(150,25),outerElbow],
    line(outerElbow,innerElbow), // deliberate cut at elbow: not an anatomical elbow contour
    [innerElbow,arm(150,-25),arm(100,-28),innerRoot],
    [innerRoot,innerTangent,add(pit,[5,0]),pit],
    [pit,add(pit,[-4,10]),thoraxTangent,side],
    [side,[593,483],[583,516],waist],
    line(waist,bottom),line(bottom,start),
  ];
  return { degrees, variant, shoulder, elbow:arm(Math.hypot(64,180),0), pit, cap, curves,
    widths: [64,100,150].map(t=>[arm(t, t===64?32:t===100?30:25),arm(t,t===64?-29:t===100?-28:-25)] as [P,P]),
    controls: [cap,capTangent,pit,innerTangent,thoraxTangent],
  };
}
export function sampleCurves(curves: Cubic[]): P[] {
  return curves.flatMap(([a,b,c,d])=>Array.from({length:SAMPLE_COUNT},(_,i):P=>{
    const t=i/SAMPLE_COUNT,u=1-t;
    return [u*u*u*a[0]+3*u*u*t*b[0]+3*u*t*t*c[0]+t*t*t*d[0],u*u*u*a[1]+3*u*u*t*b[1]+3*u*t*t*c[1]+t*t*t*d[1]];
  }));
}
export function contourPath(curves:Cubic[]) {
  return `M ${curves[0][0].join(" ")} `+curves.map(c=>`C ${c.slice(1).map(p=>p.join(" ")).join(" ")}`).join(" ")+" Z";
}
export function metrics(pose:ReturnType<typeof contourPose>) {
  const p=sampleCurves(pose.curves);
  const cross=(a:P,b:P,c:P)=>(b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]);
  let crossings=0;
  for(let i=0;i<p.length;i++) for(let j=i+2;j<p.length;j++) {
    if(i===0&&j===p.length-1)continue;
    const a=p[i],b=p[(i+1)%p.length],c=p[j],d=p[(j+1)%p.length];
    if(cross(a,b,c)*cross(a,b,d)<-1e-8&&cross(c,d,a)*cross(c,d,b)<-1e-8)crossings++;
  }
  // Root-to-pit distance is a membrane-span proxy, not actual skin stretch/area.
  const root=pose.curves[6][0];
  return { crossings, boundarySamples:p.length, rootToPit:Math.hypot(root[0]-pose.pit[0],root[1]-pose.pit[1]),
    pitDrop:pose.pit[1]-pose.shoulder[1], upperLength:Math.hypot(pose.elbow[0]-pose.shoulder[0],pose.elbow[1]-pose.shoulder[1]),
    widths:pose.widths.map(([a,b])=>Math.hypot(a[0]-b[0],a[1]-b[1])) };
}
export const REST_ELEVATION=REST_ANGLE;
