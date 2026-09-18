"use client";
import {useState} from 'react';
import {eyelidCurves,freshEyelidRig} from './eyelid-rig';
import type {useFaceRigController} from './face-rig-controller';
import styles from './face-rig-panel.module.css';
export function EyelidRigPanel({face}:{face:ReturnType<typeof useFaceRigController>}){
 const [side,setSide]=useState<'left'|'right'>('left'),[edge,setEdge]=useState<'upper'|'lower'>('upper'),[index,setIndex]=useState(4),rig=face.eyelidRig[side];
 const blinkKey=side==='left'?'eyeBlinkLeft':'eyeBlinkRight',wideKey=side==='left'?'eyeWideLeft':'eyeWideRight',curves=eyelidCurves(face.telemetry.values[blinkKey],face.telemetry.values[wideKey],rig,face.telemetry.values[side==='left'?'eyeSquintLeft':'eyeSquintRight']);
 const update=(offset:number)=>face.setEyelidRig({...face.eyelidRig,[side]:{...rig,[edge]:rig[edge].map((v,i)=>i===index?offset:v)}});
 return <details open aria-label="눈꺼풀 리그"><summary>눈꺼풀 리그 · 위·아래 각 9점</summary><p>눈꼬리는 고정하고 위·아래 윤곽을 조절합니다. 좌우 눈 감김은 독립이며, 완전히 감으면 두 윤곽이 하나로 만납니다.</p>
 <label>편집할 눈<select aria-label="눈꺼풀 좌우" value={side} onChange={e=>setSide(e.target.value as typeof side)}><option value="left">왼쪽 눈</option><option value="right">오른쪽 눈</option></select></label>
 <svg viewBox="100 120 690 390" style={{width:'100%',background:'#f1e2d1',borderRadius:8}} aria-label="눈꺼풀 제어점 편집">{(['upper','lower'] as const).map(e=><g key={e}><polyline points={curves[e].map(p=>p.join(',')).join(' ')} fill="none" stroke={e==='upper'?'#7754a6':'#3b8b98'} strokeWidth={3}/>{curves[e].map((p,i)=><circle key={i} role="button" tabIndex={0} aria-label={`${e==='upper'?'위':'아래'} 눈꺼풀 점 ${i+1}`} cx={p[0]} cy={p[1]} r={edge===e&&index===i?7:4} fill={edge===e&&index===i?'#d88c30':e==='upper'?'#7754a6':'#3b8b98'} onClick={()=>{setEdge(e);setIndex(i);}} onKeyDown={event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();setEdge(e);setIndex(i);}}}/>)}</g>)}</svg>
 <label>눈꺼풀<select aria-label="위 아래 눈꺼풀" value={edge} onChange={e=>setEdge(e.target.value as typeof edge)}><option value="upper">위 눈꺼풀</option><option value="lower">아래 눈꺼풀</option></select></label>
 <label>제어점<select aria-label="눈꺼풀 제어점 선택" value={index} onChange={e=>setIndex(Number(e.target.value))}>{Array.from({length:9},(_,i)=><option key={i} value={i}>{i+1}{i===0||i===8?' · 고정 눈꼬리':''}</option>)}</select></label>
 <label>윤곽 높이 · {rig[edge][index].toFixed(1)}<input aria-label="눈꺼풀 윤곽 높이" disabled={index===0||index===8} type="range" min="-30" max="30" step="1" value={rig[edge][index]} onChange={e=>update(Number(e.target.value))}/></label>
 <label>눈 감김 중 위눈꺼풀 이동 비율 · {Math.round(rig.upperShare*100)}%<input aria-label="위눈꺼풀 이동 비율" type="range" min=".4" max=".95" step=".01" value={rig.upperShare} onChange={e=>face.setEyelidRig({...face.eyelidRig,[side]:{...rig,upperShare:Number(e.target.value)}})}/></label>
 <div className={styles.actions}>{[[0,'눈 뜨기'],[.5,'반쯤 감기'],[1,'완전히 감기']].map(([v,label])=><button key={label} type="button" onClick={()=>{face.clearTest();face.test(blinkKey,Number(v));}}>{label}</button>)}<button type="button" onClick={()=>face.setMode('live')}>웹캠 눈꺼풀 연결</button><button type="button" onClick={()=>face.setEyelidRig({...face.eyelidRig,[side]:freshEyelidRig()[side]})}>이 눈꺼풀 초기화</button></div>
 <p>수치는 캐릭터 눈의 로컬 좌표입니다. 얼굴 리그 저장으로 보관합니다. 홍채는 크기를 유지하며 윤곽 밖으로 나간 부분만 가려집니다.</p></details>;
}
