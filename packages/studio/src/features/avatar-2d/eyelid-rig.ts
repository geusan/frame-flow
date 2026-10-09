export type LidPoint=[number,number];
export type EyelidSide={upper:number[];lower:number[];upperShare:number};
export type EyelidRig={version:1;left:EyelidSide;right:EyelidSide};
const side=():EyelidSide=>({upper:Array(9).fill(0),lower:Array(9).fill(0),upperShare:.78});
export const freshEyelidRig=():EyelidRig=>({version:1,left:side(),right:side()});
const clamp=(v:number,a:number,b:number)=>Number.isFinite(v)?Math.max(a,Math.min(b,v)):a;
export function parseEyelidRig(value:unknown):EyelidRig{const r=freshEyelidRig(),v=value as EyelidRig;if(!v||v.version!==1)return r;for(const s of ['left','right'] as const){const p=v[s];if(!p)continue;if(Number.isFinite(p.upperShare))r[s].upperShare=clamp(p.upperShare,.4,.95);for(const edge of ['upper','lower'] as const)if(Array.isArray(p[edge])&&p[edge].length===9)r[s][edge]=p[edge].map((n,i)=>i===0||i===8?0:clamp(n,-30,30));}return r;}
// Rest aperture sampled from the generated sclera. Endpoints remain shared and fixed.
const REST=[[159.8,327.82,327.82],[230.88,255.53,389.91],[301.95,224.91,423.93],[373.02,206.2,444.34],[444.1,195.14,451.15],[514.3,193.44,445.19],[585.37,200.24,422.23],[656.45,216.4,367.79],[727.52,242.35,242.35]];
export function eyelidCurves(blink:number,wide:number,rig:EyelidSide,squint=0){const b=clamp(blink,0,1),w=clamp(wide,0,1)*(1-b),upper:LidPoint[]=[],lower:LidPoint[]=[];
 REST.forEach(([x,u,l],i)=>{const weight=Math.sin(i/8*Math.PI),a=u+rig.upper[i]-w*20*weight+clamp(squint,0,1)*25*weight,z=l+rig.lower[i]+w*8*weight-clamp(squint,0,1)*65*weight,lo=Math.min(a,z),hi=Math.max(a,z),seam=lo+(hi-lo)*rig.upperShare;upper.push([x,lo+(seam-lo)*b]);lower.push([x,hi+(seam-hi)*b]);});return {upper,lower};}
/** Midpoint quadratic segments keep the contour inside the control-point hull. */
export function traceLid(ctx:CanvasRenderingContext2D,points:LidPoint[],move=true){if(move)ctx.moveTo(...points[0]);else ctx.lineTo(...points[0]);for(let i=1;i<points.length-1;i++)ctx.quadraticCurveTo(...points[i],(points[i][0]+points[i+1][0])/2,(points[i][1]+points[i+1][1])/2);ctx.lineTo(...points[points.length-1]);}
