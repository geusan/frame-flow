import { add, angle, angleDelta, length, rotate, sub, type Anchors, type Point, type Pose } from "./rig";
import { PARTS, type ArtPart } from "./parts";
import { ShapeUtils, Vector2 } from "three";
import { manualLeftShoulderPose, restShoulderElevation } from "./shoulder-lab-model";

const body = PARTS.find(p => p.id === "body")!;
const arm = PARTS.find(p => p.id === "left-arm")!;
const surfaceSamples = new Map<string, Map<number, Point[]>>();

/** The tank top follows the torso. Only its outer strap/armhole can move a
 * little; the neckline, chest print/shading and hem must not inherit arm rotation. */
export function garmentPoint(point: Point, rest: Anchors, pose: Pose): Point {
  const side=Math.max(0,Math.min(1,(point[0]-565)/30));
  const upper=Math.max(0,Math.min(1,(430-point[1])/100));
  const weight=side*upper*upper;
  return [point[0]+(pose.joints.leftShoulder[0]-rest.leftShoulder[0])*.2*weight,
    point[1]+(pose.joints.leftShoulder[1]-rest.leftShoulder[1])*.25*weight];
}

// One exterior contour. The old arm/body cut is deliberately absent: triangles
// on either side now reference the SAME vertices and the SAME artwork texture.
export const CONNECTED_LEFT_BODY: ArtPart = {
  ...body, id: "left-shoulder-surface",
  polygon: [...body.polygon.slice(0, 4), ...arm.polygon.slice(1, 23), ...body.polygon.slice(10)],
};

export function insidePolygon(p: Point, polygon: Point[]) {
  let inside = false;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const a = polygon[i], b = polygon[j];
    if ((a[1] > p[1]) !== (b[1] > p[1]) && p[0] < (b[0]-a[0])*(p[1]-a[1])/(b[1]-a[1])+a[0]) inside = !inside;
  }
  return inside;
}

function polygonDistance(p: Point, polygon: Point[]) {
  if (insidePolygon(p,polygon)) return 0;
  let distance=Infinity;
  for(let i=0;i<polygon.length;i++) {
    const a=polygon[i],b=polygon[(i+1)%polygon.length],dx=b[0]-a[0],dy=b[1]-a[1];
    const t=Math.max(0,Math.min(1,((p[0]-a[0])*dx+(p[1]-a[1])*dy)/(dx*dx+dy*dy||1)));
    distance=Math.min(distance,Math.hypot(p[0]-a[0]-t*dx,p[1]-a[1]-t*dy));
  }
  return distance;
}

