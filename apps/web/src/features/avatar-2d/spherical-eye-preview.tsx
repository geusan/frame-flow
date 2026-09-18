"use client";
import {useEffect,useRef} from 'react';
import {EYE_FRONT_CENTER} from './eye-projection';
import {LeftEyeRenderer,type EyeAppearance} from './left-eye-renderer';
import type {RigFaceValues} from './face-rig';
import styles from './left-eye-lab.module.css';
export function SphericalEyePreview({values,appearance,guides}:{values:RigFaceValues;appearance:EyeAppearance;guides:boolean}){
 const canvas=useRef<HTMLCanvasElement>(null),engine=useRef<LeftEyeRenderer|null>(null);
 useEffect(()=>{let active=true;engine.current??=new LeftEyeRenderer();const renderer=engine.current;void renderer.load().then(()=>{if(!active||!canvas.current)return;const image=renderer.render(values,appearance);if(!image)return;const ctx=canvas.current.getContext('2d')!;ctx.clearRect(0,0,500,300);ctx.drawImage(image,0,0);if(guides){ctx.strokeStyle='#8060b5';ctx.setLineDash([4,4]);ctx.beginPath();ctx.ellipse(EYE_FRONT_CENTER.x/2,EYE_FRONT_CENTER.y/2,175,145,0,0,Math.PI*2);ctx.stroke();ctx.setLineDash([]);ctx.fillStyle='#8060b5';ctx.fillRect(EYE_FRONT_CENTER.x/2-3,EYE_FRONT_CENTER.y/2-3,6,6);}}).catch(()=>{if(canvas.current)canvas.current.dataset.error='눈 텍스처 로딩 실패';});return()=>{active=false;};},[values,appearance,guides]);
 return <canvas ref={canvas} className={styles.eye} width={500} height={300} aria-label="분리 레이어 왼쪽 눈 미리보기" data-blink={values.eyeBlinkLeft.toFixed(3)} data-gaze-x={(values.eyeLookOutLeft-values.eyeLookInLeft).toFixed(3)}/>;
}
