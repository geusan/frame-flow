"use client";
import { useState } from "react";
import Link from "next/link";
import { contourPath, metrics, sampleCurves } from "./shoulder-contour-e09";
import { tangentAngles } from "./shoulder-tangent-e10";
import { crossSectionWidths } from "./shoulder-base-e13";
import { neckDiagnostics } from "./shoulder-handle-e12";
import { attachmentPoseE13, type E13Variant } from "./shoulder-attachment-e13";
import styles from "./shoulder-contour-study.module.css";
const variants:E13Variant[]=["baseline","relocated"];
export function ShoulderAttachmentStudy(){
  const degrees=160;
  const [overlay,setOverlay]=useState(false),[zoom,setZoom]=useState(true);
  return <main className={styles.study}>
    <Link href="/live-avatar/2d/shoulder/e12">← E12 135° 기준</Link>
    <h1>E13 · 160° 어깨 연결점</h1>
    <p>왼쪽 어깨 · 정면 · 160° 정지 비교. 외곽점 위치만 입력 변수로 바꾸고 동일한 접선·길이 규칙을 재계산합니다.</p>
    <p className={styles.notice}>160° 목 옆 패임·돌출 개선 확인. 겨드랑이 전환과 전체 피부 부피는 미검증입니다. 새 외곽점은 가려진 피부의 임시 설계입니다.</p>
    <div className={styles.toolbar}>
      <label><input type="checkbox" checked={overlay} onChange={e=>setOverlay(e.target.checked)}/> 접선·제어점 표시</label>
      <label><input type="checkbox" checked={zoom} onChange={e=>setZoom(e.target.checked)}/> 어깨 확대</label>
      <span>옷·음영·물리 없음 · 11곡선 / 176표본 고정</span>
    </div>
    <div className={styles.comparison} style={{gridTemplateColumns:"repeat(2, minmax(0, 1fr))"}}>
      {variants.map(v=>{const {pose:p,scale,applicable,gap}=attachmentPoseE13(v),m=metrics(p),a=tangentAngles(p.curves),n=neckDiagnostics(p.curves[1]);return <section key={v}>
        <h2>{v==="baseline"?"A · 기존 외곽점":"B · 외곽점 위치 변경"}</h2>
        <svg data-e13={v} aria-label={`${v} ${degrees}도 실루엣`} viewBox={zoom?"555 270 180 180":"495 95 365 475"}>
          <path d={contourPath(p.curves)} fill="#59636b"/>
          {overlay&&<g>
            {p.curves.map((c,i)=><path key={i} d={`M ${c.map(q=>q.join(" ")).join(" L ")}`} fill="none" stroke="#e6ad53" strokeWidth=".65"/>)}
            {sampleCurves(p.curves).map((q,i)=><circle key={i} cx={q[0]} cy={q[1]} r=".6" fill="#d7e4eb"/>)}
            {a.map(({join})=><circle key={join} cx={p.curves[join][0][0]} cy={p.curves[join][0][1]} r="1.8" fill="#ffc778"/>)}
            <path d={`M ${p.shoulder.join(" ")} L ${p.elbow.join(" ")}`} fill="none" stroke="#dad9ff" strokeWidth="1"/>
          </g>}
        </svg>
        <p>경계 교차 {m.crossings} · 최대 접선 꺾임 {Math.max(...a.map(v=>v.degrees)).toFixed(2)}°</p>
        <small>가로 간격 {gap.toFixed(3)}px · 정책 {applicable?"적용":"거부"} · 핸들 배율 {scale===null?"적용 불가":scale.toFixed(4)} · 목→어깨 최소 dx/dt {n.minDx.toFixed(3)} (음수면 역행)</small>
        <small>실제 위팔 단면폭: {crossSectionWidths(p).map(w=>`${w.along}px 지점 ${w.width.toFixed(2)}px`).join(" / ")}</small>
      </section>;})}
    </div>
    <details open><summary>정지 판정 기준과 범위</summary>
      <ul><li>목 옆→어깨→위팔에 작은 뿔·패임이 없어야 합니다.</li><li>겨드랑이는 급한 모서리 대신 짧은 오목한 곡선으로 옆구리와 연결되어야 합니다.</li><li>정렬하는 6개 연결점의 접선 방향 차이 0°, 경계 교차 0, 비대상 경계·위팔 단면폭 동일.</li><li>160° 목→어깨 곡선은 좌표 역행이 없어야 하며, 두 끝점의 사각 범위 안에 있어야 합니다. 곡률·피부 내부는 별도 검증 대상입니다.</li></ul>
    </details>
    <p>후보는 160° 전용입니다. 기존 45°·90°·135° 화면은 보존했으며, 중간 각도·왕복·의상은 아직 평가하지 않습니다.</p>
  </main>;
}
