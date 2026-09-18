"use client";
import {useState} from 'react';
import {browControls,freshBrowDetail,type BrowSide} from './brow-detail';
import {alignFaceFeatures} from './feature-alignment';
import {characterEyes} from './eye-layout';
import {solveFacePoints} from './face-rig';
import type {useFaceRigController} from './face-rig-controller';
import styles from './face-rig-panel.module.css';
export function BrowDetailPanel({face}:{face:ReturnType<typeof useFaceRigController>}){
 const [side,setSide]=useState<BrowSide>('left'),[index,setIndex]=useState(4),p=face.browDetail[side][index];
 const rest=face.profile.poses.neutral.points,layout=characterEyes(rest,face.eyeAppearance.enabled?face.eyeAppearance.spacing:1),neutral=alignFaceFeatures(rest,rest,layout,face.featureAlignment),animated=alignFaceFeatures(rest,solveFacePoints(face.profile,face.telemetry.values),layout,face.featureAlignment);
 const points=browControls(animated,neutral,side,face.browDetail),cx=neutral[`${side}BrowMid`][0],cy=neutral[`${side}BrowMid`][1];
 const update=(key:'x'|'y'|'gain',value:number)=>face.setBrowDetail({...face.browDetail,[side]:face.browDetail[side].map((v,i)=>i===index?{...v,[key]:value}:v)});
 return <details open><summary>눈썹 정밀 제어점 · 좌우 각 9개</summary><p>1번은 안쪽, 5번은 중앙, 9번은 바깥쪽입니다. 각 점의 위치와 표정 반응 배율을 따로 조절합니다.</p><label>편집할 눈썹<select aria-label="정밀 눈썹 좌우" value={side} onChange={e=>setSide(e.target.value as BrowSide)}><option value="left">왼쪽 눈썹</option><option value="right">오른쪽 눈썹</option></select></label>
 <svg viewBox={`${cx-30} ${cy-18} 60 36`} aria-label="눈썹 9개 제어점" style={{width:'100%',background:'#f2e5d7',borderRadius:8}}><polyline points={points.map(p=>p.join(',')).join(' ')} fill="none" stroke="#795799" strokeWidth={.5}/>{points.map((p,i)=><g key={i}><circle role="button" tabIndex={0} aria-label={`눈썹 제어점 ${i+1}`} cx={p[0]} cy={p[1]} r={index===i?1.1:.7} fill={index===i?'#d6872d':'#795799'} onClick={()=>setIndex(i)} onKeyDown={e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();setIndex(i);}}}/><text x={p[0]} y={p[1]-2} textAnchor="middle" fontSize={2.3} fill="#604576">{i+1}</text></g>)}</svg>
 <label>제어점<select aria-label="눈썹 세부 제어점" value={index} onChange={e=>setIndex(Number(e.target.value))}>{Array.from({length:9},(_,i)=><option value={i} key={i}>{i+1}{i===0?' · 안쪽':i===4?' · 중앙':i===8?' · 바깥쪽':''}</option>)}</select></label>
 {([['x','좌우 위치',-1.5,1.5,.1],['y','상하 위치',-5,5,.1],['gain','표정 반응 배율',0,2,.05]] as const).map(([key,label,min,max,step])=><label key={key}>{label} · {p[key].toFixed(2)}<input aria-label={`눈썹 제어점 ${label}`} type="range" min={min} max={max} step={step} value={p[key]} onChange={e=>update(key,Number(e.target.value))}/></label>)}
 <div className={styles.actions}><button type="button" onClick={()=>face.setBrowDetail({...face.browDetail,[side]:face.browDetail[side].map((p,i)=>i===index?{x:0,y:0,gain:1}:p)})}>선택 점 초기화</button><button type="button" onClick={()=>face.setBrowDetail({...face.browDetail,[side]:freshBrowDetail()[side]})}>이 눈썹 초기화</button></div><p>양쪽 총 18개 제어점입니다. 얼굴 리그 저장으로 보관합니다. 추적 입력은 기존 눈썹 채널을 사용하며 점별 배율로 반응을 다르게 설정합니다.</p></details>;
}
