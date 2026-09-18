"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { Camera, Check, Download, Move, Pause, Play, RotateCcw, Save, Sun, Upload, Video, WandSparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { API_BASE } from "@/lib/api";
import { CONNECTIONS, JOINTS, LABELS, clamp, frameAt, freshProfile, hipOrigin, neutralPose, parseProfile, smoothPose, solvePose, type Joint, type Performance, type Point, type Pose, type RigProfile } from "./rig";
import type { PuppetScene } from "./puppet-scene";
import { BodyTrackingSession } from "./tracking-session";
import { ExpressionPanel } from "./expression-panel";
import type { ExpressionImage, ExpressionLibrary } from "./expression-library";
import { useFaceRigController } from "./face-rig-controller";
import { FaceRigPanel } from "./face-rig-panel";
import { WebcamFaceOverlay } from "./webcam-face-overlay";
import {RIG_HEAD_IMAGE} from "./avatar-artwork";
import { CameraSession } from "../live-avatar/camera-session";
import styles from "./avatar-studio.module.css";

const assetRoot = "/avatars/cat-2d-v1";
const referenceUrl = `${API_BASE}/artifacts/art_d78356242bc4494495/content`;
const storageKey = "frameflow.puppet2d.cat-2d-v1";
const download = (blob: Blob, name: string) => { const url = URL.createObjectURL(blob); const a = document.createElement("a"); a.href = url; a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(url), 2000); };
type Mode = "reference" | "neutral" | "tracking";
const DEFAULT_LIGHTING = { direction: -130, height: 1.2, strength: 1, mix: .38, smoothing: .08, background: "#ebe9e5" };

