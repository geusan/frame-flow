"use client";
import {useState} from 'react';
import {FACE_MOTION_CHANNELS,RIG_CHANNEL_META,type FaceMotionChannel,type RigChannel} from './face-rig';
import type {useFaceRigController} from './face-rig-controller';
import styles from './face-rig-panel.module.css';
const labels:Partial<Record<FaceMotionChannel,string>>={browOuterUpLeft:'왼쪽 눈썹 바깥 올림',browOuterUpRight:'오른쪽 눈썹 바깥 올림',eyeSquintLeft:'왼눈 찡그림',eyeSquintRight:'오른눈 찡그림',jawForward:'턱 내밀기',jawLeft:'턱 왼쪽',jawRight:'턱 오른쪽',mouthClose:'입술 닫기',mouthDimpleLeft:'왼쪽 보조개·입꼬리 당김',mouthDimpleRight:'오른쪽 보조개·입꼬리 당김',mouthLeft:'입 전체 왼쪽',mouthRight:'입 전체 오른쪽',mouthShrugUpper:'윗입술 들어 올림',mouthShrugLower:'아랫입술 들어 올림',cheekPuff:'볼 부풀리기',cheekSquintLeft:'왼쪽 볼 올림',cheekSquintRight:'오른쪽 볼 올림',noseSneerLeft:'왼쪽 코 찡그림',noseSneerRight:'오른쪽 코 찡그림'};
export function AllFaceChannelsPanel({face}:{face:ReturnType<typeof useFaceRigController>}){
 const [key,setKey]=useState<FaceMotionChannel>('browOuterUpLeft');
 return <details open aria-label="전체 MediaPipe 채널"><summary>MediaPipe 전체 채널 · 51개 움직임</summary><p>51개 움직임을 리그에 연결합니다. neutral은 움직임이 아닌 기준값입니다. 볼·코·턱의 깊이 변화는 현재 2.5D 얼굴 메시로 근사합니다.</p>
 <label>채널<select aria-label="전체 얼굴 채널 선택" value={key} onChange={e=>setKey(e.target.value as FaceMotionChannel)}>{FACE_MOTION_CHANNELS.map(k=><option key={k} value={k}>{labels[k]??RIG_CHANNEL_META[k as RigChannel]?.label??k} · {k}</option>)}</select></label>
 <p>원본 {Math.round((face.telemetry.raw[key]??0)*100)}% → 적용 {Math.round(face.telemetry.values[key]*100)}% · neutral {Math.round((face.telemetry.raw._neutral??face.telemetry.raw.neutral??0)*100)}%</p>
 <label>선택 채널 수동 강도<input aria-label="전체 얼굴 채널 수동 강도" type="range" min="0" max="1" step=".01" value={face.mode==='test'?face.manualValues[key]:face.telemetry.values[key]} onChange={e=>face.test(key,Number(e.target.value))}/></label>
 <div className={styles.actions}><button type="button" onClick={()=>{face.clearTest();face.test(key,.8);}}>선택 채널만 테스트</button><button type="button" onClick={()=>{face.clearTest();face.setMode('test');}}>전체 표정 초기화</button><button type="button" onClick={()=>face.setMode('live')}>전체 채널 웹캠 연결</button></div><p>웹캠 연결 후 정면에서 무표정 보정을 해주세요. 혀 위치·방향은 이 출력에 포함되지 않아 수동 리그를 유지합니다.</p></details>;
}
