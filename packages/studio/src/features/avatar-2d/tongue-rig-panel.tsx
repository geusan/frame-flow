"use client";
import {neutralTongue,parseTongue,type TonguePose} from './mouth-rig';
import type {useFaceRigController} from './face-rig-controller';
import styles from './face-rig-panel.module.css';
const presets:{name:string;pose:TonguePose}[]=[{name:'혀 내밀기',pose:{x:0,y:0,out:.9,curl:0}},{name:'혀 왼쪽',pose:{x:1,y:0,out:.6,curl:0}},{name:'혀 오른쪽',pose:{x:-1,y:0,out:.6,curl:0}},{name:'혀 위로',pose:{x:0,y:-1,out:.3,curl:.6}},{name:'혀 아래로',pose:{x:0,y:1,out:.6,curl:0}}];
export function TongueRigPanel({face}:{face:ReturnType<typeof useFaceRigController>}){const pose=parseTongue(face.mouthRig.tonguePose);
 return <details open aria-label="혀 리그"><summary>혀 리그 · 수동 조절</summary><p>혀의 위치와 길이는 수동 설정입니다. 웹캠은 입 열림만 연결하며, 입을 다물면 혀가 가려집니다. 좌우는 캐릭터 기준입니다.</p>
 {([['out','혀 내밀기 정도',0,1],['x','혀 좌우 위치',-1,1],['y','혀 상하 위치',-1,1],['curl','혀끝 말기',-1,1]] as const).map(([key,label,min,max])=><label key={key}>{label} · {pose[key].toFixed(2)}<input aria-label={label} type="range" min={min} max={max} step=".01" value={pose[key]} onChange={e=>face.setMouthRig({...face.mouthRig,tongue:true,tonguePose:{...pose,[key]:Number(e.target.value)}})}/></label>)}
 <div className={styles.actions}>{presets.map(p=><button key={p.name} type="button" onClick={()=>{face.clearTest();face.setMode('test');face.test('jawOpen',.65);face.setMouthRig({...face.mouthRig,tongue:true,tonguePose:p.pose});}}>{p.name}</button>)}<button type="button" onClick={()=>face.setMouthRig({...face.mouthRig,tonguePose:neutralTongue()})}>혀 위치 초기화</button></div><p>테스트 버튼은 입을 벌린 상태로 실행합니다. 얼굴 리그 저장으로 설정을 보관할 수 있습니다.</p></details>;
}
