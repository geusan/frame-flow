import type { FacePoint } from './face-rig';
export type FaceTriangle=[number,number,number];
export const triangleArea=(a:FacePoint,b:FacePoint,c:FacePoint)=>(b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]);
/** Deterministic Delaunay connectivity is built once on the neutral control mesh. */
export function triangulateFace(input:FacePoint[]):FaceTriangle[]{
  const p:FacePoint[]=[...input,[-2000,-2000],[4000,-2000],[1000,4000]],n=input.length;
  let triangles:FaceTriangle[]=[[n,n+1,n+2]];
  const inside=(point:FacePoint,t:FaceTriangle)=>{
    const [a,b,c]=t.map(i=>p[i]);const ax=a[0]-point[0],ay=a[1]-point[1],bx=b[0]-point[0],by=b[1]-point[1],cx=c[0]-point[0],cy=c[1]-point[1];
    const d=(ax*ax+ay*ay)*(bx*cy-cx*by)-(bx*bx+by*by)*(ax*cy-cx*ay)+(cx*cx+cy*cy)*(ax*by-bx*ay);
    return d*triangleArea(a,b,c)>1e-7;
  };
  for(let index=0;index<n;index++){
    const bad=new Set(triangles.filter(t=>inside(p[index],t))),edges=new Map<string,{edge:[number,number];count:number}>();
    for(const t of bad)for(let i=0;i<3;i++){const edge:[number,number]=[t[i],t[(i+1)%3]],key=[...edge].sort((a,b)=>a-b).join(':');const existing=edges.get(key);if(existing)existing.count++;else edges.set(key,{edge,count:1});}
    triangles=triangles.filter(t=>!bad.has(t));
    for(const {edge,count}of edges.values())if(count===1){const t:FaceTriangle=[edge[0],edge[1],index];if(triangleArea(p[t[0]],p[t[1]],p[t[2]])<0)[t[0],t[1]]=[t[1],t[0]];if(Math.abs(triangleArea(p[t[0]],p[t[1]],p[t[2]]))>1e-6)triangles.push(t);}
  }
  return triangles.filter(t=>t.every(i=>i<n));
}
export function affineTriangle(source:FacePoint[],target:FacePoint[]):[number,number,number,number,number,number]|null {
  const [a,b,c]=source,[d,e,f]=target;const x1=b[0]-a[0],y1=b[1]-a[1],x2=c[0]-a[0],y2=c[1]-a[1],det=x1*y2-x2*y1;
  if(Math.abs(det)<1e-7)return null;
  const A=((e[0]-d[0])*y2-(f[0]-d[0])*y1)/det,C=((f[0]-d[0])*x1-(e[0]-d[0])*x2)/det;
  const B=((e[1]-d[1])*y2-(f[1]-d[1])*y1)/det,D=((f[1]-d[1])*x1-(e[1]-d[1])*x2)/det;
  return [A,B,C,D,d[0]-A*a[0]-C*a[1],d[1]-B*a[0]-D*a[1]];
}
export function safeFaceDeformation(rest:FacePoint[],target:FacePoint[],triangles:FaceTriangle[]):{points:FacePoint[];limited:boolean}{
  let amount=1;
  while(amount>.03){const points=rest.map((p,i)=>[p[0]+(target[i][0]-p[0])*amount,p[1]+(target[i][1]-p[1])*amount] as FacePoint);
    if(triangles.every(t=>triangleArea(points[t[0]],points[t[1]],points[t[2]])>=Math.max(.015,triangleArea(rest[t[0]],rest[t[1]],rest[t[2]])*.005)))return {points,limited:amount<1};amount*=.8;}
  return {points:rest.map(p=>[...p] as FacePoint),limited:true};
}
