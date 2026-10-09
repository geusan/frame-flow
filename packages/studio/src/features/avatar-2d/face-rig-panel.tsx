"use client";
import {useEffect,useMemo,useRef,useState} from 'react';
import {Camera,Save,Download,ScanFace} from 'lucide-react';
import {FACE_CHANNELS_2D,FACE_POINT_IDS,FACE_POINT_LABELS,FACE_POSE_IDS,FACE_CROP,RIG_CHANNEL_META,editableFacePoints,parseFaceRig,freshFaceRig,type FacePoseId,type FacePointId,type FacePoint,type RigChannel} from './face-rig';
import {expressionRect,EXPRESSION_SOURCE_SHA,portableExpressions,parseExpressions,type ExpressionLibrary} from './expression-library';
import {triangulateFace} from './face-triangulation';
import {inferFacePoints} from './face-rig-inference';
import type {useFaceRigController} from './face-rig-controller';
import {AllFaceChannelsPanel} from "./all-face-channels-panel";
import {MouthRigPanel} from "./mouth-rig-panel";
import {EyelidRigPanel} from "./eyelid-rig-panel";
import {FeatureAlignmentPanel} from "./feature-alignment-panel";
import {LeftEyeLab} from "./left-eye-lab";
import styles from './face-rig-panel.module.css';
type Controller=ReturnType<typeof useFaceRigController>;
const download=(blob:Blob,name:string)=>{const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),2000);};
export function FaceRigPanel({face,ready,running,starting,start,stop,focus,importLibrary,initialCloseup=false,cameraStatus}:{initialCloseup?:boolean;cameraStatus:string;face:Controller;ready:boolean;running:boolean;starting:boolean;start:(file?:File)=>void;stop:()=>void;focus:(enabled:boolean)=>void;importLibrary:(library:ExpressionLibrary)=>void}){
  const [pose,setPose]=useState<FacePoseId>('neutral'),[point,setPoint]=useState<FacePointId>('mouthInnerLower'),[channel,setChannel]=useState<RigChannel>('jawOpen'),[message,setMessage]=useState(''),[closeup,setCloseup]=useState(initialCloseup),[busy,setBusy]=useState(false);
  const dragging=useRef<FacePointId|null>(null),svg=useRef<SVGSVGElement>(null);
  const inference=useRef<AbortController|null>(null);
  useEffect(()=>()=>inference.current?.abort(),[]);
  const points=face.profile.poses[pose].points,source=face.library.entries.find(e=>e.id===face.profile.poses[pose].imageId),rect=source?expressionRect(source):[0,0,1024,1536];
  const triangles=useMemo(()=>triangulateFace(FACE_POINT_IDS.map(id=>face.profile.poses.neutral.points[id])),[face.profile.poses.neutral.points]);
  const move=(id:FacePointId,p:FacePoint)=>{try{face.setProfile({...face.profile,poses:{...face.profile.poses,[pose]:{...face.profile.poses[pose],points:{...points,[id]:[Math.max(420,Math.min(600,p[0])),Math.max(145,Math.min(290,p[1]))]}}}});setMessage('');}catch(error){setMessage(error instanceof Error?error.message:'기준점 오류');}};
  const response=face.profile.channels[channel];
  return <section id="avatar-face-rig" className={styles.panel} aria-label="웹캠 얼굴 리그">
    <div className={styles.title}><ScanFace size={14}/><h2>웹캠 얼굴 리그</h2><button type="button" aria-pressed={closeup} onClick={()=>{setCloseup(!closeup);focus(!closeup);}}><ScanFace size={14}/>{closeup?'전신 보기':'얼굴 확대'}</button></div>
    <p>MediaPipe가 내 눈·입·눈썹·시선을 읽어 캐릭터 얼굴 리그를 연속적으로 움직입니다. 얼굴이 보이게 앉은 뒤 웹캠을 연결하고, 편안한 무표정으로 보정하세요.</p>
    <p role="status" className={styles.status}>{cameraStatus}</p>
    <div className={styles.actions}><button type="button" aria-pressed={face.showMesh} onClick={()=>{if(face.mode==='reference')face.setMode('live');face.setShowMesh(!face.showMesh);}}>웹캠·아바타 리그 비교 {face.showMesh?'숨기기':'표시'}</button></div>
    {face.showMesh&&<p>웹캠에는 검출 기준점, 아바타에는 변형 메시를 같은 색으로 표시합니다. 하늘색: 눈 · 초록: 눈동자 · 분홍: 눈썹 · 주황: 입. 흰 선은 원래 위치에서 이동한 거리입니다. 좌우는 캐릭터 기준입니다.</p>}
    <div className={styles.actions}><button type="button" className={styles.primary} disabled={!ready||running||starting} onClick={()=>{face.setMode('live');start();}}><Camera size={14}/> 웹캠 얼굴 연결</button><button type="button" disabled={!running||!face.telemetry.detected||face.telemetry.calibrating} onClick={()=>face.calibrate('neutral')}>무표정 보정</button><button type="button" disabled={!running&&!starting} onClick={stop}>얼굴 추적 종료</button></div>
    <label className={styles.file}>얼굴 영상으로 추적 테스트<input aria-label="얼굴 추적 영상 테스트" type="file" accept="video/*" disabled={!ready||starting} onChange={e=>{const file=e.target.files?.[0];e.target.value="";if(file)start(file);}}/></label>
    <div className={styles.actions}>{([['live','웹캠 구동'],['test','리그 테스트'],['reference','제작 자료 보기']] as const).map(([id,label])=><button type="button" aria-pressed={face.mode===id} key={id} onClick={()=>face.setMode(id)}>{label}</button>)}</div>
    <p className={styles.status}>{face.error||message||face.telemetry.message} {face.mode==='live'?(face.telemetry.detected?' · 얼굴 감지 중':' · 얼굴 감지 대기'):''}</p>
    {face.telemetry.calibrating&&<progress aria-label="얼굴 보정 진행" max={24} value={face.telemetry.progress}/>}
    {face.telemetry.limited&&<p>메시가 뒤집히는 구간의 변형을 제한했습니다. 해당 표정의 기준점을 확인하세요.</p>}
    <div className={styles.bars}>{FACE_CHANNELS_2D.map(key=><span className={styles.bar} key={key}>{RIG_CHANNEL_META[key].label} {Math.round(face.telemetry.values[key]*100)}%<meter aria-label={`${RIG_CHANNEL_META[key].label} 추적값`} min={0} max={1} value={face.telemetry.values[key]}/></span>)}</div>
    <details open><summary>본체 양쪽 눈 · 구면 리그</summary><label><span><input type="checkbox" checked={face.eyeAppearance.enabled} onChange={e=>face.setEyeAppearance({...face.eyeAppearance,enabled:e.target.checked})}/> 본체에 양안 구면 리그 적용</span></label><label>홍채 외경<input aria-label="본체 왼눈 홍채 외경" type="range" min=".6" max="1.4" step=".01" value={face.eyeAppearance.size} onChange={e=>face.setEyeAppearance({...face.eyeAppearance,size:Number(e.target.value)})}/></label><label>동공 직경<input aria-label="본체 왼눈 동공 직경" type="range" min=".12" max=".75" step=".01" value={face.eyeAppearance.pupil} onChange={e=>face.setEyeAppearance({...face.eyeAppearance,pupil:Number(e.target.value)})}/></label><label>눈 사이 간격 · 원화의 {Math.round((face.eyeAppearance.spacing??.94)*100)}%<input aria-label="캐릭터 눈 사이 간격" type="range" min=".8" max="1.15" step=".01" value={face.eyeAppearance.spacing??.94} onChange={e=>face.setEyeAppearance({...face.eyeAppearance,spacing:Number(e.target.value)})}/></label><label>가상 주시 거리 · 얼굴 너비의 {((face.eyeAppearance.focusDistance??60)/10).toFixed(1)}배<input aria-label="양안 주시 거리" type="range" min="20" max="200" step="1" value={face.eyeAppearance.focusDistance??60} onChange={e=>face.setEyeAppearance({...face.eyeAppearance,focusDistance:Number(e.target.value)})}/></label><p>정면의 한 점을 향해 두 눈의 각도를 각각 계산합니다. 가까울수록 안쪽 회전이 커집니다. 눈 중심·눈꼬리·볼 기준점에서 배치와 시선 각도를 계산합니다. 거리는 캐릭터 얼굴 너비에 대한 비율이며 실측값이 아닙니다. 눈 감김은 좌우 독립이며 동공 크기는 수동 설정입니다.</p></details>
    <AllFaceChannelsPanel face={face}/>
    <MouthRigPanel face={face}/>
    <EyelidRigPanel face={face}/>
    <FeatureAlignmentPanel face={face}/>
    <details><summary>왼쪽 눈 이미지 레이어 실험</summary><LeftEyeLab values={face.telemetry.values}/></details>
    <details open><summary>표정 채널 연결·보정</summary>
      <p>선택 채널: MediaPipe 원본 {Math.round((face.telemetry.raw[channel]??0)*100)}% → 리그 적용 {Math.round(face.telemetry.values[channel]*100)}%</p>
      <p>무표정 보정 후 채널을 골라 해당 표정을 크게 유지하고 최대값을 보정하세요. 수동 테스트가 잘 움직이면 추적 강도를, 수동 테스트부터 어긋나면 아래 기준점을 조절하세요.</p>
      <label>웹캠 채널<select aria-label="얼굴 리그 채널" value={channel} onChange={e=>setChannel(e.target.value as RigChannel)}>{FACE_CHANNELS_2D.map(k=><option key={k} value={k}>{RIG_CHANNEL_META[k].label}</option>)}</select></label>
      <label>목표 표정<select aria-label="채널 목표 표정" disabled={RIG_CHANNEL_META[channel].gaze} value={response.pose} onChange={e=>face.setProfile({...face.profile,channels:{...face.profile.channels,[channel]:{...response,pose:e.target.value as FacePoseId}}})}>{FACE_POSE_IDS.map(id=><option key={id} value={id}>{face.library.entries.find(e=>e.id===face.profile.poses[id].imageId)?.name??id}</option>)}</select></label>
      <label>수동 리그 테스트<span>{Math.round(face.telemetry.values[channel]*100)}%</span><input aria-label="얼굴 리그 테스트 강도" type="range" min={0} max={1} step={.01} value={face.mode==='test'?face.manualValues[channel]:face.telemetry.values[channel]} onChange={e=>face.test(channel,Number(e.target.value))}/></label>
      <div className={styles.actions}><button type="button" onClick={face.clearTest}>테스트 초기화</button><button type="button" disabled={!running||!face.telemetry.detected||face.telemetry.calibrating} onClick={()=>face.calibrate(channel)}>선택 표정 최대값 보정</button></div>
      {([['gain','반응 강도',5],['deadzone','미세 움직임 무시',.4],['max','최대 변형',1]] as const).map(([key,label,max])=><label key={key}>{label}<span>{response[key].toFixed(2)}</span><input aria-label={`얼굴 리그 ${label}`} type="range" min={0} max={max} step={.01} value={response[key]} onChange={e=>face.setProfile({...face.profile,channels:{...face.profile.channels,[channel]:{...response,[key]:Number(e.target.value)}}})}/></label>)}
      <label>얼굴 떨림 완화<span>{Math.round(face.profile.smoothing*1000)} ms</span><input aria-label="얼굴 리그 떨림 완화" type="range" min={.02} max={.4} step={.01} value={face.profile.smoothing} onChange={e=>face.setProfile({...face.profile,smoothing:Number(e.target.value)})}/></label>
      <label><span><input type="checkbox" checked={response.enabled} onChange={e=>face.setProfile({...face.profile,channels:{...face.profile.channels,[channel]:{...response,enabled:e.target.checked}}})}/> 이 채널 사용</span></label>
    </details>
    <details><summary>원본·표정 이미지 기준점 편집</summary>
      <p>양쪽 눈과 입의 같은 위치를 맞추세요. 주황색 점을 드래그하거나 좌표를 조절합니다. 기준점은 정밀 조정이 가능한 초안입니다.</p>
      <label>편집할 기준 표정<select aria-label="기준점 편집 표정" value={pose} onChange={e=>setPose(e.target.value as FacePoseId)}>{FACE_POSE_IDS.map(id=><option key={id} value={id}>{id==='neutral'?'원본 기준점':face.library.entries.find(e=>e.id===face.profile.poses[id].imageId)?.name??id}</option>)}</select></label>
      <label>제작 자료 이미지<select aria-label="리그 제작 자료 이미지" value={face.profile.poses[pose].imageId} disabled={pose==='neutral'} onChange={e=>face.setProfile({...face.profile,poses:{...face.profile.poses,[pose]:{...face.profile.poses[pose],imageId:e.target.value}}})}>{face.library.entries.map(e=><option key={e.id} value={e.id}>{e.name}</option>)}</select></label>
      <svg ref={svg} className={styles.editor} viewBox={`${FACE_CROP.x} ${FACE_CROP.y} ${FACE_CROP.width} ${FACE_CROP.height}`} aria-label="얼굴 기준점 편집" onPointerMove={e=>{if(!dragging.current||!svg.current)return;const r=svg.current.getBoundingClientRect();move(dragging.current,[FACE_CROP.x+(e.clientX-r.left)/r.width*FACE_CROP.width,FACE_CROP.y+(e.clientY-r.top)/r.height*FACE_CROP.height]);}} onPointerUp={()=>{dragging.current=null;}} onPointerCancel={()=>{dragging.current=null;}}>
        {source&&<image href={source.image} x={rect[0]} y={rect[1]} width={rect[2]} height={rect[3]}/>}
        {triangles.map((t,i)=><polygon key={i} points={t.map(index=>points[FACE_POINT_IDS[index]].join(',')).join(' ')} fill="none" stroke="#9c76cb" strokeWidth={.28} opacity={.55}/>)}
        {editableFacePoints.map(id=><circle key={id} cx={points[id][0]} cy={points[id][1]} r={point===id?2.3:1.45} fill={point===id?'#ffc557':'#fff'} stroke="#704dac" strokeWidth={.65} tabIndex={0} role="button" aria-label={FACE_POINT_LABELS[id]} onPointerDown={e=>{e.preventDefault();e.currentTarget.setPointerCapture(e.pointerId);dragging.current=id;setPoint(id);}} onKeyDown={e=>{const d={ArrowLeft:[-1,0],ArrowRight:[1,0],ArrowUp:[0,-1],ArrowDown:[0,1]}[e.key];if(d){e.preventDefault();move(id,[points[id][0]+d[0]*(e.shiftKey?1:.25),points[id][1]+d[1]*(e.shiftKey?1:.25)]);}}}><title>{FACE_POINT_LABELS[id]}</title></circle>)}
      </svg>
      <label>기준점<select aria-label="얼굴 기준점" value={point} onChange={e=>setPoint(e.target.value as FacePointId)}>{editableFacePoints.map(id=><option key={id} value={id}>{FACE_POINT_LABELS[id]}</option>)}</select></label>
      <div className={styles.grid}>{(['X','Y'] as const).map((axis,i)=><label key={axis}>{axis}<input aria-label={`기준점 ${axis}`} type="number" step={.25} value={points[point][i]} onChange={e=>{const p=[...points[point]] as FacePoint;p[i]=Number(e.target.value);move(point,p);}}/></label>)}</div>
      <button type="button" disabled={busy||!source} onClick={async()=>{if(!source)return;inference.current?.abort();const controller=new AbortController();inference.current=controller;setBusy(true);try{const detected=await inferFacePoints(source,points,controller.signal);face.setProfile({...face.profile,poses:{...face.profile.poses,[pose]:{...face.profile.poses[pose],points:detected}}});setMessage('자동 기준점 초안을 적용했습니다. 눈꺼풀·입술 위치를 그림과 대조해 보정하세요.');}catch(error){if(!controller.signal.aborted)setMessage(error instanceof Error?error.message:'기준점 분석 실패');}finally{if(!controller.signal.aborted)setBusy(false);}}}>{busy?'기준점 분석 중…':'MediaPipe 기준점 초안 검출'}</button>
      <button type="button" onClick={()=>face.setProfile({...face.profile,poses:{...face.profile.poses,[pose]:freshFaceRig(EXPRESSION_SOURCE_SHA).poses[pose]}})}>이 기준 표정 초기화</button>
    </details>
    <div className={styles.actions}><button type="button" onClick={async()=>{try{await face.save();setMessage('얼굴 리그를 이 브라우저에 저장했습니다.');}catch{setMessage('리그를 저장하지 못했습니다. 파일로 내보내 주세요.');}}}><Save size={14}/> 얼굴 리그 저장</button><button type="button" disabled={busy} onClick={async()=>{setBusy(true);try{const library=await portableExpressions(face.library);download(new Blob([JSON.stringify({schema_version:'avatar.face_rig_package.v1',rig:face.profile,library})],{type:'application/json'}),'cat-2d-face-rig.json');setMessage('표정 이미지·기준점·채널 연결을 내보냈습니다.');}catch{setMessage('얼굴 리그 내보내기 실패');}finally{setBusy(false);}}}><Download size={14}/> 리그 모음 내보내기</button></div>
    <label className={styles.file}>얼굴 리그 모음 불러오기<input aria-label="얼굴 리그 모음 불러오기" type="file" accept=".json" disabled={busy} onChange={async e=>{const file=e.target.files?.[0];e.target.value='';if(!file)return;try{if(file.size>40_000_000)throw new Error('리그 파일은 40MB 이하여야 합니다.');const pack=JSON.parse(await file.text());if(pack.schema_version!=='avatar.face_rig_package.v1')throw new Error('얼굴 리그 모음 파일이 아닙니다.');const rig=parseFaceRig(pack.rig,EXPRESSION_SOURCE_SHA),library=parseExpressions(pack.library);if(FACE_POSE_IDS.some(id=>!library.entries.some(e=>e.id===rig.poses[id].imageId)))throw new Error('리그 제작 자료가 누락됐습니다.');importLibrary(library);face.setProfile(rig);setMessage('얼굴 리그를 불러왔습니다. 확인 후 저장하세요.');}catch(error){setMessage(error instanceof Error?error.message:'리그 불러오기 실패');}}}/></label>
    <p>표정 12개와 눈동자 방향 8개 채널을 연결합니다. 얼굴만 보여도 표정을 처리하며, 카메라 영상은 브라우저 밖으로 전송하지 않습니다.</p>
  </section>;
}
