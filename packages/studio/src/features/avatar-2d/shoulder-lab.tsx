"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { ArrowLeft, BookmarkPlus, Download, Pause, Play, RotateCcw, ScanLine } from "lucide-react";
import { Button } from "../../components/ui/button";
import { REST, length, sub, type Pose } from "./rig";
import { emptyReview, manualLeftShoulderPose, parseShoulderReview, restShoulderElevation, sweepElevation, type ShoulderReview } from "./shoulder-lab-model";
import type { PuppetScene } from "./puppet-scene";
import styles from "./shoulder-lab.module.css";

type ViewMode = "art" | "flat" | "mesh";
const STORAGE_KEY = "frameflow.shoulder-lab.left.v1";
const BASE_ANGLE = restShoulderElevation();
const presets = [{ label: "내림", angle: 0 }, { label: "기준", angle: BASE_ANGLE }, { label: "45°", angle: 45 }, { label: "수평", angle: 90 }, { label: "135°", angle: 135 }, { label: "160°", angle: 160 }];
const download = (blob: Blob, filename: string) => { const url = URL.createObjectURL(blob); const a = document.createElement("a"); a.href = url; a.download = filename; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1500); };

function JointOverlay({ pose, viewBox, show }: { pose: Pose; viewBox: string; show: boolean }) {
  if (!show) return null;
  const shoulder = pose.joints.leftShoulder, elbow = pose.joints.leftElbow, wrist = pose.joints.leftWrist;
  return <svg className={styles.overlay} viewBox={viewBox} aria-label="왼쪽 어깨 관절 축">
    <line x1={REST.chest[0]} y1={REST.chest[1]} x2={shoulder[0]} y2={shoulder[1]} stroke="#6b7164" strokeWidth={1.5} strokeDasharray="5 5" />
    <path d={`M ${shoulder.join(" ")} L ${elbow.join(" ")} L ${wrist.join(" ")}`} fill="none" stroke="#553eb0" strokeWidth={2} />
    <circle cx={shoulder[0]} cy={shoulder[1]} r={5} stroke="#553eb0" strokeWidth={2} fill="white"><title>팔 높이에 따라 함께 올라가는 왼쪽 어깨 축</title></circle>
    <circle cx={elbow[0]} cy={elbow[1]} r={3.5} stroke="#553eb0" strokeWidth={1.5} fill="white" />
    <circle cx={wrist[0]} cy={wrist[1]} r={3.5} stroke="#553eb0" strokeWidth={1.5} fill="white" />
  </svg>;
}

