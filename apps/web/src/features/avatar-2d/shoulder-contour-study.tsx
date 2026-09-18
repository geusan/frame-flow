"use client";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { contourPose, contourPath, sampleCurves, metrics, VARIANTS, REST_ELEVATION, type Variant } from "./shoulder-contour-e09";
import styles from "./shoulder-contour-study.module.css";
const labels:Record<Variant,string>={minimal:"A · 최소 리그",helper:"B · 역할별 보조 제어",corrected:"C · B + 자세별 보정"};
const angles=[0,REST_ELEVATION,45,90,135,160];
export function ShoulderContourStudy() {
  const [angle,setAngle]=useState(90),[overlay,setOverlay]=useState(false),[zoom,setZoom]=useState(false),[sweep,setSweep]=useState(false);
  const [timing,setTiming]=useState("미측정"),[gate,setGate]=useState(false);
  const angleRef=useRef(angle), timingRef=useRef<number[]>([]);
  useEffect(()=>{ angleRef.current=angle; },[angle]);
  useEffect(()=>{
    if(!sweep)return;
    let frame=0,start:number|undefined,last:number|undefined;
    const phase=Math.acos(1-angleRef.current/80); timingRef.current=[];
    const tick=(now:number)=>{
      start??=now;
      if(last!==undefined)timingRef.current.push(now-last);last=now;
      setAngle(80*(1-Math.cos(phase+(now-start)/12000*Math.PI*2)));
      if(now-start>=12000){
        const sorted=[...timingRef.current].sort((a,b)=>a-b);
        setTiming(`${sorted.length} frames · rAF p95 ${sorted[Math.floor(sorted.length*.95)]?.toFixed(1)} ms · >50 ms ${sorted.filter(v=>v>50).length}`);
        setSweep(false);return;
      }
      frame=requestAnimationFrame(tick);
    };
    const hidden=()=>{if(document.hidden){setSweep(false);setTiming("백그라운드 전환으로 측정 중단");}};
    document.addEventListener("visibilitychange",hidden);frame=requestAnimationFrame(tick);
    return ()=>{cancelAnimationFrame(frame);document.removeEventListener("visibilitychange",hidden);};
  },[sweep]);
  const change=(n:number)=>{if(Number.isFinite(n)){setSweep(false);setAngle(Math.max(0,Math.min(160,n)));}};
  return <main className={styles.study}>
    <Link href="/live-avatar/2d/shoulder">← E08 실패 비교군 그대로 열기</Link>
    <h1>E09 · 왼쪽 어깨의 단색 경계</h1>
    <p>정면 · 팔 벌림 한 축 · 화면 오른쪽. 의상·음영·물리 없음. 원화 좌표의 상체 절반과 위팔만 표시하며 팔꿈치에서 잘랐습니다.</p>
    <p className={styles.notice}>E09 정지 평가 실패: 0°에서 A·B·C 경계 교차, 135°·160°에서 패임·돌출. 중간 각도와 왕복은 미검증입니다. 옷에 가렸던 몸통과 겨드랑이는 임시 설계입니다.</p>
    <div className={styles.toolbar}>
      <label>각도 <input aria-label="E09 각도" type="number" min={0} max={160} step={.1} value={Math.round(angle*10)/10} onChange={e=>change(e.target.valueAsNumber)} /></label>
      <input aria-label="E09 팔 벌림" type="range" min={0} max={160} step={.1} value={angle} onChange={e=>change(e.target.valueAsNumber)} />
      {angles.map(a=><button key={a} onClick={()=>change(a)}>{a===REST_ELEVATION?"원화 각도":`${a}°`}</button>)}
      <label><input type="checkbox" checked={overlay} onChange={e=>setOverlay(e.target.checked)} /> 축·경계 표본</label>
      <label><input type="checkbox" checked={zoom} onChange={e=>setZoom(e.target.checked)} /> 어깨 확대</label>
    </div>
    <div className={styles.comparison}>
      {VARIANTS.map(variant=>{
        const pose=contourPose(angle,variant),m=metrics(pose);
        return <section key={variant}><h2>{labels[variant]}</h2>
          <svg data-variant={variant} aria-label={`${labels[variant]} ${angle.toFixed(1)}도 단색 실루엣`} viewBox={zoom?"545 250 235 225":"495 95 365 475"}>
            <path d={contourPath(pose.curves)} fill="#59636b" />
            {overlay&&<g>
              {pose.curves.map((c,i)=><path key={i} d={`M ${c.map(p=>p.join(" ")).join(" L ")}`} fill="none" stroke="#ebaf4b" strokeWidth=".7" />)}
              {sampleCurves(pose.curves).map((p,i)=><circle key={i} cx={p[0]} cy={p[1]} r=".8" fill="#f4c771" />)}
              <path d={`M 512 346 L ${pose.shoulder.join(" ")} L ${pose.elbow.join(" ")}`} fill="none" stroke="#e6e7ff" strokeWidth="2" />
              {pose.widths.map(([a,b],i)=><path key={i} d={`M ${a.join(" ")} L ${b.join(" ")}`} stroke="#a6e4d8" strokeWidth="1" />)}
              <circle cx={pose.pit[0]} cy={pose.pit[1]} r="3" fill="#ffb56b"><title>겨드랑이 몸통 부착 경계</title></circle>
              <circle cx={pose.cap[0]} cy={pose.cap[1]} r="3" fill="#bcb1ff"><title>어깨 외곽 제어</title></circle>
            </g>}
          </svg>
          <p>교차 {m.crossings} · 안쪽 뿌리↔겨드랑이 {m.rootToPit.toFixed(1)} px</p>
          <small>팔 길이 {m.upperLength.toFixed(1)} px · 설계 단면폭 {m.widths.map(n=>n.toFixed(0)).join(" / ")} px</small>
        </section>;
      })}
    </div>
    <details open><summary>정지 자세 판정 기준</summary>
      <ul><li>0°·원화 각도·45°·90°·135°·160°를 같은 배율로 비교합니다.</li><li>어깨 외곽에 뿔·패임이 없고 위팔 안쪽이 옆구리 아래까지 늘어지지 않아야 합니다.</li><li>겨드랑이의 오목한 전환이 상부 흉곽 곁에서 끝나야 합니다. 긴 삼각 막이나 S자 흔들림은 실패입니다.</li><li>수치 방어선: 경계 자기교차 0, 위팔 길이 보존. 폭 61/58/50 px는 고정 설계값이며 자연스러움의 증거가 아닙니다.</li></ul>
    </details>
    <label><input type="checkbox" checked={gate} onChange={e=>{setGate(e.target.checked);setSweep(false);}} /> 정지 자세 검토 후 중간 각도·왕복 관찰 열기 (통과 기록으로 저장되지 않음)</label>
    <div className={styles.toolbar}><button disabled={!gate} onClick={()=>setSweep(!sweep)}>{sweep?"정지":"12초 왕복 및 프레임 측정"}</button>
      {[22.5,67.5,112.5,147.5].map(a=><button key={a} disabled={!gate} onClick={()=>change(a)}>{a}°</button>)}<output>{timing}</output></div>
    <p>rAF 간격은 브라우저 프레임 스케줄 관찰이며 입력→실제 화면 표시 지연 측정이 아닙니다. 정지 형태가 실패하면 왕복·의상 단계로 승격하지 않습니다.</p>
  </main>;
}
