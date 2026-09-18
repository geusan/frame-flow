"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { Camera, CameraOff, Crosshair, Download, RotateCcw, Save, ScanFace } from "lucide-react";
import { API_BASE, frameflowApi, type ArtifactDetail, type ArtifactListItem } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { CameraSession } from "./camera-session";
import type { AvatarScene } from "./avatar-scene";
import { ANCHOR_LABELS, EXPRESSION_CHANNELS, defaultExpressions, GAZE_CHANNELS, GAZE_LABELS, defaultGaze, estimateGaze, calibratedGaze, meanGaze, neutralGaze, calibratedValues, meanBaseline, neutralFace, parseFaceProfile, type Gaze, type AnchorName, type FaceFrame, type FaceProfile, type FaceValues, type FaceChannel } from "./face-state";
import styles from "./live-avatar.module.css";
import { ExpressionControls } from "./expression-controls";
import { findMorphMapping } from "./morph-binding";
import catAvatarPreset from "./presets/cat-avatar-gaze.v2.json";

const storageKey = (sha: string) => `frameflow.avatar.face.v3.${sha}`;
function download(data: BlobPart, type: string, name: string) {
  const url = URL.createObjectURL(new Blob([data], { type }));
  const link = document.createElement("a"); link.href = url; link.download = name; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function LiveAvatar({ artifactId }: { artifactId?: string }) {
  const mountRef = useRef<HTMLDivElement>(null), videoRef = useRef<HTMLVideoElement>(null);
  const sceneRef = useRef<AvatarScene | null>(null), sessionRef = useRef<CameraSession | null>(null);
  const profileRef = useRef<FaceProfile | null>(null);
  const baseline = useRef<Record<string, number>>({}), neutralMatrix = useRef<number[] | null>(null);
  const calibration = useRef<FaceFrame[] | null>(null), lastSeen = useRef(0);
  const gazeCenter = useRef<Gaze>(neutralGaze()), calibrationMode = useRef<"all" | "gaze">("all"), calibrationStarted = useRef(0);
  const [assets, setAssets] = useState<ArtifactListItem[]>([]), [artifact, setArtifact] = useState<ArtifactDetail | null>(null);
  const [profile, setProfile] = useState<FaceProfile | null>(null), [models, setModels] = useState({ meshes: [] as string[], bones: [] as string[], morphs: [] as string[] });
  const [message, setMessage] = useState("아바타를 선택해 주세요."), [cameraStatus, setCameraStatus] = useState("웹캠 꺼짐");
  const [running, setRunning] = useState(false), [starting, setStarting] = useState(false), [ready, setReady] = useState(false);
  const [values, setValues] = useState<FaceValues>(neutralFace), [picking, setPicking] = useState<AnchorName | null>(null);
  const [detected, setDetected] = useState(false), [calibrationCount, setCalibrationCount] = useState<number | null>(null);
  const [exporting, setExporting] = useState(false);
  const [rigError, setRigError] = useState(false);
  const [gaze, setGaze] = useState<Gaze>(neutralGaze), [gazeValid, setGazeValid] = useState(false), [gazeError, setGazeError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    void frameflowApi.listAllArtifacts(["CharacterRigged", "Character3D", "Model3D", "AnimatedCharacter"]).then((items) => { if (active) setAssets(items); }).catch(() => { if (active) setMessage("아바타 목록을 불러오지 못했습니다."); });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (!artifactId || !mountRef.current) return;
    let active = true;
    let scene: AvatarScene | null = null;
    void Promise.all([frameflowApi.getArtifact(artifactId), import("./avatar-scene")]).then(async ([asset, module]) => {
      if (!active || !mountRef.current) return;
      if (!["CharacterRigged", "Character3D", "Model3D", "AnimatedCharacter"].includes(asset.type)) throw new Error("GLB 아바타를 선택해 주세요.");
      setArtifact(asset); setMessage("3D 아바타를 불러오는 중…");
      scene = new module.AvatarScene(mountRef.current); sceneRef.current = scene;
      await scene.load(`${API_BASE}/artifacts/${encodeURIComponent(asset.id)}/content`);
      if (!active) return;
      const meshes = scene.meshes.map((mesh) => mesh.name);
      const bones = scene.bones.map((bone) => bone.name);
      const morphs = [...new Set(scene.morphMeshes.flatMap((mesh) => Object.keys(mesh.morphTargetDictionary ?? {})))];
      const mesh = scene.meshes.find((mesh) => Object.keys(mesh.morphTargetDictionary ?? {}).length) ?? [...scene.meshes].sort((a, b) => b.geometry.getAttribute("position").count - a.geometry.getAttribute("position").count)[0];
      let initial: FaceProfile = {
        schema_version: "avatar.face_profile.v3", source_sha256: asset.sha256,
        mode: morphs.length ? "native" : "starter", mesh: mesh?.name ?? "", head_bone: bones.find((name) => /head$/i.test(name)) ?? "",
        front_axis: asset.metadata.provider === "tripo" ? "+x" : "+z",
        anchors: {}, eye_radius: .38, depth: .3, gain: 1.4, smoothing: .09,
        mouth_patch: true,
        gaze: defaultGaze(false),
        expressions: defaultExpressions(morphs.length ? "extended" : "basic"),
        mappings: Object.fromEntries([...EXPRESSION_CHANNELS, ...GAZE_CHANNELS].map((key) => [key, findMorphMapping(morphs, key)])),
      };
      initial.gaze.left_eye_bone = bones.find((name) => /left.*eye|eye.*left|eye_l$/i.test(name)) ?? "";
      initial.gaze.right_eye_bone = bones.find((name) => /right.*eye|eye.*right|eye_r$/i.test(name)) ?? "";
      if (initial.gaze.left_eye_bone && initial.gaze.right_eye_bone) initial.gaze.method = "bones";
      else if (GAZE_CHANNELS.some((key) => initial.mappings[key])) initial.gaze.method = "morphs";
      if (scene.embeddedProfile) {
        try { initial = parseFaceProfile({ ...(scene.embeddedProfile as object), source_sha256: asset.sha256 }, asset.sha256); }
        catch { /* Ignore malformed embedded authoring metadata. */ }
      }
      if (catAvatarPreset.source_sha256 === asset.sha256) initial = parseFaceProfile(catAvatarPreset, asset.sha256);
      try { const saved = localStorage.getItem(storageKey(asset.sha256)) ?? localStorage.getItem(`frameflow.avatar.face.v2.${asset.sha256}`) ?? localStorage.getItem(`frameflow.avatar.face.v1.${asset.sha256}`); if (saved) initial = parseFaceProfile(JSON.parse(saved), asset.sha256); } catch { /* A corrupt local preference must not prevent opening the original model. */ }
      scene.onPick = (name, point) => {
        setProfile((current) => current ? { ...current, anchors: { ...current.anchors, [name]: point } } : null);
        const next: AnchorName | null = name === "leftEye" ? "rightEye" : name === "rightEye" ? "mouth" : null;
        setPicking(next); scene?.setPicking(next);
      };
      setModels({ meshes, bones, morphs }); setProfile(initial); setReady(true);
      setMessage(morphs.length ? `기존 표정 ${morphs.length}개를 발견했습니다. 매핑을 확인해 주세요.` : Object.keys(initial.anchors).length === 3 ? "얼굴 설정을 불러왔습니다. 표정 테스트 후 웹캠을 시작해 주세요." : "간이 리그: 양쪽 눈과 입 중앙을 지정하면 표정 테스트를 시작할 수 있습니다.");
    }).catch((error) => { if (active) setMessage(error instanceof Error ? error.message : "아바타 로딩 실패"); });
    return () => { active = false; scene?.dispose(); sceneRef.current = null; };
  }, [artifactId]);

  useEffect(() => {
    profileRef.current = profile;
    if (!profile || !sceneRef.current) return;
    let active = true;
    void Promise.resolve().then(() => {
      if (!active || !sceneRef.current) return;
      sceneRef.current.useProfile(profile); setRigError(false); setGazeError(sceneRef.current.gazeError); setGaze(neutralGaze()); setValues(neutralFace());
    }).catch((error) => {
      if (active) { setRigError(true); setMessage(error instanceof Error ? error.message : "리그 설정을 확인해 주세요."); }
    });
    return () => { active = false; };
  }, [profile]);

  const receiveFrame = useCallback((frame: FaceFrame) => {
    const scene = sceneRef.current, current = profileRef.current;
    if (!scene || !current) return;
    setDetected(frame.detected);
    const rawGaze = estimateGaze(frame);
    setGazeValid(rawGaze.valid);
    if (!frame.detected) { scene.targetValues = neutralFace(); scene.targetGaze = neutralGaze(); scene.setHeadMatrix([], null); setValues(neutralFace()); setGaze(neutralGaze()); return; }
    lastSeen.current = performance.now();
    if (calibration.current) {
      if (calibrationMode.current === "all" || rawGaze.valid) calibration.current.push(frame);
      setCalibrationCount(calibration.current.length);
      if (calibration.current.length >= 24) {
        if (calibrationMode.current === "all") { baseline.current = meanBaseline(calibration.current); neutralMatrix.current = frame.matrix; }
        try { gazeCenter.current = meanGaze(calibration.current); setMessage(calibrationMode.current === "gaze" ? "시선 중심 보정 완료. 눈동자를 상하·좌우로 움직여 보세요." : "무표정·시선 중심 보정 완료."); }
        catch { setMessage("무표정은 보정됐습니다. 눈을 뜨고 시선 중심을 다시 보정해 주세요."); }
        calibration.current = null; setCalibrationCount(null);
      }
    }
    const next = calibratedValues(frame.values, baseline.current, current.gain, current.mode === "starter" ? defaultExpressions() : current.expressions);
    scene.targetValues = next; scene.setHeadMatrix(frame.matrix, neutralMatrix.current);
    const nextGaze = rawGaze.valid && !scene.gazeError ? calibratedGaze(rawGaze, gazeCenter.current, current.gaze) : neutralGaze();
    scene.targetGaze = nextGaze; setGaze(nextGaze);
    setValues(next);
  }, []);

  useEffect(() => {
    if (!videoRef.current) return;
    const session = new CameraSession(videoRef.current, receiveFrame, (status, active) => {
      setCameraStatus(status); setRunning(active);
      if (active || !status.endsWith("…")) setStarting(false);
      if (!active && !status.endsWith("…")) { sceneRef.current?.resetPose(); setValues(neutralFace()); setGaze(neutralGaze()); setGazeValid(false); setDetected(false); setCalibrationCount(null); calibration.current = null; }
    });
    sessionRef.current = session;
    const hidden = () => { if (document.hidden) session.stop(); };
    document.addEventListener("visibilitychange", hidden);
    const timer = setInterval(() => {
      if (performance.now() - lastSeen.current > 600) { if (sceneRef.current && videoRef.current && !videoRef.current.paused) { sceneRef.current.targetValues = neutralFace(); sceneRef.current.targetGaze = neutralGaze(); sceneRef.current.setHeadMatrix([], null); setGaze(neutralGaze()); setGazeValid(false); } }
      if (calibration.current && performance.now() - calibrationStarted.current > 8000) { calibration.current = null; setCalibrationCount(null); setMessage("보정에 필요한 얼굴·눈 데이터를 얻지 못했습니다. 눈을 뜨고 정면을 보며 다시 시도해 주세요."); }
    }, 250);
    return () => { session.stop(false); sessionRef.current = null; clearInterval(timer); document.removeEventListener("visibilitychange", hidden); };
  }, [receiveFrame]);

  const update = (patch: Partial<FaceProfile>) => setProfile((current) => current ? { ...current, ...patch } : null);
  const rigReady = !rigError && !!profile && (profile.mode === "native" ? Object.values(profile.mappings).some(Boolean) : Object.keys(profile.anchors).length === 3);
  const start = (file?: File) => { setStarting(true); setPicking(null); sceneRef.current?.setPicking(null); baseline.current = {}; neutralMatrix.current = null; gazeCenter.current = neutralGaze(); void sessionRef.current?.start(file); };
  const beginCalibration = (mode: "all" | "gaze") => { calibration.current = []; calibrationMode.current = mode; calibrationStarted.current = performance.now(); setCalibrationCount(0); setMessage(mode === "gaze" ? "눈을 뜨고 카메라 렌즈를 바라봐 주세요." : "카메라 렌즈를 보고 눈을 뜬 채 입을 다물어 주세요."); };
  const updateGaze = (patch: Partial<FaceProfile["gaze"]>) => { if (profile) update({ gaze: { ...profile.gaze, ...patch } }); };
  const testGaze = (next: Gaze) => { setGaze(next); if (sceneRef.current) sceneRef.current.targetGaze = next; };
  const pick = (name: AnchorName) => { sessionRef.current?.stop(); setValues(neutralFace()); sceneRef.current?.resetPose(); sceneRef.current?.focus(true); setPicking(name); sceneRef.current?.setPicking(name); };
  const testValue = (key: FaceChannel, value: number) => { const next = { ...values, [key]: value }; setValues(next); if (sceneRef.current) sceneRef.current.targetValues = next; };
  const save = () => {
    if (!profile) return;
    try { localStorage.setItem(storageKey(profile.source_sha256), JSON.stringify(profile)); setMessage("이 브라우저에 얼굴 설정을 저장했습니다."); }
    catch { setMessage("설정을 저장하지 못했습니다. 설정 파일 내보내기를 이용해 주세요."); }
  };
  const exportModel = async () => {
    if (!sceneRef.current) return;
    sessionRef.current?.stop(); setValues(neutralFace()); setExporting(true);
    try { download(await sceneRef.current.exportGlb(), "model/gltf-binary", "avatar-face-rig.glb"); setMessage("표정이 포함된 새 GLB를 내보냈습니다. 원본 아바타는 유지됩니다."); }
    catch (error) { setMessage(error instanceof Error ? error.message : "GLB 내보내기 실패"); }
    finally { setExporting(false); }
  };

  if (!artifactId) return <div className={styles.picker}><h1>Live Avatar</h1><p>웹캠에 연결할 아바타를 선택하세요.</p><div><Link href="/live-avatar/2d/face"><ScanFace size={24} /><strong>2D 웹캠 얼굴 리그</strong><small>현재 고양이 캐릭터 · 눈·입·눈썹·시선 추적</small><small>웹캠 연결 → 무표정 보정 → 표정 맞추기</small></Link><Link href="/live-avatar/2d"><ScanFace size={24} /><strong>2D 캐릭터 스튜디오</strong><small>그림체를 유지하는 전신 아바타 · 참고 동작 · 웹캠</small></Link>{assets.map((asset) => <Link key={asset.id} href={`/live-avatar/${asset.id}`}><ScanFace size={24} /><strong>{asset.filename}</strong><small>{asset.type}</small></Link>)}</div>{!assets.length && <p>3D 아바타는 리깅된 GLB를 업로드해 추가할 수 있습니다.</p>}</div>;

  return <div className={styles.workspace}>
    <header className={styles.header}>
      <span><small>LIVE AVATAR</small><h1>{artifact?.metadata.filename ?? "웹캠 아바타"}</h1><p>눈 · 입술 · 볼 · 눈썹 · 시선 · 고개 움직임을 연결합니다.</p></span>
      <div><Button onClick={() => start()} disabled={!ready || running || starting}><Camera size={16} /> {starting ? "연결 중…" : "웹캠 시작"}</Button><Button variant="outline" disabled={!running || !detected || calibrationCount !== null} onClick={() => beginCalibration("all")}><Crosshair size={16} /> 무표정 보정</Button><Button variant="outline" disabled={!running && !starting} onClick={() => sessionRef.current?.stop()}><CameraOff size={16} /> 종료</Button></div>
    </header>
    <div className={styles.layout}>
      <section className={styles.preview}>
        <div ref={mountRef} className={styles.stage} />
        <div className={styles.stageTools}><Button variant="outline" onClick={() => sceneRef.current?.focus(true)}>얼굴 보기</Button><Button variant="outline" onClick={() => sceneRef.current?.focus(false)}>전신 보기</Button><Button variant="outline" onClick={() => { sessionRef.current?.stop(); sceneRef.current?.resetPose(); setValues(neutralFace()); }}><RotateCcw size={14} /> 표정 초기화</Button></div>
        {picking && <div className={styles.pickPrompt}>{ANCHOR_LABELS[picking]}의 중앙을 3D 모델에서 클릭하세요. <button type="button" onClick={() => { setPicking(null); sceneRef.current?.setPicking(null); }}>완료</button></div>}
        <div className={styles.cameraPreview}><video ref={videoRef} autoPlay muted playsInline className={running ? "" : styles.hiddenVideo} />{!running && <div><CameraOff size={24} /><span>웹캠 꺼짐</span></div>}<small>{cameraStatus}{running ? detected ? " · 얼굴 감지" : " · 얼굴을 찾는 중" : ""}</small></div>
        <footer>카메라는 시작 버튼을 누르면 켜집니다. 영상은 브라우저 안에서 처리되며 저장·전송하지 않습니다.</footer>
      </section>
      <aside className={styles.settings}>
        <div className={styles.notice} role="status">{message}{calibrationCount !== null && <progress max={24} value={calibrationCount} />}</div>
        {profile && <>
          <section><h2>1. 얼굴 리그 준비</h2><label>방식<select value={profile.mode} disabled={running} onChange={(e) => update({ mode: e.target.value as FaceProfile["mode"] })}><option value="starter">간이 얼굴 리그</option><option value="native">기존 표정 리그 매핑</option></select></label>
          <label>아바타 정면 방향<select value={profile.front_axis} disabled={running} onChange={(e) => update({ front_axis: e.target.value as FaceProfile["front_axis"] })}>{["+x", "-x", "+z", "-z"].map((axis) => <option key={axis}>{axis}</option>)}</select></label>
          {profile.mode === "starter" ? <>
            <p>눈·입 주변의 메시를 변형하는 기본 리그입니다. 입안·치아 생성과 정교한 눈꺼풀 변형은 포함하지 않습니다.</p>
            <label>얼굴 메시<select value={profile.mesh} disabled={running} onChange={(e) => update({ mesh: e.target.value, anchors: {} })}>{models.meshes.map((name, i) => <option key={name} value={name}>{i + 1}. {name}</option>)}</select></label>
            <div className={styles.anchors}>{(Object.keys(ANCHOR_LABELS) as AnchorName[]).map((name) => <button type="button" className={picking === name ? styles.active : ""} key={name} onClick={() => pick(name)} disabled={!ready || !profile.head_bone}>{profile.anchors[name] ? "✓ " : "+ "}{ANCHOR_LABELS[name]}</button>)}</div>
            <label>눈 변형 반경<input aria-label="눈 변형 반경" type="range" min={.15} max={.55} step={.01} value={profile.eye_radius} disabled={running} onChange={(e) => update({ eye_radius: Number(e.target.value) })} /></label>
            <label>얼굴 영역 깊이<input aria-label="얼굴 영역 깊이" type="range" min={.05} max={.7} step={.01} value={profile.depth} disabled={running} onChange={(e) => update({ depth: Number(e.target.value) })} /></label>
            <label><span><input type="checkbox" checked={profile.mouth_patch !== false} disabled={running} onChange={(e) => update({ mouth_patch: e.target.checked })} /> 입 안쪽 간이 표현</span></label>
          </> : <p>아래 표정 테스트에서 눈·입·볼의 변형을 확인하고 연결·보정을 조절하세요.</p>}
          <label>머리 뼈대<select value={profile.head_bone} disabled={running} onChange={(e) => update({ head_bone: e.target.value })}><option value="">머리 회전 끄기</option>{models.bones.map((name) => <option key={name}>{name}</option>)}</select></label>
          {!profile.head_bone && <p>현재 모델에서 머리 뼈대를 선택해야 고개 움직임과 간이 리그를 사용할 수 있습니다.</p>}
          </section>
          <ExpressionControls profile={profile} morphs={models.morphs} values={values} running={running} ready={rigReady} update={update} test={testValue} preset={(patch) => { const next = { ...neutralFace(), ...patch }; setValues(next); if (sceneRef.current) sceneRef.current.targetValues = next; }} />
          <section><h2>시선 추적</h2>
            <label><span><input type="checkbox" aria-label="시선 추적 사용" checked={profile.gaze.enabled} onChange={(e) => updateGaze({ enabled: e.target.checked })} /> 시선 추적 사용</span></label>
            <p>웹캠으로 눈동자의 상하·좌우 방향을 추정합니다. 카메라를 바라보며 중심을 보정하세요.</p>
            {profile.gaze.enabled && <>
              <label>시선 연결 방식<select aria-label="시선 연결 방식" value={profile.gaze.method} disabled={running} onChange={(e) => updateGaze({ method: e.target.value as FaceProfile["gaze"]["method"] })}><option value="surface">간이 눈동자 이동 · 표면 텍스처</option><option value="bones">안구 뼈대 회전</option><option value="morphs">기존 시선 모프</option></select></label>
              {profile.gaze.method === "surface" && <><p>현재 눈 영역의 색상을 이동합니다. 눈 주변 메시의 품질에 따라 표현이 달라집니다. GLB에는 설정을 저장하며 시선 효과는 Live Avatar에서 적용됩니다.</p><label>눈 영역 반경<input aria-label="시선 눈 영역 반경" type="range" min={.15} max={.5} step={.01} value={profile.gaze.radius} onChange={(e) => updateGaze({ radius: Number(e.target.value) })} /></label><label>눈동자 이동 범위<input aria-label="눈동자 이동 범위" type="range" min={.01} max={.15} step={.005} value={profile.gaze.range} onChange={(e) => updateGaze({ range: Number(e.target.value) })} /></label></>}
              {profile.gaze.method === "bones" && <>{(["left_eye_bone", "right_eye_bone"] as const).map((key) => <label key={key}>{key === "left_eye_bone" ? "왼쪽 안구 뼈대" : "오른쪽 안구 뼈대"}<select value={profile.gaze[key]} disabled={running} onChange={(e) => updateGaze({ [key]: e.target.value })}><option value="">선택</option>{models.bones.map((name) => <option key={name}>{name}</option>)}</select></label>)}<label>최대 회전 · {profile.gaze.max_angle}°<input type="range" min={5} max={40} value={profile.gaze.max_angle} onChange={(e) => updateGaze({ max_angle: Number(e.target.value) })} /></label></>}
              {profile.gaze.method === "morphs" && GAZE_CHANNELS.map((key) => <label key={key}>{GAZE_LABELS[key]}<select value={profile.mappings[key] ?? ""} disabled={running} onChange={(e) => update({ mappings: { ...profile.mappings, [key]: e.target.value } })}><option value="">연결 안 함</option>{models.morphs.map((name) => <option key={name}>{name}</option>)}</select></label>)}
              {gazeError && <p role="alert">{gazeError}</p>}
              <div className={styles.gazePad} aria-label="시선 방향 표시"><i style={{ left: `${50 + gaze.x * 40}%`, top: `${50 - gaze.y * 40}%` }} /></div>
              <p>{running ? gazeValid ? "시선 감지 중" : "눈을 뜨고 정면을 바라봐 주세요." : "슬라이더로 정면 기준 방향을 확인하세요."}</p>
              <label>시선 좌우<input aria-label="시선 좌우" type="range" min={-1} max={1} step={.01} value={gaze.x} disabled={running || !!gazeError} onChange={(e) => testGaze({ ...gaze, x: Number(e.target.value) })} /></label>
              <label>시선 상하<input aria-label="시선 상하" type="range" min={-1} max={1} step={.01} value={gaze.y} disabled={running || !!gazeError} onChange={(e) => testGaze({ ...gaze, y: Number(e.target.value) })} /></label>
              <div className={styles.gazeActions}><Button variant="outline" disabled={!running || !gazeValid || calibrationCount !== null} onClick={() => beginCalibration("gaze")}>시선 중심 보정</Button><Button variant="outline" disabled={running} onClick={() => testGaze(neutralGaze())}>시선 중앙</Button></div>
              <label>시선 민감도 · {profile.gaze.sensitivity.toFixed(1)}×<input aria-label="시선 민감도" type="range" min={.5} max={6} step={.1} value={profile.gaze.sensitivity} onChange={(e) => updateGaze({ sensitivity: Number(e.target.value) })} /></label>
              <label>시선 떨림 완화 · {Math.round(profile.gaze.smoothing * 1000)} ms<input aria-label="시선 떨림 완화" type="range" min={.02} max={.5} step={.01} value={profile.gaze.smoothing} onChange={(e) => updateGaze({ smoothing: Number(e.target.value) })} /></label>
              <label>미세 움직임 무시<input aria-label="시선 미세 움직임 무시" type="range" min={0} max={.3} step={.01} value={profile.gaze.deadzone} onChange={(e) => updateGaze({ deadzone: Number(e.target.value) })} /></label>
              <div className={styles.gazeActions}><label><span><input type="checkbox" checked={profile.gaze.invert_x} onChange={(e) => updateGaze({ invert_x: e.target.checked })} /> 좌우 반전</span></label><label><span><input type="checkbox" checked={profile.gaze.invert_y} onChange={(e) => updateGaze({ invert_y: e.target.checked })} /> 상하 반전</span></label></div>
            </>}
          </section>
          <section><h2>3. 추적 보정</h2><label>표정 민감도 · {profile.gain.toFixed(1)}×<input aria-label="표정 민감도" type="range" min={.5} max={3} step={.1} value={profile.gain} onChange={(e) => update({ gain: Number(e.target.value) })} /></label><label>떨림 완화 · {Math.round(profile.smoothing * 1000)} ms<input aria-label="떨림 완화" type="range" min={.02} max={.5} step={.01} value={profile.smoothing} onChange={(e) => update({ smoothing: Number(e.target.value) })} /></label><label>녹화 영상으로 테스트 (로컬)<input aria-label="녹화 영상으로 테스트" type="file" accept="video/*" disabled={!ready || running || starting} onChange={(e) => { const file = e.target.files?.[0]; e.target.value = ""; if (file) start(file); }} /></label></section>
          <section className={styles.saveActions}><Button variant="outline" onClick={save}><Save size={15} /> 설정 저장</Button><Button variant="outline" onClick={() => download(JSON.stringify(profile, null, 2), "application/json", "face-profile.json")}><Download size={15} /> 설정 내보내기</Button><label>설정 불러오기<input aria-label="얼굴 설정 불러오기" type="file" accept=".json" disabled={running} onChange={async (event) => { const file = event.target.files?.[0]; if (!file || !artifact) return; try { if (file.size > 100_000) throw new Error("설정 파일이 너무 큽니다."); setProfile(parseFaceProfile(JSON.parse(await file.text()), artifact.sha256)); } catch (error) { setMessage(error instanceof Error ? error.message : "설정 파일 오류"); } }} /></label><Button disabled={!rigReady || exporting} onClick={() => void exportModel()}><Download size={15} /> {exporting ? "내보내는 중…" : "표정 리그 GLB 내보내기"}</Button></section>
        </>}
        <Link href="/live-avatar">다른 아바타 선택</Link>
      </aside>
    </div>
  </div>;
}
