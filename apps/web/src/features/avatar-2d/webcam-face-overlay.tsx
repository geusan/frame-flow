"use client";
import type { Landmark } from './rig';
import { MEDIAPIPE_FACE_POINTS, FACE_POINT_LABELS, type FacePointId } from './face-rig';
import styles from './avatar-studio.module.css';

const features = [
  {color:'#55e3fa',ids:['rightEyeOuter','rightEyeUpper','rightEyeInner','rightEyeLower','rightEyeOuter']},
  {color:'#55e3fa',ids:['leftEyeOuter','leftEyeUpper','leftEyeInner','leftEyeLower','leftEyeOuter']},
  {color:'#ef96ff',ids:['rightBrowOuter','rightBrowMid','rightBrowInner']},
  {color:'#ef96ff',ids:['leftBrowOuter','leftBrowMid','leftBrowInner']},
  {color:'#ffbe5c',ids:['mouthRight','mouthUpper','mouthLeft','mouthLower','mouthRight']},
  {color:'#ffbe5c',ids:['mouthRight','mouthInnerUpper','mouthLeft','mouthInnerLower','mouthRight']},
] satisfies {color:string;ids:FacePointId[]}[];
export function WebcamFaceOverlay({points,aspect}:{points:Landmark[];aspect:number}){
  const width=1000*aspect;
  const valid=(p:Landmark|undefined):p is Landmark=>!!p&&Number.isFinite(p[0])&&Number.isFinite(p[1]);
  return <svg className={styles.webcamMesh} viewBox={`0 0 ${width} 1000`} preserveAspectRatio="xMidYMid meet" aria-label="웹캠 얼굴 검출 기준점" data-landmark-count={points.length}>
    {points.map((p,i)=>valid(p)&&<circle key={i} cx={p[0]*width} cy={p[1]*1000} r={1.7} fill="#ffffff66"/>)}
    {features.map((feature,i)=>{const ps=feature.ids.map(id=>points[MEDIAPIPE_FACE_POINTS[id]!]);return ps.every(valid)&&<polyline key={i} points={ps.map(p=>`${p[0]*width},${p[1]*1000}`).join(' ')} fill="none" stroke={feature.color} strokeWidth={3}/>;})}
    {Object.entries(MEDIAPIPE_FACE_POINTS).map(([id,index])=>{const p=points[index];return valid(p)&&<circle key={id} cx={p[0]*width} cy={p[1]*1000} r={id.includes('Iris')?5:3.5} fill={id.includes('Iris')?'#77f58d':id.startsWith('mouth')?'#ffbe5c':id.includes('Brow')?'#ef96ff':'#55e3fa'}><title>{FACE_POINT_LABELS[id as FacePointId]}</title></circle>;})}
  </svg>;
}
