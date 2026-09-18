"use client";
import { useState } from "react";
import Link from "next/link";
import { contourPath, metrics, sampleCurves } from "./shoulder-contour-e09";
import { tangentAngles, type E10Variant } from "./shoulder-tangent-e10";
import { tangentPoseE11, crossSectionWidths } from "./shoulder-tangent-e11";
import styles from "./shoulder-contour-study.module.css";
const variants:E10Variant[]=["baseline","aligned"];
export function ShoulderTangentRangeStudy(){
  const [degrees,setDegrees]=useState<45|90|135>(45);
  const [overlay,setOverlay]=useState(false),[zoom,setZoom]=useState(true);
  return <main className={styles.study}>
    <Link href="/live-avatar/2d/shoulder/e10">← E10 90° 기준</Link>
    <h1>E11 · 45°·135° 접선 정책 비교</h1>
    <p>왼쪽 어깨 · 정면 · 45°·90°·135° 정지 비교. 연결점과 핸들 길이를 보존하고 접선 방향만 바꿉니다.</p>
    <p className={styles.notice}>E11: 45° 국소 개선 / 135° 시각 실패. 접선은 이어져도 목 옆의 뾰족한 돌출이 남습니다. 연속 입력·왕복은 미검증입니다.</p>
    <div className={styles.toolbar}>
      {([45,90,135] as const).map(a=><button key={a} aria-pressed={degrees===a} onClick={()=>setDegrees(a)}>{a}°</button>)}
      <label><input type="checkbox" checked={overlay} onChange={e=>setOverlay(e.target.checked)}/> 접선·제어점 표시</label>
      <label><input type="checkbox" checked={zoom} onChange={e=>setZoom(e.target.checked)}/> 어깨 확대</label>
      <span>옷·음영·물리 없음 · 11곡선 / 176표본 고정</span>
    </div>
    <div className={styles.comparison} style={{gridTemplateColumns:"repeat(2, minmax(0, 1fr))"}}>
      {variants.map(v=>{const p=tangentPoseE11(degrees,v),m=metrics(p),a=tangentAngles(p.curves);return <section key={v}>
        <h2>{v==="baseline"?"A · E09 B 보존":"B · 접선 방향 정렬"}</h2>
        <svg data-e11={v} aria-label={`${v} ${degrees}도 실루엣`} viewBox={zoom?"555 270 180 180":"495 95 365 475"}>
          <path d={contourPath(p.curves)} fill="#59636b"/>
          {overlay&&<g>
            {p.curves.map((c,i)=><path key={i} d={`M ${c.map(q=>q.join(" ")).join(" L ")}`} fill="none" stroke="#e6ad53" strokeWidth=".65"/>)}
            {sampleCurves(p.curves).map((q,i)=><circle key={i} cx={q[0]} cy={q[1]} r=".6" fill="#d7e4eb"/>)}
            {a.map(({join})=><circle key={join} cx={p.curves[join][0][0]} cy={p.curves[join][0][1]} r="1.8" fill="#ffc778"/>)}
            <path d={`M ${p.shoulder.join(" ")} L ${p.elbow.join(" ")}`} fill="none" stroke="#dad9ff" strokeWidth="1"/>
          </g>}
        </svg>
        <p>경계 교차 {m.crossings} · 최대 접선 꺾임 {Math.max(...a.map(v=>v.degrees)).toFixed(2)}°</p>
        <small>실제 위팔 단면폭: {crossSectionWidths(p).map(w=>`${w.along}px 지점 ${w.width.toFixed(2)}px`).join(" / ")}</small>
      </section>;})}
    </div>
    <details open><summary>정지 판정 기준과 범위</summary>
      <ul><li>목 옆→어깨→위팔에 작은 뿔·패임이 없어야 합니다.</li><li>겨드랑이는 급한 모서리 대신 짧은 오목한 곡선으로 옆구리와 연결되어야 합니다.</li><li>정렬하는 6개 연결점의 접선 방향 차이 0°, 경계 교차 0, 비대상 경계·위팔 단면폭 동일.</li><li>방향 연결만 검사하며 곡률 연속성이나 해부학적 정답을 보장하지 않습니다.</li></ul>
    </details>
    <p>연속 입력과 왕복은 아직 평가하지 않습니다. 90°는 E10 정책을 그대로 옮겼는지 확인하는 비교 자세입니다.</p>
  </main>;
}