export function ShoulderLab() {
  const fullMount = useRef<HTMLDivElement>(null), closeMount = useRef<HTMLDivElement>(null);
  const scenes = useRef<PuppetScene[]>([]);
  const [ready, setReady] = useState(false), [status, setStatus] = useState("실험용 원화를 준비하고 있습니다.");
  const [degrees, setDegrees] = useState(BASE_ANGLE), [mode, setMode] = useState<ViewMode>("art"), [axes, setAxes] = useState(true), [sweep, setSweep] = useState(false);
  const [viewBoxes, setViewBoxes] = useState(["0 -170 1024 1770", "380 105 480 500"]);
  const [review, setReview] = useState<ShoulderReview>(emptyReview), [note, setNote] = useState("");
  const pose = useMemo(() => manualLeftShoulderPose(degrees), [degrees]);
  const poseRef = useRef(pose), modeRef = useRef<ViewMode>(mode);
  const angleRef = useRef(BASE_ANGLE);
  const upperLength = length(sub(pose.joints.leftElbow, pose.joints.leftShoulder));
  const upperRatio = upperLength / length(sub(REST.leftElbow, REST.leftShoulder));

  useEffect(() => {
    let active = true, resizeFrame = 0;
    const created: PuppetScene[] = [];
    let observer: ResizeObserver | null = null;
    import("./puppet-scene").then(async ({ PuppetScene }) => {
      if (!active || !fullMount.current || !closeMount.current) return;
      try { const saved = localStorage.getItem(STORAGE_KEY); if (saved) setReview(parseShoulderReview(JSON.parse(saved))); } catch { /* Invalid notes must not change the experiment. */ }
      const full = new PuppetScene(fullMount.current, REST); created.push(full);
      const close = new PuppetScene(closeMount.current, REST); created.push(close); scenes.current = created;
      for (const scene of created) { scene.connectedLeftShoulder = true; scene.lightMix = 0; scene.motionEffects = false; scene.groundShadow = false; scene.background = "#f0f0eb"; }
      full.setFraming(630, 715, 1770, 1100); close.setFraming(620, 355, 460);
      close.inspectionMode = modeRef.current;
      await Promise.all(created.map((scene) => scene.load("/avatars/cat-2d-v1/base.png")));
      if (!active) return;
      created.forEach((scene) => scene.render(poseRef.current, 0));
      setViewBoxes(created.map((scene) => scene.viewBox)); setReady(true);
      setStatus("피부 연결 보정 · 민소매 형태 유지가 적용되었습니다.");
      observer = new ResizeObserver(() => {
        cancelAnimationFrame(resizeFrame);
        resizeFrame = requestAnimationFrame(() => { if (active) setViewBoxes(created.map((scene) => scene.viewBox)); });
      });
      observer.observe(fullMount.current); observer.observe(closeMount.current);
    }).catch((error) => { if (active) { created.forEach((scene) => scene.dispose()); scenes.current = []; setStatus(error instanceof Error ? error.message : "원화를 불러오지 못했습니다."); } });
    return () => { active = false; observer?.disconnect(); cancelAnimationFrame(resizeFrame); created.forEach((scene) => scene.dispose()); scenes.current = []; };
  }, []);

  useEffect(() => {
    poseRef.current = pose; modeRef.current = mode; angleRef.current = degrees;
    scenes.current.forEach((scene, i) => { scene.inspectionMode = i === 0 ? "art" : mode; scene.render(pose, 0); });
  }, [pose, mode, ready, degrees]);

  useEffect(() => {
    if (!sweep || !ready) return;
    let frame = 0, start: number | null = null;
    const initial = angleRef.current;
    const tick = (now: number) => {
      start ??= now; setDegrees(sweepElevation((now - start) / 1000, initial)); frame = requestAnimationFrame(tick);
    };
    const hidden = () => { if (document.hidden) setSweep(false); };
    document.addEventListener("visibilitychange", hidden); frame = requestAnimationFrame(tick);
    return () => { cancelAnimationFrame(frame); document.removeEventListener("visibilitychange", hidden); };
  }, [sweep, ready]);

  const setAngle = (value: number) => { if (!Number.isFinite(value)) return; setSweep(false); setDegrees(Math.max(0, Math.min(160, value))); };
  const persist = (next: ShoulderReview) => {
    setReview(next);
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(next)); setStatus("이 브라우저에 각도와 메모를 기록했습니다."); }
    catch { setStatus("브라우저 저장이 어려워 화면에만 기록했습니다. 기록 내보내기를 이용하세요."); }
  };
  const record = () => {
    setSweep(false);
    if (review.observations.length >= 100) { setStatus("기록이 100개입니다. 기록을 내보낸 뒤 필요한 항목을 정리하세요."); return; }
    const item = { id: crypto.randomUUID(), angle: Math.round(degrees * 10) / 10, note: note.trim() || "이 각도에서 연결과 실루엣 확인", createdAt: new Date().toISOString() };
    persist({ ...review, observations: [...review.observations, item] }); setNote("");
  };

  return <div className={styles.lab}>
    <header className={styles.header}><div><Link href="/live-avatar/2d"><ArrowLeft size={14} /> 아바타 스튜디오</Link><span className={styles.eyebrow}>JOINT STUDY / 01</span><h1>왼쪽 어깨 수동 실험</h1><p>캐릭터의 왼쪽, 화면 오른쪽입니다. 먼저 팔을 옆으로 올리는 동작 하나만 확인합니다.</p></div><span className={styles.scope}>한 관절 · 한 축</span></header>
    <div className={styles.layout}>
      <section className={styles.fullPanel} aria-label="전체 자세 비교"><header><strong>전체 자세</strong><span>원화 기준</span></header><div className={styles.fullStage}><div ref={fullMount} className={styles.canvas} /><JointOverlay pose={pose} viewBox={viewBoxes[0]} show={axes} /></div><footer>오른팔 · 머리 · 하체 고정 / 왼쪽 상체 연결 변형</footer></section>
      <section className={styles.closePanel} aria-label="왼쪽 어깨 확대"><header><strong>왼쪽 어깨 확대</strong><div className={styles.modeTabs}>{([["art", "원화"], ["flat", "단색"], ["mesh", "메쉬"]] as const).map(([key, label]) => <button type="button" key={key} aria-pressed={mode === key} className={mode === key ? styles.active : ""} onClick={() => setMode(key)}>{label}</button>)}</div></header><div className={styles.closeStage}><div ref={closeMount} className={styles.canvas} /><JointOverlay pose={pose} viewBox={viewBoxes[1]} show={axes} />{!ready && <div className={styles.loading}>{status}</div>}<div className={styles.angleBadge}>{degrees.toFixed(1)}<small>°</small></div></div><footer><label><input type="checkbox" checked={axes} onChange={(e) => setAxes(e.target.checked)} /><ScanLine size={14} /> 관절 축 표시</label><button type="button" disabled={!ready} onClick={() => scenes.current[1]?.canvas.toBlob((blob) => blob && download(blob, `left-shoulder-${degrees.toFixed(1)}deg.png`))}><Download size={14} /> 현재 각도 이미지</button></footer></section>
      <aside className={styles.controls}>
        <section><span className={styles.step}>01 / INPUT</span><h2>어깨 벌림</h2><label className={styles.numberLabel}><span>팔을 내리면 0°, 옆으로 들면 90°</span><input aria-label="왼쪽 어깨 각도 숫자 입력" type="number" min={0} max={160} step={.1} value={Math.round(degrees * 10) / 10} disabled={!ready} onChange={(e) => setAngle(e.target.valueAsNumber)} /></label><input className={styles.angleSlider} aria-label="왼쪽 어깨 벌림 각도" type="range" min={0} max={160} step={.1} value={degrees} disabled={!ready} onChange={(e) => setAngle(Number(e.target.value))} /><div className={styles.scale}><span>0°</span><span>90°</span><span>160°</span></div><div className={styles.presets}>{presets.map((p) => <button type="button" key={p.label} disabled={!ready} className={Math.abs(degrees - p.angle) < .1 ? styles.active : ""} onClick={() => setAngle(p.angle)}>{p.label}</button>)}</div><div className={styles.actions}><Button variant="outline" disabled={!ready} onClick={() => setSweep(!sweep)}>{sweep ? <Pause size={15} /> : <Play size={15} />}{sweep ? "스윕 정지" : "천천히 왕복"}</Button><Button variant="ghost" disabled={!ready} onClick={() => setAngle(BASE_ANGLE)}><RotateCcw size={14} /> 기준 자세</Button></div><p className={styles.hint}>팔꿈치와 손목의 상대 각도는 고정됩니다. 팔 높이에 따라 어깨가 올라가고, 겨드랑이 피부가 연결됩니다. 옷의 목선과 가슴 형태는 유지됩니다.</p></section>
        <section><span className={styles.step}>02 / ISOLATION</span><h2>이번 실험의 고정 조건</h2><dl className={styles.conditions}><div><dt>입력</dt><dd>수동 각도</dd></div><div><dt>연결 부위</dt><dd>왼쪽 어깨·겨드랑이</dd></div><div><dt>동적 조명·흔들림</dt><dd>꺼짐</dd></div><div><dt>위팔 길이</dt><dd>{(upperRatio * 100).toFixed(1)}%</dd></div></dl><p className={styles.hint}>단색 보기는 원화의 음영을 숨깁니다. 길이가 같아도 연결이나 두께는 어색할 수 있으니 확대 화면을 함께 확인하세요.</p></section>
        <section><span className={styles.step}>03 / REVIEW</span><h2>어색한 각도 기록</h2><p className={styles.hint}>틈 · 피부 돌출 · 두께 변화 · 갑작스러운 꺾임을 확인합니다.</p><textarea aria-label="어깨 문제 메모" placeholder="예: 90°에서 겨드랑이 선이 꺾임" value={note} maxLength={1000} onChange={(e) => setNote(e.target.value)} /><Button disabled={!ready || review.observations.length >= 100} onClick={record}><BookmarkPlus size={15} /> {degrees.toFixed(1)}° 기록</Button><div className={styles.notes}>{review.observations.map((item) => <div key={item.id}><button type="button" onClick={() => setAngle(item.angle)}><strong>{item.angle}°</strong><span>{item.note}</span></button><button type="button" aria-label={`${item.angle}도 기록 삭제`} onClick={() => persist({ ...review, observations: review.observations.filter((v) => v.id !== item.id) })}>×</button></div>)}</div>{review.observations.length > 0 && <button type="button" className={styles.export} onClick={() => download(new Blob([JSON.stringify(review, null, 2)], { type: "application/json" }), "left-shoulder-review.json")}><Download size={13} /> 기록 내보내기 ({review.observations.length})</button>}</section>
        <p className={styles.status} role="status">{status}</p>
      </aside>
    </div>
  </div>;
}