export function artworkGrid(polygon: Point[], spacing: number, trim = false) {
  const minX=Math.floor(Math.min(...polygon.map(p=>p[0]))),minY=Math.floor(Math.min(...polygon.map(p=>p[1])));
  const width=Math.ceil(Math.max(...polygon.map(p=>p[0]))-minX),height=Math.ceil(Math.max(...polygon.map(p=>p[1]))-minY);
  if (trim) {
    const points:Point[]=polygon.map(p=>[...p]);
    let triangles=ShapeUtils.triangulateShape(polygon.map(p=>new Vector2(...p)),[]);
    // Conforming refinement preserves the exact concave armpit boundary. A
    // rectangular grid can accidentally bridge the narrow transparent gap.
    for(let pass=0;pass<9;pass++) {
      const mids=new Map<string,number>();
      const key=(a:number,b:number)=>a<b?`${a},${b}`:`${b},${a}`;
      for(const [a,b,c] of triangles) for(const [i,j] of [[a,b],[b,c],[c,a]]) {
        const k=key(i,j);
        if(!mids.has(k) && length(sub(points[i],points[j]))>spacing*1.5) {
          mids.set(k,points.length);points.push([(points[i][0]+points[j][0])/2,(points[i][1]+points[j][1])/2]);
        }
      }
      if(!mids.size) break;
      const next:number[][]=[];
      for(const [a,b,c] of triangles) {
        const ab=mids.get(key(a,b)),bc=mids.get(key(b,c)),ca=mids.get(key(c,a));
        if(ab!==undefined && bc!==undefined && ca!==undefined) next.push([a,ab,ca],[ab,b,bc],[ca,bc,c],[ab,bc,ca]);
        else if(ab!==undefined && bc!==undefined) next.push([b,bc,ab],[a,ab,c],[ab,bc,c]);
        else if(ab!==undefined && ca!==undefined) next.push([a,ab,ca],[b,c,ab],[ab,c,ca]);
        else if(bc!==undefined && ca!==undefined) next.push([c,ca,bc],[a,b,ca],[b,bc,ca]);
        else if(ab!==undefined) next.push([a,ab,c],[ab,b,c]);
        else if(bc!==undefined) next.push([b,bc,a],[bc,c,a]);
        else if(ca!==undefined) next.push([c,ca,b],[ca,a,b]);
        else next.push([a,b,c]);
      }
      triangles=next;
    }
    // Flip interior diagonals to remove thin triangles introduced by refinement.
    // Boundary edges remain constrained, including the concave armpit notch.
    const cross=(a:number,b:number,c:number)=>(points[b][0]-points[a][0])*(points[c][1]-points[a][1])-(points[b][1]-points[a][1])*(points[c][0]-points[a][0]);
    const cot=(a:number,b:number,o:number)=>{
      const u=sub(points[a],points[o]),v=sub(points[b],points[o]);return (u[0]*v[0]+u[1]*v[1])/Math.max(1e-10,Math.abs(u[0]*v[1]-u[1]*v[0]));
    };
    for(let pass=0;pass<24;pass++) {
      const edges=new Map<string,{a:number;b:number;opposite:number;triangle:number}[]>();
      triangles.forEach(([a,b,c],triangle)=>{for(const [i,j,o] of [[a,b,c],[b,c,a],[c,a,b]]) {const key=i<j?`${i},${j}`:`${j},${i}`;const e=edges.get(key)??[];e.push({a:i,b:j,opposite:o,triangle});edges.set(key,e);}});
      const used=new Set<number>();let flips=0;
      for(const adjacent of edges.values()) {
        if(adjacent.length!==2) continue;
        const [e,f]=adjacent,{a,b}=e,c=e.opposite,d=f.opposite;
        if(used.has(e.triangle)||used.has(f.triangle)||cot(a,b,c)+cot(a,b,d)>=-1e-7||cross(c,d,a)*cross(c,d,b)>=-1e-8)continue;
        const sign=Math.sign(cross(...triangles[e.triangle] as [number,number,number]));
        triangles[e.triangle]=cross(c,d,b)*sign>0?[c,d,b]:[d,c,b];
        triangles[f.triangle]=cross(d,c,a)*sign>0?[d,c,a]:[c,d,a];
        used.add(e.triangle);used.add(f.triangle);flips++;
      }
      if(!flips)break;
    }
    return {points,indices:triangles.flat(),minX,minY,width,height};
  }
  const nx=Math.ceil(width/spacing),ny=Math.ceil(height/spacing),points:Point[]=[],indices:number[]=[];
  const dx=width/nx,dy=height/ny;
  for(let y=0;y<=ny;y++) for(let x=0;x<=nx;x++) {
    const px=minX+dx*x,py=minY+dy*y;points.push([px,py]);
    if(x<nx && y<ny && (!trim || [[px,py],[px+dx,py],[px,py+dy],[px+dx,py+dy],[px+dx/2,py+dy/2]].some(p=>insidePolygon(p as Point,polygon)))) {
      const i=y*(nx+1)+x;indices.push(i,i+nx+1,i+1,i+1,i+nx+1,i+nx+2);
    }
  }
  return {points,indices,minX,minY,width,height};
}

/** Cotangent-weight 2D ARAP, local rotation / global position iterations.
 * Only the small shoulder region is free. The torso and distal arm are exact
 * Dirichlet constraints; a prefactored Laplacian keeps manual input interactive.
 * Reference: Sorkine & Alexa, SGP 2007, https://igl.ethz.ch/projects/ARAP/ .
 */
