import { tangentPoseE13Base } from "./shoulder-base-e13";
import { type P, type Cubic } from "./shoulder-contour-e09";
export type E13Variant="baseline"|"relocated";
// Authored 160-degree proposal, not anatomical ground truth. Single independent
// variable: cap attachment position. Same tangent + handle-limit policy in both.
export const PROPOSED_CAP:P=[585,305];
export function attachmentPoseE13(variant:E13Variant){
  const input=tangentPoseE13Base(160,"aligned",variant==="relocated"?PROPOSED_CAP:undefined);
  const curves:Cubic[]=input.curves.map(c=>c.map(p=>[...p]) as Cubic);
  const c=curves[1],gap=c[3][0]-c[0][0],a=c[1][0]-c[0][0],b=c[3][0]-c[2][0];
  const applicable=gap>0&&a>=0&&b>=0;
  const scale=applicable?Math.min(1,gap/(a+b)):null;
  if(scale!==null&&scale<1){
    c[1]=[c[0][0]+scale*(c[1][0]-c[0][0]),c[0][1]+scale*(c[1][1]-c[0][1])];
    c[2]=[c[3][0]+scale*(c[2][0]-c[3][0]),c[3][1]+scale*(c[2][1]-c[3][1])];
  }
  return {pose:{...input,curves},gap,scale,applicable};
}
