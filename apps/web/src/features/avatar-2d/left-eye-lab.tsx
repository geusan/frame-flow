"use client";
import {useState} from 'react';
import {SphericalEyePreview} from './spherical-eye-preview';
import {projectEye} from './eye-projection';
import type {RigFaceValues} from './face-rig';
import styles from './left-eye-lab.module.css';
const root='/avatars/cat-2d-v1/left-eye-v1';
const sprites={sclera:{file:'sclera.png',box:[221,463,923,388]},iris:{file:'iris.png',box:[342,309,567,644]},lid:{file:'closed-lid.png',box:[288,603,716,98]}};
function Sprite({kind,x,y,width,height}:{kind:keyof typeof sprites;x:number;y:number;width:number;height:number}){
  const {file,box:[sx,sy,sw,sh]}=sprites[kind];
  return <svg x={x} y={y} width={width} height={height} viewBox={`${sx} ${sy} ${sw} ${sh}`} preserveAspectRatio="none" overflow="hidden"><image href={`${root}/${file}`} width={1254} height={1254}/></svg>;
}
/** Authoring-only prototype: generated plates, independent iris, aperture occlusion. */
export function LeftEyeLab({values}:{values:RigFaceValues}){
  const [live,setLive]=useState(false),[blink,setBlink]=useState(0),[x,setX]=useState(0),[y,setY]=useState(0),[size,setSize]=useState(1),[pupil,setPupil]=useState(.38),[guides,setGuides]=useState(true);
  const b=live?values.eyeBlinkLeft:blink,gx=live?values.eyeLookOutLeft-values.eyeLookInLeft:x,gy=live?values.eyeLookDownLeft-values.eyeLookUpLeft:y;
  const irisH=365*size;
  const projection=projectEye(gx,gy,irisH/2);
  return <section id="left-eye-lab" className={styles.lab} aria-label="왼쪽 눈 레이어 실험">
    <h3>왼쪽 눈 · 이미지 레이어 실험</h3><p>캐릭터의 왼쪽 눈(화면 오른쪽)을 위한 시제품입니다. 안구 회전을 투영해 홍채와 동공이 곡면을 따라 움직입니다. 홍채 외경과 동공 직경을 따로 조절할 수 있습니다.</p>
    <div className={styles.actions}><button type="button" aria-pressed={!live} onClick={()=>setLive(false)}>수동 테스트</button><button type="button" aria-pressed={live} onClick={()=>setLive(true)}>웹캠 왼눈 값 연결</button><button type="button" aria-pressed={guides} onClick={()=>setGuides(!guides)}>가림 경계 {guides?'숨기기':'표시'}</button></div>
    <SphericalEyePreview values={{...values,eyeBlinkLeft:b,eyeLookOutLeft:Math.max(0,gx),eyeLookInLeft:Math.max(0,-gx),eyeLookDownLeft:Math.max(0,gy),eyeLookUpLeft:Math.max(0,-gy)}} appearance={{enabled:true,size,pupil}} guides={guides}/>
    <p aria-live="off">눈 감김 {Math.round(b*100)}% · 시선 X {gx.toFixed(2)} / Y {gy.toFixed(2)}{live?' · 상단에서 웹캠을 연결하고 무표정을 보정하세요.':''}</p>
    <label>눈 감기<input aria-label="왼눈 레이어 눈 감기" type="range" min="0" max="1" step=".01" disabled={live} value={blink} onChange={e=>setBlink(Number(e.target.value))}/></label>
    <label>좌우 시선<input aria-label="왼눈 레이어 좌우 시선" type="range" min="-1" max="1" step=".01" disabled={live} value={x} onChange={e=>setX(Number(e.target.value))}/></label>
    <label>상하 시선<input aria-label="왼눈 레이어 상하 시선" type="range" min="-1" max="1" step=".01" disabled={live} value={y} onChange={e=>setY(Number(e.target.value))}/></label>
    <label>홍채 외경 · 캐릭터 비율<input aria-label="왼눈 레이어 홍채 크기" type="range" min=".6" max="1.4" step=".01" value={size} onChange={e=>setSize(Number(e.target.value))}/></label>
    <label>동공 직경 · 홍채 대비 {Math.round(pupil*100)}%<input aria-label="왼눈 레이어 동공 크기" type="range" min=".12" max=".75" step=".01" value={pupil} onChange={e=>setPupil(Number(e.target.value))}/></label>
    <p>회전: 좌우 {Math.round(projection.yaw*180/Math.PI)}° · 상하 {Math.round(projection.pitch*180/Math.PI)}°. 동공 크기는 수동 설정이며 웹캠 측정값이 아닙니다.</p>
    <div className={styles.actions}>{[[0,'눈 뜨기'],[.5,'반쯤 감기'],[1,'완전히 감기']].map(([value,label])=><button key={label} type="button" onClick={()=>{setLive(false);setBlink(Number(value));}}>{label}</button>)}</div>
    <div className={styles.layers}>{Object.entries(sprites).map(([key,s])=><a href={`${root}/${s.file}`} key={key} download><svg viewBox="0 0 300 180"><Sprite kind={key as keyof typeof sprites} x={20} y={key==='lid'?75:30} width={260} height={key==='lid'?35:120}/></svg>{key==='sclera'?'흰자·눈 테두리':key==='iris'?'이전 홍채·동공 원본':'닫힌 눈꺼풀'} ↓</a>)}</div>
    <p>홍채의 실제 외경은 유지하고 회전각에 따른 원근 단축을 적용합니다. 동공도 같은 회전을 따르며 크기는 독립적으로 바뀝니다. 원화와의 일치, 반쯤 감긴 눈의 선 모양은 추가 조정이 필요합니다. 본체 양쪽 눈에 같은 구면 메시가 적용되어 있습니다. 본체 설정은 위의 양쪽 눈 패널에서 조절합니다.</p>
  </section>;
}