export class ShoulderSurface {
  private neighbors: number[][];
  private weights: Map<number,number>[];
  private free: number[];
  private freeIndex: Int32Array;
  private handles: number[];
  private factor: Float64Array;
  private samples: Map<number,Point[]>;
  constructor(readonly points: Point[], readonly indices: number[], private rest: Anchors) {
    const key=JSON.stringify([rest,points.length,indices.length]);
    this.samples=surfaceSamples.get(key)??new Map();surfaceSamples.set(key,this.samples);
    const sets = points.map(() => new Set<number>());
    for (let k = 0; k < indices.length; k += 3) {
      for (const [a,b] of [[indices[k],indices[k+1]],[indices[k+1],indices[k+2]],[indices[k+2],indices[k]]]) { sets[a].add(b); sets[b].add(a); }
    }
    this.neighbors = sets.map(s => [...s]);
    this.weights=points.map(()=>new Map<number,number>());
    for(let k=0;k<indices.length;k+=3) {
      const [a,b,c]=indices.slice(k,k+3);
      for(const [i,j,o] of [[a,b,c],[b,c,a],[c,a,b]]) {
        const u=sub(points[i],points[o]),v=sub(points[j],points[o]);
        const w=(u[0]*v[0]+u[1]*v[1])/Math.max(1e-10,Math.abs(u[0]*v[1]-u[1]*v[0]))*.5;
        this.weights[i].set(j,(this.weights[i].get(j)??0)+w);this.weights[j].set(i,(this.weights[j].get(i)??0)+w);
      }
    }
    for(const map of this.weights) for(const [j,w] of map) map.set(j,Math.max(1e-5,w));
    this.handles = points.map(([x,y]) => {
      if (x <= rest.neck[0] + 40 || y < 290) return 0;
      if (length(sub([x,y],[613,440])) < 1e-6) return 3;
      if (y >= 470 && polygonDistance([x,y],arm.polygon) < polygonDistance([x,y],body.polygon)) return 1;
      if (y >= 590) return 0;
      return -1;
    });
    this.free = points.flatMap((_,i) => this.handles[i] === -1 && sets[i].size ? [i] : []);
    this.freeIndex = new Int32Array(points.length).fill(-1);
    this.free.forEach((v,i) => { this.freeIndex[v] = i; });
    const n = this.free.length, l = new Float64Array(n*n);
    for (let i=0;i<n;i++) {
      const v=this.free[i]; l[i*n+i]=[...this.weights[v].values()].reduce((a,b)=>a+b,0);
      for(const j of this.neighbors[v]) if(this.freeIndex[j]>=0) l[i*n+this.freeIndex[j]]=-this.weights[v].get(j)!;
    }
    for(let i=0;i<n;i++) for(let j=0;j<=i;j++) {
      let sum=l[i*n+j]; for(let k=0;k<j;k++) sum-=l[i*n+k]*l[j*n+k];
      l[i*n+j]=i===j?Math.sqrt(sum):sum/l[j*n+j];
    }
    this.factor=l;
  }
  async prepare(keepGoing: () => boolean) {
    for(let degree=0;degree<=160 && keepGoing();degree+=2) {
      if(!this.samples.has(degree))this.samples.set(degree,this.solve(manualLeftShoulderPose(degree,this.rest)));
      if(degree%8===0)await new Promise<void>(resolve=>setTimeout(resolve,0));
    }
  }
  deform(pose: Pose): Point[] {
    const v=sub(pose.joints.leftElbow,pose.joints.leftShoulder);
    const degrees=Math.max(0,Math.min(160,Math.atan2(v[0],v[1])*180/Math.PI));
    const baseline=manualLeftShoulderPose(degrees,this.rest);
    // This surface is scoped to the one-axis manual study, not live retargeting.
    let low=Math.floor(degrees/2)*2,high=Math.min(160,low+2);
    const neutral=restShoulderElevation(this.rest);
    if(low<neutral && high>neutral) {if(degrees<neutral)high=neutral;else low=neutral;}
    const blend=high===low?0:(degrees-low)/(high-low);
    const sample=(degree:number)=>{
      if(!this.samples.has(degree))this.samples.set(degree,this.solve(manualLeftShoulderPose(degree,this.rest)));
      return this.samples.get(degree)!;
    };
    const a=sample(low),b=sample(high);
    const s=this.rest.leftShoulder,delta=angleDelta(angle(sub(baseline.joints.leftElbow,baseline.joints.leftShoulder)),angle(sub(this.rest.leftElbow,s)));
    return this.preventFoldovers(this.points.map((p,i)=>this.handles[i]===1?add(baseline.joints.leftShoulder,rotate(sub(p,s),delta)):[a[i][0]+(b[i][0]-a[i][0])*blend,a[i][1]+(b[i][1]-a[i][1])*blend]));
  }
  private solve(pose: Pose): Point[] {
    const s=this.rest.leftShoulder, target=pose.joints.leftShoulder;
    const delta=angleDelta(angle(sub(pose.joints.leftElbow,target)),angle(sub(this.rest.leftElbow,s)));
    if(Math.abs(delta)<1e-12 && length(sub(s,target))<1e-12) return this.points;
    const raised=Math.max(0,Math.min(1,-delta/(100*Math.PI/180))),ease=raised*raised*(3-2*raised);
    const direction=sub(this.rest.leftElbow,s),size=length(direction),axis:Point=[direction[0]/size,direction[1]/size];
    const pit:Point=[613,440],offset=sub(pit,s),along=offset[0]*axis[0]+offset[1]*axis[1];
    // Corrective attachment: the armpit approaches the shoulder as the arm rises,
    // instead of travelling around it on the long rigid upper-arm lever.
    const pitTarget=add(target,rotate(sub(offset,[axis[0]*along*ease,axis[1]*along*ease]),delta));
    const q=this.points.map((p,i): Point => {
      const h=this.handles[i];
      if(h===0) return [...p];
      if(h===1) return add(target,rotate(sub(p,s),delta));
      if(h===3) return add(pitTarget,rotate(sub(p,pit),delta));
      const w=Math.max(0,Math.min(1,(p[0]-560)/90));
      return add(add(s,rotate(sub(p,s),delta*w)),[(target[0]-s[0])*w,(target[1]-s[1])*w]);
    });
    const c=new Float64Array(q.length), sn=new Float64Array(q.length), n=this.free.length;
    const bx=new Float64Array(n), by=new Float64Array(n), l=this.factor;
    for(let iteration=0;iteration<28;iteration++) {
      for(let i=0;i<q.length;i++) {
        let dot=0,cross=0;
        for(const j of this.neighbors[i]) {
          const px=this.points[i][0]-this.points[j][0],py=this.points[i][1]-this.points[j][1];
          const x=q[i][0]-q[j][0],y=q[i][1]-q[j][1];
          const w=this.weights[i].get(j)!;dot+=w*(px*x+py*y);cross+=w*(px*y-py*x);
        }
        const size=Math.hypot(dot,cross)||1;c[i]=dot/size;sn[i]=cross/size;
      }
      for(let k=0;k<n;k++) {
        const i=this.free[k]; let x=0,y=0;
        for(const j of this.neighbors[i]) {
          const px=this.points[i][0]-this.points[j][0],py=this.points[i][1]-this.points[j][1];
          const w=this.weights[i].get(j)!;
          x+=w*((c[i]+c[j])*px-(sn[i]+sn[j])*py)*.5;
          y+=w*((sn[i]+sn[j])*px+(c[i]+c[j])*py)*.5;
          if(this.freeIndex[j]<0){x+=w*q[j][0];y+=w*q[j][1];}
        }
        bx[k]=x;by[k]=y;
      }
      for(let i=0;i<n;i++) {
        for(let j=0;j<i;j++){bx[i]-=l[i*n+j]*bx[j];by[i]-=l[i*n+j]*by[j];}
        bx[i]/=l[i*n+i];by[i]/=l[i*n+i];
      }
      for(let i=n-1;i>=0;i--) {
        for(let j=i+1;j<n;j++){bx[i]-=l[j*n+i]*bx[j];by[i]-=l[j*n+i]*by[j];}
        bx[i]/=l[i*n+i];by[i]/=l[i*n+i];q[this.free[i]]=[bx[i],by[i]];
      }
    }
    return this.preventFoldovers(q);
  }
  private preventFoldovers(q: Point[]): Point[] {
    // ARAP alone does not forbid foldovers. Project the few compressed boundary
    // triangles back to positive signed area; fixed torso/arm handles never move.
    for(let pass=0;pass<300;pass++) {
      let corrected=false;
      for(let k=0;k<this.indices.length;k+=3) {
        const ids=this.indices.slice(k,k+3),[a,b,c]=ids;
        const p=this.points;
        const restArea=(p[b][0]-p[a][0])*(p[c][1]-p[a][1])-(p[b][1]-p[a][1])*(p[c][0]-p[a][0]);
        const sign=Math.sign(restArea);
        const area=((q[b][0]-q[a][0])*(q[c][1]-q[a][1])-(q[b][1]-q[a][1])*(q[c][0]-q[a][0]))*sign;
        const deficit=Math.abs(restArea)*.12-area;if(deficit<=1e-7)continue;
        const gradients:Point[]=[[q[b][1]-q[c][1],q[c][0]-q[b][0]],[q[c][1]-q[a][1],q[a][0]-q[c][0]],[q[a][1]-q[b][1],q[b][0]-q[a][0]]];
        let denom=0;ids.forEach((v,i)=>{if(this.freeIndex[v]>=0)denom+=gradients[i][0]**2+gradients[i][1]**2;});
        if(denom<1e-12)continue;
        ids.forEach((v,i)=>{if(this.freeIndex[v]>=0){q[v][0]+=sign*deficit*gradients[i][0]/denom;q[v][1]+=sign*deficit*gradients[i][1]/denom;}});
        corrected=true;
      }
      if(!corrected)break;
    }
    return q;
  }
}
