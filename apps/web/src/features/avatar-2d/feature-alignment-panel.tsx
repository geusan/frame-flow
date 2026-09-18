"use client";
import {BrowDetailPanel} from "./brow-detail-panel";
import {DEFAULT_FEATURE_ALIGNMENT,FEATURE_LIMITS,type FeatureAlignment} from './feature-alignment';
import type {useFaceRigController} from './face-rig-controller';
import type {RigChannel} from './face-rig';
import styles from './face-rig-panel.module.css';
const controls:[keyof FeatureAlignment,string,number][]=[['browThickness','눈썹 두께',.01],['browWidth','눈썹 너비',.01],['leftBrowHeight','왼쪽 눈썹 높이',.25],['rightBrowHeight','오른쪽 눈썹 높이',.25],['browTilt','눈썹 안쪽 기울기',.25],['mouthWidth','입 너비',.01],['mouthHeight','입 높이',.25],['mouthOpening','입 벌림 비율',.01]];
const presets:{label:string;values:Partial<Record<RigChannel,number>>}[]=[{label:'눈썹 올리기',values:{browInnerUp:.8}},{label:'왼쪽 찡그리기',values:{browDownLeft:.8}},{label:'오른쪽 찡그리기',values:{browDownRight:.8}},{label:'미소',values:{mouthSmileLeft:.8,mouthSmileRight:.8}},{label:'입 벌림',values:{jawOpen:.65}},{label:'미소 + 입 벌림',values:{jawOpen:.65,mouthSmileLeft:.8,mouthSmileRight:.8}}];
export function FeatureAlignmentPanel({face}:{face:ReturnType<typeof useFaceRigController>}){
 return <details open><summary>본체 눈썹·입 맞추기</summary><p>눈썹은 새 투명 레이어로 분리되어 안쪽·중앙·바깥쪽 기준점을 따라 움직입니다. 앞머리는 고정되어 눈썹을 가립니다. 높이 값이 작을수록 위로 올라갑니다. 좌우는 캐릭터 기준입니다.</p>
 <label><span><input type="checkbox" aria-label="독립 눈썹 표시" checked={!!face.featureAlignment.browVisible} onChange={e=>face.setFeatureAlignment({...face.featureAlignment,browVisible:e.target.checked?1:0})}/> 독립 눈썹 표시</span></label>
 {controls.map(([key,label,step])=><label key={key}>{label}<span>{face.featureAlignment[key].toFixed(2)}</span><input aria-label={`본체 ${label}`} type="range" min={FEATURE_LIMITS[key][0]} max={FEATURE_LIMITS[key][1]} step={step} value={face.featureAlignment[key]} onChange={e=>face.setFeatureAlignment({...face.featureAlignment,[key]:Number(e.target.value)})}/></label>)}
 <div className={styles.actions}>{presets.map(p=><button type="button" key={p.label} onClick={()=>{face.clearTest();for(const [key,value]of Object.entries(p.values))face.test(key as RigChannel,value);}}>{p.label}</button>)}<button type="button" onClick={()=>{face.clearTest();face.setMode('test');}}>무표정 테스트</button><button type="button" onClick={()=>face.setMode('live')}>웹캠 표정으로 돌아가기</button></div>
 <BrowDetailPanel face={face}/>
 <button type="button" onClick={()=>face.setFeatureAlignment({...DEFAULT_FEATURE_ALIGNMENT})}>눈썹·입 배치 초기화</button><p>마음에 드는 배치는 아래 얼굴 리그 저장으로 보관하세요. 원본·표정 이미지의 세부 기준점은 아래 편집기에서 조정할 수 있습니다.</p></details>;
}
