"use client";
import { useState } from "react";
import Link from "next/link";
import { contourPath, metrics } from "./shoulder-contour-e09";
import { occlusionSurfaces, paintOrder, type Surface } from "./shoulder-occlusion-e14";
import styles from "./shoulder-contour-study.module.css";
export function ShoulderOcclusionStudy(){
 const [zoom,setZoom]=useState(true),[ownership,setOwnership]=useState(false),[outline,setOutline]=useState(false);
 const s=occlusionSurfaces();
 const views=[{id:"original",title:"A · 기존 단일 경계"},{id:"arm",title:"B · 고정 분할 / 팔 앞"},{id:"torso",title:"C · 고정 분할 / 몸통 앞"}] as const;
 return <main className={styles.study}>
 <Link href="/live-avatar/2d/shoulder/e13">← E13 160° 연구</Link>
 <h1>E14 · 0° 겹침과 앞뒤 표시 검사</h1>
 <p>팔 내림 0° 고정. A는 기존 비교군, B/C는 같은 팔·몸통 영역의 그리기 순서만 다릅니다.</p>
 <p className={styles.notice}>E14 검사 결과: 앞뒤 순서를 바꿔도 0° 틈이 남습니다. 틈은 두 표면 모두 덮지 않는 영역이며 피부 연결 실패로 기록했습니다.</p>
 <div className={styles.toolbar}>
 <label><input type="checkbox" checked={zoom} onChange={e=>setZoom(e.target.checked)}/> 겨드랑이 확대</label>
 <label><input type="checkbox" checked={ownership} onChange={e=>setOwnership(e.target.checked)}/> 표면 소유권 색 (진단용)</label>
 <label><input type="checkbox" checked={outline} onChange={e=>setOutline(e.target.checked)}/> 가려진 경계와 내부 절단선</label>
 </div>
 <div className={styles.comparison}>{views.map(v=><section key={v.id}><h2>{v.title}</h2>
 <svg data-e14={v.id} aria-label={`${v.id} 0도 비교`} viewBox={zoom?"570 350 80 110":"495 290 190 270"}>
 {v.id==="original"?<path d={contourPath(s.pose.curves)} fill="#59636b"/>:paintOrder(v.id).map(k=><path key={k} d={contourPath(s[k])} fill={ownership?(k==="arm"?"#6986aa":"#bc9873"):"#59636b"}/>)}
 {outline&&<g fill="none" strokeWidth=".5">
 {(["torso","arm"] as Surface[]).map(k=><path key={k} d={contourPath(s[k])} stroke={k==="arm"?"#335cb0":"#c77b22"}/>)}
 <path d={`M ${s.pose.cap.join(" ")} L ${s.pose.pit.join(" ")}`} stroke="#cd3a64" strokeDasharray="2 2"/>
 </g>}
 </svg><p>{v.id==="original"?`기존 경계 교차 ${metrics(s.pose).crossings}`:"단색 합집합은 앞뒤 순서와 무관"}</p></section>)}</div>
 <details open><summary>판정 기준</summary><ul><li>B/C의 곡선 좌표와 경계 표본은 같아야 합니다.</li><li>겹친 영역의 소유권은 바뀌어도 단색 외곽선은 같아야 합니다.</li><li>A와 B의 차이는 분할/채움 차이이며 앞뒤 순서의 효과로 해석하지 않습니다.</li><li>겨드랑이 틈·돌출·두께를 검사하고, 가려진 잘못된 연결은 실패로 남깁니다.</li></ul></details>
 <p>정지 피부 연결이 확인되기 전에는 인접 낮은 각도·왕복으로 진행하지 않습니다. 옷·음영·물리 없음.</p>
 </main>;
}
