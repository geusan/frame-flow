"use client";
import { useState } from "react";
import Link from "next/link";
import { contourPath, metrics, sampleCurves } from "./shoulder-contour-e09";
import { tangentPose, tangentAngles, actualWidths, type E10Variant } from "./shoulder-tangent-e10";
import styles from "./shoulder-contour-study.module.css";
const variants:E10Variant[]=["baseline","aligned"];
export function ShoulderTangentStudy(){
  const [overlay,setOverlay]=useState(false),[zoom,setZoom]=useState(true);
  return <main className={styles.study}>
    <Link href="/live-avatar/2d/shoulder/e09">← E09 비교군</Link>
    <h1>E10 · 90° 어깨 접선 연결</h1>
    <p>왼쪽 어깨 · 정면 · 90° 고정. 연결점과 핸들 길이를 보존하고 접선 방향만 바꿉니다.</p>
    <p className={styles.notice}>90° 국소 개선 확인: 어깨 돌출과 겨드랑이 꺾임이 줄었습니다. 피부 전체의 자연스러움·다른 각도·앞뒤 면·접촉은 미검증입니다.</p>
    <div className={styles.toolbar}>
      <label><input type="checkbox" checked={overlay} onChange={e=>setOverlay(e.target.checked)}/> 접선·제어점 표시</label>
      <label><input type="checkbox" checked={zoom} onChange={e=>setZoom(e.target.checked)}/> 어깨 확대</label>
      <span>옷·음영·물리 없음 · 11곡선 / 176표본 고정</span>
    </div>
    <div className={styles.comparison} style={{gridTemplateColumns:"repeat(2, minmax(0, 1fr))"}}>
      {variants.map(v=>{const p=tangentPose(v),m=metrics(p),a=tangentAngles(p.curves);return <section key={v}>
        <h2>{v==="baseline"?"A · E09 B 보존":"B · 접선 방향 정렬"}</h2>
        <svg data-e10={v} aria-label={`${v} 90도 실루엣`} viewBox={zoom?"555 270 180 180":"495 95 365 475"}>
          <path d={contourPath(p.curves)} fill="#59636b"/>
          {overlay&&<g>
            {p.curves.map((c,i)=><path key={i} d={`M ${c.map(q=>q.join(" ")).join(" L ")}`} fill="none" stroke="#e6ad53" strokeWidth=".65"/>)}
            {sampleCurves(p.curves).map((q,i)=><circle key={i} cx={q[0]} cy={q[1]} r=".6" fill="#d7e4eb"/>)}
            {a.map(({join})=><circle key={join} cx={p.curves[join][0][0]} cy={p.curves[join][0][1]} r="1.8" fill="#ffc778"/>)}
            <path d={`M ${p.shoulder.join(" ")} L ${p.elbow.join(" ")}`} fill="none" stroke="#dad9ff" strokeWidth="1"/>
          </g>}
        </svg>
        <p>경계 교차 {m.crossings} · 최대 접선 꺾임 {Math.max(...a.map(v=>v.degrees)).toFixed(2)}°</p>
        <small>실제 위팔 단면폭: {actualWidths(p.curves,p.shoulder).map(w=>`${w.along}px 지점 ${w.width.toFixed(2)}px`).join(" / ")}</small>
      </section>;})}
    </div>
    <details open><summary>90° 판정 기준과 범위</summary>
      <ul><li>목 옆→어깨→위팔에 작은 뿔·패임이 없어야 합니다.</li><li>겨드랑이는 급한 모서리 대신 짧은 오목한 곡선으로 옆구리와 연결되어야 합니다.</li><li>정렬하는 6개 연결점의 접선 방향 차이 0°, 경계 교차 0, 비대상 경계·위팔 단면폭 동일.</li><li>방향 연결만 검사하며 곡률 연속성이나 해부학적 정답을 보장하지 않습니다.</li></ul>
    </details>
    <p>다른 각도·왕복은 이 화면에서 생성하지 않습니다. 90° 기준 형태의 판정과 전체 움직임의 판정을 분리합니다.</p>
  </main>;
}