export function AvatarStudio({ faceFirst = false }: { faceFirst?: boolean }) {
  const mount = useRef<HTMLDivElement>(null), input = useRef<HTMLVideoElement>(null), reference = useRef<HTMLVideoElement>(null);
  const scene = useRef<PuppetScene | null>(null), session = useRef<BodyTrackingSession | null>(null);
  const faceSession = useRef<CameraSession|null>(null);
  const performance = useRef<Performance | null>(null), profileRef = useRef(freshProfile());
  const current = useRef<Pose>(neutralPose()), tracked = useRef<Pose>(neutralPose()), origin = useRef<Point | undefined>(undefined);
  const modeRef = useRef<Mode>(faceFirst ? "neutral" : "reference"), playingRef = useRef(!faceFirst), rigRef = useRef(false), timeRef = useRef(0), lastTracked = useRef(0);
  const options = useRef(DEFAULT_LIGHTING);
  const recorder = useRef<MediaRecorder | null>(null), recordingStream = useRef<MediaStream | null>(null);
  const [cameraAspect,setCameraAspect]=useState(4/3);
  const [ready, setReady] = useState(false), [error, setError] = useState("");
  const [profile, setProfile] = useState<RigProfile>(freshProfile), [mode, setMode] = useState<Mode>(faceFirst ? "neutral" : "reference"), [playing, setPlaying] = useState(!faceFirst);
  const [rigEditing, setRigEditing] = useState(false), [showRig, setShowRig] = useState(false), [activeJoint, setActiveJoint] = useState<Joint | null>(null);
  const [pose, setPose] = useState<Pose>(neutralPose), [viewBox, setViewBox] = useState("0 -70 1024 1650"), [time, setTime] = useState(0), [duration, setDuration] = useState(35.6);
  const [status, setStatus] = useState("캐릭터와 참고 동작을 준비하고 있습니다."), [running, setRunning] = useState(false), [starting, setStarting] = useState(false), [recording, setRecording] = useState(false);
  const [lighting, setLighting] = useState(DEFAULT_LIGHTING), [test, setTest] = useState(""), [blink, setBlink] = useState(0), [mouth, setMouth] = useState(0);
  const faceTest = useRef({ blink: 0, mouth: 0 });
  const face = useFaceRigController(scene,ready);
  const faceTick = face.tick, faceReceive = face.receive, resetFaceCapture = face.resetCapture, facePreview = face.preview;
  const [incomingLibrary,setIncomingLibrary] = useState<ExpressionLibrary|null>(null);
  const [artExpression, setArtExpression] = useState(false);
  const applyExpression = useCallback(async (entry: ExpressionImage, strength: number, duration: number) => { setArtExpression(entry.id!=="neutral" && strength>0); await facePreview(entry,strength,duration); }, [facePreview]);
  const focusExpression = useCallback((enabled: boolean) => { scene.current?.setFraming(512,enabled?205:755,enabled?440:1650,enabled?640:0); }, []);

  useEffect(() => {
    if (!mount.current) return;
    let active = true, raf = 0, localScene: PuppetScene | null = null;
    let last = 0, lastUi = 0;
    Promise.all([import("./puppet-scene"), fetch(`${assetRoot}/reference-motion.json`).then(async (r) => { if (!r.ok) throw new Error("참고 동작을 불러오지 못했습니다."); return await r.json() as Performance; })]).then(async ([module, motion]) => {
      if (!active || !mount.current) return;
      let initial = freshProfile();
      try { const saved = localStorage.getItem(storageKey); if (saved) initial = parseProfile(JSON.parse(saved)); } catch { /* Keep the checked-in rig if a local edit is invalid. */ }
      profileRef.current = initial; setProfile(initial); performance.current = motion; setDuration(motion.duration);
      localScene = new module.PuppetScene(mount.current, initial.anchors); scene.current = localScene;
      await localScene.load(`${assetRoot}/base.png`,RIG_HEAD_IMAGE);
      if (!active) return;
      if (faceFirst) localScene.setFraming(512,205,440,640);
      setReady(true); setStatus(faceFirst ? "웹캠 얼굴 연결을 누르고 무표정을 보정하세요." : "참고 영상의 전신 동작을 재생합니다.");
      const tick = (now: number) => {
        if (!active || !localScene) return;
        const dt = last ? Math.min(.1, (now - last) / 1000) : 1 / 60; last = now;
        const rest = profileRef.current.anchors;
        let target = neutralPose(rest);
        if (!rigRef.current && modeRef.current === "reference") {
          if (playingRef.current) timeRef.current = (timeRef.current + dt) % motion.duration;
          target = solvePose(frameAt(motion, timeRef.current), rest, motion.width / motion.height, current.current, hipOrigin(motion.frames[0], motion.width / motion.height));
        } else if (!rigRef.current && modeRef.current === "tracking" && now - lastTracked.current < 700) target = tracked.current;
        else if (!rigRef.current) { target.blink = faceTest.current.blink; target.mouth = faceTest.current.mouth; }
        current.current = rigRef.current ? neutralPose(rest) : smoothPose(current.current, target, dt, options.current.smoothing);
        localScene.setLight(options.current.direction, options.current.height); localScene.lightMix = options.current.mix; localScene.lightStrength = options.current.strength; localScene.background = options.current.background;
        faceTick(now,dt);
        localScene.render(current.current, timeRef.current);
        if (now - lastUi > 66) { setPose(current.current); setTime(timeRef.current); setViewBox(localScene.viewBox); lastUi = now; }
        if (reference.current && modeRef.current === "reference") {
          const v = reference.current;
          if (Math.abs(v.currentTime - timeRef.current) > .15) v.currentTime = timeRef.current;
          if (playingRef.current && v.paused) void v.play().catch(() => {});
          if (!playingRef.current && !v.paused) v.pause();
        }
        raf = requestAnimationFrame(tick);
      };
      raf = requestAnimationFrame(tick);
    }).catch((e) => { if (active) { setError(e instanceof Error ? e.message : "아바타 준비 실패"); setStatus("아바타를 불러오지 못했습니다."); } });
    return () => { active = false; cancelAnimationFrame(raf); localScene?.dispose(); scene.current = null; if (recorder.current?.state === "recording") recorder.current.stop(); recordingStream.current?.getTracks().forEach((t) => t.stop()); };
  }, [faceTick, faceFirst]);

  useEffect(() => {
    if (!input.current) return;
    const s = new BodyTrackingSession(input.current, (f, aspect) => {
      faceReceive(f,window.performance.now());
      if (f.pose.length < 33 || ![11, 12, 23, 24].every((i) => f.pose[i][3] >= .35)) return;
      origin.current ??= hipOrigin(f, aspect);
      tracked.current = solvePose(f, profileRef.current.anchors, aspect, tracked.current, origin.current);
      lastTracked.current = window.performance.now();
    }, (text, active) => { setStatus(text); setRunning(active); setStarting(!active && text.endsWith("…")); if(!active&&!text.endsWith("…"))resetFaceCapture(); });
    session.current = s;
    const f = new CameraSession(input.current,frame=>faceReceive({time:frame.timestamp/1000,pose:[],expressions:frame.values,faceDetected:frame.detected,faceLandmarks:frame.landmarks?.map(p=>[p[0],p[1],p[2],1])},window.performance.now()),(text,active)=>{setStatus(text);setRunning(active);setStarting(!active&&text.endsWith('…'));if(!active&&!text.endsWith('…'))resetFaceCapture();});
    faceSession.current=f;
    const hidden = () => { if (document.hidden) { s.stop(); f.stop(); playingRef.current = false; setPlaying(false); if (recorder.current?.state === "recording") recorder.current.stop(); } };
    document.addEventListener("visibilitychange", hidden);
    return () => { document.removeEventListener("visibilitychange", hidden); s.stop(false); f.stop(false); session.current = null; faceSession.current=null; };
  }, [faceReceive, resetFaceCapture]);

  const changeMode = (next: Mode) => {
    resetFaceCapture(); session.current?.stop(false); faceSession.current?.stop(false); setRunning(false); setStarting(false); setTest(""); modeRef.current = next; setMode(next);
    rigRef.current = false; setRigEditing(false);
    if (next === "reference") { playingRef.current = true; setPlaying(true); setStatus("참고 영상의 전신 동작을 재생합니다."); }
    else { reference.current?.pause(); setStatus("준비 자세에서 리그와 표정을 확인하세요."); }
  };
  const start = (file?: File | string) => { face.setMode("live"); changeMode("tracking"); origin.current = undefined; lastTracked.current = 0; setStarting(true); void session.current?.start(file); };
  const startFace = (file?: File) => { face.setMode('live');changeMode('tracking');lastTracked.current=0;setStarting(true);void faceSession.current?.start(file); };
  const edit = () => { changeMode("neutral"); rigRef.current = !rigEditing; setRigEditing(!rigEditing); setShowRig(!rigEditing); setStatus(!rigEditing ? "관절점을 드래그해 위치를 조정하세요. 캐릭터 기준 좌우입니다." : "리그 편집을 마쳤습니다."); };
  const updateProfile = (next: RigProfile) => { profileRef.current = next; setProfile(next); scene.current?.setRest(next.anchors); current.current = neutralPose(next.anchors); };
  const save = () => { try { const valid = parseProfile(profileRef.current); localStorage.setItem(storageKey, JSON.stringify(valid)); setStatus("이 브라우저에 2D 리그를 저장했습니다."); } catch (e) { setStatus(e instanceof Error ? e.message : "리그 저장 실패"); } };
  const scrub = (t: number) => { timeRef.current = t; setTime(t); current.current = neutralPose(profileRef.current.anchors); };
  const light = (key: keyof typeof lighting, value: number | string) => { const next = { ...options.current, [key]: value }; options.current = next; setLighting(next); };
  const record = () => {
    if (recording) { recorder.current?.stop(); return; }
    if (!scene.current || typeof MediaRecorder === "undefined" || !scene.current.canvas.captureStream) { setStatus("이 브라우저는 아바타 녹화를 지원하지 않습니다."); return; }
    try {
      const stream = scene.current.canvas.captureStream(30); recordingStream.current = stream;
      const mimeType = ["video/webm;codecs=vp9", "video/webm;codecs=vp8", "video/mp4"].find((m) => MediaRecorder.isTypeSupported(m));
      if (!mimeType) { stream.getTracks().forEach((t) => t.stop()); throw new Error("지원하는 녹화 형식을 찾지 못했습니다."); }
      const chunks: Blob[] = [], r = new MediaRecorder(stream, { mimeType, videoBitsPerSecond: 6_000_000 }); recorder.current = r;
      r.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
      r.onstop = () => { stream.getTracks().forEach((t) => t.stop()); recordingStream.current = null; setRecording(false); if (chunks.length) { download(new Blob(chunks, { type: mimeType }), `cat-avatar-2d.${mimeType.includes("mp4") ? "mp4" : "webm"}`); setStatus("아바타 영상을 저장했습니다. 카메라 원본은 포함되지 않습니다."); } };
      r.start(1000); setRecording(true); setStatus("아바타 화면 녹화 중 · 다시 누르면 저장합니다.");
    } catch (e) { setStatus(e instanceof Error ? e.message : "녹화를 시작하지 못했습니다."); }
  };
  const example = (name: string, at: number) => { changeMode("reference"); playingRef.current = false; setPlaying(false); scrub(at); setTest(name); };

  const facePanel = <FaceRigPanel face={face} initialCloseup={faceFirst} cameraStatus={status} ready={ready} running={running} starting={starting} start={startFace} stop={() => changeMode("neutral")} focus={focusExpression} importLibrary={(library) => { setIncomingLibrary(library);face.setLibrary(library); }} />;

  return <div className={styles.studio} aria-label="2D 아바타 작업영역" tabIndex={0}>
    <header className={styles.header}><div><span className={styles.eyebrow}>ILLUSTRATED AVATAR</span><h1>{faceFirst ? "내 표정을 따라 움직이는 2D 얼굴." : "그림이 나를 따라 움직이도록."}</h1><p>{faceFirst ? "웹캠 연결 → 무표정 보정 → 눈·입·눈썹·시선 리그 조정" : "원화 기반 얼굴 리그 · 웹캠 표정 · 전신 동작"}</p></div><a href="#avatar-face-rig">얼굴 리그로 이동 ↓</a><Link href="/live-avatar">다른 아바타 선택 ↗</Link></header>
    <div className={styles.workspace}>
      <section className={styles.preview}>
        <div className={styles.previewTop}><span><i className={ready ? styles.dot : ""} />{rigEditing ? "리그 편집" : mode === "tracking" ? "내 움직임" : mode === "reference" ? "참고 동작" : "준비 자세"}</span><div><button type="button" className={showRig ? styles.selected : ""} onClick={() => setShowRig(!showRig)}><Move size={14} /> 관절 표시</button><button type="button" disabled={!ready} onClick={() => { scene.current?.canvas.toBlob((b) => b && download(b, "avatar-frame.png")); }}><Download size={14} /> 이미지</button></div></div>
        <div className={styles.stageWrap}>
          <div className={styles.stage} ref={mount} />
          {faceFirst && <div className={running ? `${styles.faceCamera} ${face.showMesh ? styles.faceCameraCompare : ""}` : styles.hidden}><div className={styles.cameraImage}><video ref={input} muted playsInline onLoadedMetadata={e=>setCameraAspect(e.currentTarget.videoWidth/Math.max(1,e.currentTarget.videoHeight))} aria-label="내 얼굴 추적 미리보기" />{face.showMesh && <WebcamFaceOverlay points={face.telemetry.landmarks} aspect={cameraAspect} />}</div><span>{face.showMesh ? "내 얼굴 기준점 · 아바타와 좌우 맞춤" : "내 얼굴 · 로컬 추적"}</span></div>}
          {(showRig || rigEditing) && <svg className={styles.rig} viewBox={viewBox} aria-label="2D 아바타 관절 편집" onPointerMove={(e) => {
            if (!rigEditing || !activeJoint || !scene.current) return;
            const p = scene.current.imagePoint(e.clientX, e.clientY); updateProfile({ ...profileRef.current, anchors: { ...profileRef.current.anchors, [activeJoint]: p } });
          }} onPointerUp={() => setActiveJoint(null)} onPointerCancel={() => setActiveJoint(null)}>
            {CONNECTIONS.map(([a, b]) => <line key={`${a}-${b}`} x1={pose.joints[a][0]} y1={pose.joints[a][1]} x2={pose.joints[b][0]} y2={pose.joints[b][1]} stroke="#7866ef" strokeWidth={3} opacity={.65} />)}
            {JOINTS.map((key) => <g key={key}><circle cx={pose.joints[key][0]} cy={pose.joints[key][1]} r={rigEditing ? 11 : 6} fill={activeJoint === key ? "#ffc66e" : "#fff"} stroke="#7866ef" strokeWidth={3} className={rigEditing ? styles.handle : ""} onPointerDown={(e) => { if (!rigEditing) return; e.preventDefault(); e.currentTarget.setPointerCapture(e.pointerId); setActiveJoint(key); }}><title>{LABELS[key]}</title></circle>{activeJoint === key && <text x={pose.joints[key][0] + 18} y={pose.joints[key][1] - 15} fontSize={22} fill="#493aaa">{LABELS[key]}</text>}</g>)}
          </svg>}
          {!ready && <div className={styles.loading}>{error || "원화와 리그를 준비하는 중…"}</div>}
          {recording && <div className={styles.recordBadge}><i /> 녹화 중</div>}
          <div className={styles.stageLabel}><span>CAT / 01</span><span>2D ART · LIVE MOTION</span></div>
        </div>
        <div className={styles.transport}><button type="button" aria-label={playing ? "동작 일시정지" : "동작 재생"} disabled={mode !== "reference" || rigEditing} onClick={() => { playingRef.current = !playing; setPlaying(!playing); }}>{playing && mode === "reference" ? <Pause size={18} /> : <Play size={18} />}</button><span>{time.toFixed(1)}s</span><input aria-label="참고 동작 재생 위치" type="range" min={0} max={duration - .05} step={.04} value={time} disabled={mode !== "reference" || rigEditing} onChange={(e) => scrub(Number(e.target.value))} /><span>{duration.toFixed(1)}s</span><button type="button" disabled={!ready} onClick={() => scrub(0)} aria-label="처음으로"><RotateCcw size={16} /></button></div>
      </section>
      <aside className={styles.controls} aria-label="2D 아바타 설정" tabIndex={0}>
        {faceFirst && facePanel}
        <section><div className={styles.sectionTitle}><span>01</span><h2>움직임 연결</h2></div><div className={styles.inputTabs}><button type="button" className={mode === "reference" ? styles.selected : ""} onClick={() => changeMode("reference")}><Play size={15} /> 참고 동작</button><button type="button" className={mode === "neutral" ? styles.selected : ""} onClick={() => changeMode("neutral")}><WandSparkles size={15} /> 준비 자세</button></div>
          <div className={styles.reference}><video ref={reference} src={referenceUrl} muted playsInline loop preload="metadata" /><div><strong>스타일 & 동작 레퍼런스</strong><p>같은 동작을 새 캐릭터에 적용합니다.</p><button type="button" onClick={() => start(referenceUrl)} disabled={!ready || starting}>영상에서 실시간 추적 ↗</button></div></div>
          <div className={styles.inputActions}><Button onClick={() => start()} disabled={!ready || starting || running}><Camera size={15} />{starting ? "연결 중…" : "웹캠으로 움직이기"}</Button><label className={styles.fileButton}><Upload size={15} /> 동작 영상 불러오기<input aria-label="동작 영상 불러오기" type="file" accept="video/*" disabled={!ready || starting} onChange={(e) => { const file = e.target.files?.[0]; e.target.value = ""; if (file) start(file); }} /></label></div>
          <div className={mode === "tracking" ? styles.tracking : styles.hidden}>{!faceFirst && <div className={styles.cameraImage}><video ref={input} muted playsInline onLoadedMetadata={e=>setCameraAspect(e.currentTarget.videoWidth/Math.max(1,e.currentTarget.videoHeight))} />{face.showMesh && <WebcamFaceOverlay points={face.telemetry.landmarks} aspect={cameraAspect} />}</div>}<div><Button variant="outline" onClick={() => { origin.current = undefined; setStatus("현재 위치를 중심으로 맞춥니다."); }}>중심 맞추기</Button><Button variant="outline" onClick={() => { session.current?.stop(); changeMode("neutral"); }}>종료</Button></div></div>
          <p className={styles.help}>얼굴만 보여도 얼굴 리그를 추적합니다. 몸 동작도 연결하려면 전신이 화면에 들어오게 서 주세요. 영상은 브라우저 안에서 처리합니다.</p>
        </section>
        <section><div className={styles.sectionTitle}><span>02</span><h2>리그 확인</h2><button type="button" disabled={!ready} onClick={edit}>{rigEditing ? <><Check size={14} /> 편집 완료</> : <><Move size={14} /> 관절 수정</>}</button></div>
          <Link className={styles.labLink} href="/live-avatar/2d/shoulder">왼쪽 어깨만 수동으로 테스트 ↗</Link>
          <div className={styles.poseTests}>{[["팔 교차", 21.8], ["팔 올리기", 6.2], ["옆으로 이동", 11.3]].map(([name, at]) => <button type="button" key={name} className={test === name ? styles.selected : ""} onClick={() => example(String(name), Number(at))}>{name}</button>)}</div>
          {rigEditing && <p className={styles.help}>그림 위 관절점을 드래그하세요. 어깨·팔꿈치·손목을 차례로 맞추면 팔 길이가 정해집니다.</p>}
          <div className={styles.row}><button type="button" onClick={save}><Save size={14} /> 리그 저장</button><button type="button" onClick={() => { updateProfile(freshProfile()); setStatus("기본 리그로 복원했습니다. 저장하면 유지됩니다."); }}><RotateCcw size={14} /> 초기화</button><button type="button" onClick={() => download(new Blob([JSON.stringify(profile, null, 2)], { type: "application/json" }), "cat-2d-rig.json")}><Download size={14} /> 내보내기</button></div>
          <label className={styles.importRig}>리그 파일 불러오기<input aria-label="2D 리그 파일 불러오기" type="file" accept=".json" onChange={async (e) => { const file = e.target.files?.[0]; e.target.value = ""; if (!file) return; try { if (file.size > 30000) throw new Error("리그 파일이 너무 큽니다."); const imported = parseProfile(JSON.parse(await file.text())); changeMode("neutral"); updateProfile(imported); setStatus("리그 파일을 불러왔습니다. 동작 확인 후 저장하세요."); } catch (error) { setStatus(error instanceof Error ? error.message : "리그를 불러오지 못했습니다."); } }} /></label>
          <label className={styles.slider}>떨림 완화 <span>{Math.round(lighting.smoothing * 1000)} ms</span><input type="range" aria-label="떨림 완화" min={.02} max={.25} step={.01} value={lighting.smoothing} onChange={(e) => light("smoothing", Number(e.target.value))} /></label>
        </section>
        <section><div className={styles.sectionTitle}><span>03</span><h2>빛과 그림자</h2><Sun size={17} /></div><label className={styles.slider}>빛의 방향 <span>{lighting.direction}°</span><input aria-label="빛의 방향" type="range" min={-180} max={180} value={lighting.direction} onChange={(e) => light("direction", Number(e.target.value))} /></label><div className={styles.twoColumns}><label className={styles.slider}>빛의 세기<input aria-label="빛의 세기" type="range" min={.3} max={1.8} step={.05} value={lighting.strength} onChange={(e) => light("strength", Number(e.target.value))} /></label><label className={styles.slider}>음영 깊이<input aria-label="음영 깊이" type="range" min={0} max={1} step={.05} value={lighting.mix} onChange={(e) => light("mix", Number(e.target.value))} /></label></div><div className={styles.swatches}>{["#ebe9e5", "#dfe8e2", "#e7e3ef", "#26282e"].map((color) => <button type="button" aria-label={`배경 ${color}`} style={{ background: color }} className={lighting.background === color ? styles.activeSwatch : ""} key={color} onClick={() => light("background", color)} />)}<small>스튜디오 배경</small></div></section>
        {!faceFirst && facePanel}
        <details className={styles.faceMaterials}><summary>표정 제작 자료 관리</summary><ExpressionPanel ready={ready} apply={applyExpression} focus={focusExpression} onLibraryChange={face.setLibrary} incomingLibrary={incomingLibrary} rigAuthoring /></details>
        <section><div className={styles.sectionTitle}><span>05</span><h2>기본 표정과 내보내기</h2></div><div className={styles.twoColumns}><label className={styles.slider}>눈 감기<input aria-label="눈 감기" disabled={face.mode!=="reference" || artExpression} type="range" min={0} max={1} step={.05} value={blink} onChange={(e) => { changeMode("neutral"); const value = clamp(Number(e.target.value), 0, 1); setBlink(value); faceTest.current.blink = value; }} /></label><label className={styles.slider}>입 벌리기<input aria-label="입 벌리기" disabled={face.mode!=="reference" || artExpression} type="range" min={0} max={1} step={.05} value={mouth} onChange={(e) => { changeMode("neutral"); const value = clamp(Number(e.target.value), 0, 1); setMouth(value); faceTest.current.mouth = value; }} /></label></div><Button variant={recording ? "danger" : "outline"} className={styles.recordButton} disabled={!ready} onClick={record}><Video size={16} />{recording ? "녹화 종료 · 영상 저장" : "아바타 영상 녹화"}</Button></section>
        <div className={styles.status} role="status">{error || status}</div>
      </aside>
    </div>
  </div>;
}
