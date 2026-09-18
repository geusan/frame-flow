"use client";
import {useCallback,useEffect,useRef,useState,type RefObject} from 'react';
import {freshMouthRig,parseMouthRig} from './mouth-rig';
import {freshEyelidRig,parseEyelidRig} from './eyelid-rig';
import {freshBrowDetail,parseBrowDetail} from './brow-detail';
import {DEFAULT_FEATURE_ALIGNMENT,parseFeatureAlignment} from './feature-alignment';
import {DEFAULT_EYE} from './left-eye-renderer';
import type {PuppetScene} from './puppet-scene';
import {EXPRESSION_SOURCE_SHA,freshExpressions,saveExpressions,type ExpressionImage,type ExpressionLibrary} from './expression-library';
import {FaceRigCapture,freshFaceRig,parseFaceRig,neutralRigFace,smoothRigFace,type FaceRig2D,type RigChannel,type FaceMotionChannel} from './face-rig';
import type {Landmark,PerformanceFrame} from './rig';

export type FaceRigMode='live'|'test'|'reference';
const KEY='frameflow.face-rig2d.v1.cat-2d-v1';
const MOUTH_KEY='frameflow.mouth-rig.v1';
const LID_KEY='frameflow.eyelid-rig.v1';
const BROW_KEY='frameflow.brow-detail.v1';
const FEATURE_KEY='frameflow.feature-alignment.v1';
const EYE_KEY='frameflow.left-eye-appearance.v1';
export function useFaceRigController(scene:RefObject<PuppetScene|null>,ready:boolean){
  const [mouthRig,setMouthRig]=useState(freshMouthRig);
  const [eyelidRig,setEyelidRig]=useState(freshEyelidRig);
  const [browDetail,setBrowDetail]=useState(freshBrowDetail);
  const [featureAlignment,setFeatureAlignment]=useState({...DEFAULT_FEATURE_ALIGNMENT});
  const landmarks=useRef<Landmark[]>([]);
  const [eyeAppearance,setEyeAppearance]=useState({...DEFAULT_EYE});
  const [showMesh,setShowMesh]=useState(false);
  const [profile,setProfileState]=useState(()=>freshFaceRig(EXPRESSION_SOURCE_SHA));
  const profileRef=useRef(profile),capture=useRef(new FaceRigCapture()),values=useRef(neutralRigFace()),manual=useRef(neutralRigFace());
  const [manualValues,setManualValues]=useState(neutralRigFace);
  const [library,setLibrary]=useState<ExpressionLibrary>(freshExpressions),[mode,setModeState]=useState<FaceRigMode>('live'),modeRef=useRef<FaceRigMode>('live');
  const [telemetry,setTelemetry]=useState({values:neutralRigFace(),landmarks:[] as Landmark[],raw:{} as Record<string,number>,detected:false,progress:0,calibrating:false,message:'웹캠을 연결하고 무표정을 보정하세요.',limited:false});
  const lastUi=useRef(0),[error,setError]=useState(''),[loaded,setLoaded]=useState(false);
  const setProfile=useCallback((next:FaceRig2D)=>{const valid=parseFaceRig(next,EXPRESSION_SOURCE_SHA);profileRef.current=valid;setProfileState(valid);setError('');},[]);
  useEffect(()=>{let active=true;void Promise.resolve().then(()=>{if(!active)return;try{const saved=localStorage.getItem(KEY);if(saved)setProfile(parseFaceRig(JSON.parse(saved),EXPRESSION_SOURCE_SHA));setMouthRig(parseMouthRig(JSON.parse(localStorage.getItem(MOUTH_KEY)??'null')));setEyelidRig(parseEyelidRig(JSON.parse(localStorage.getItem(LID_KEY)??'null')));setBrowDetail(parseBrowDetail(JSON.parse(localStorage.getItem(BROW_KEY)??'null')));setFeatureAlignment(parseFeatureAlignment(JSON.parse(localStorage.getItem(FEATURE_KEY)??'null')));const eye=JSON.parse(localStorage.getItem(EYE_KEY)??'null');if(eye&&typeof eye.enabled==='boolean'&&Number.isFinite(eye.size)&&eye.size>=.6&&eye.size<=1.4&&Number.isFinite(eye.pupil)&&eye.pupil>=.12&&eye.pupil<=.75)setEyeAppearance({enabled:eye.enabled,size:eye.size,pupil:eye.pupil,spacing:Number.isFinite(eye.spacing)?Math.max(.8,Math.min(1.15,eye.spacing)):.94,focusDistance:Number.isFinite(eye.focusDistance)?Math.max(20,Math.min(200,eye.focusDistance)):60});}catch{setError('저장된 얼굴 리그를 읽지 못해 기본 기준점을 열었습니다.');}setLoaded(true);});return()=>{active=false;};},[setProfile]);
  useEffect(()=>{if(!ready||!loaded)return;let active=true;void scene.current?.configureFaceRig(profile,library).then(()=>{if(active){scene.current?.setLiveFace(modeRef.current!=='reference');scene.current?.setFaceRigDebug(showMesh);scene.current?.setLeftEyeAppearance(eyeAppearance);scene.current?.setFeatureAlignment(featureAlignment);scene.current?.setBrowDetail(browDetail);scene.current?.setEyelidRig(eyelidRig);scene.current?.setMouthRig(mouthRig);setError('');}}).catch(e=>{if(active)setError(e instanceof Error?e.message:'얼굴 리그 준비 실패');});return()=>{active=false;};},[ready,loaded,profile,library,scene,showMesh,eyeAppearance,featureAlignment,browDetail,eyelidRig,mouthRig]);
  const setMode=useCallback((next:FaceRigMode)=>{modeRef.current=next;setModeState(next);manual.current=neutralRigFace();setManualValues(manual.current);scene.current?.setLiveFace(next!=='reference');if(next==='reference'){const entry=library.entries.find(e=>e.id===library.selected);if(entry)void scene.current?.setExpression(entry,library.strength,library.transition_ms).catch(()=>setError('제작 자료 이미지를 표시하지 못했습니다.'));}},[scene,library]);
  const receive=useCallback((frame:PerformanceFrame,now:number)=>{
    landmarks.current=frame.faceDetected===false?[]:frame.faceLandmarks??[];
    const changed=capture.current.receive(frame.expressions??{},frame.faceDetected??(frame.faceLandmarks?.length??0)>=400,now,profileRef.current);
    if(changed)setProfile({...profileRef.current,channels:{...profileRef.current.channels,...changed}});
  },[setProfile]);
  const tick=useCallback((now:number,dt:number)=>{
    const target=modeRef.current==='live'?capture.current.target(now,profileRef.current):modeRef.current==='test'?manual.current:neutralRigFace();
    values.current=smoothRigFace(values.current,target,dt,profileRef.current.smoothing);scene.current?.setFaceRigValues(values.current);
    if(now-lastUi.current>90){lastUi.current=now;setTelemetry({values:values.current,landmarks:now-capture.current.lastSeen<500?landmarks.current:[],raw:capture.current.raw,detected:capture.current.detected&&now-capture.current.lastSeen<500,progress:capture.current.samples?.length??0,calibrating:!!capture.current.samples,message:capture.current.message,limited:scene.current?.faceRigLimited??false});}
  },[scene]);
  const test=useCallback((key:FaceMotionChannel,value:number)=>{modeRef.current='test';setModeState('test');scene.current?.setLiveFace(true);manual.current={...manual.current,[key]:Math.max(0,Math.min(1,value))};setManualValues(manual.current);},[scene]);
  const clearTest=useCallback(()=>{manual.current=neutralRigFace();setManualValues(manual.current);values.current=neutralRigFace();scene.current?.setFaceRigValues(values.current);},[scene]);
  const resetCapture=useCallback(()=>{capture.current.reset();landmarks.current=[];},[]);
  const calibrate=useCallback((key:'neutral'|RigChannel)=>{capture.current.begin(key,performance.now());},[]);
  const preview=useCallback(async(entry:ExpressionImage,strength:number,duration:number)=>{if(modeRef.current==='reference')await scene.current?.setExpression(entry,strength,duration);},[scene]);
  const save=useCallback(async()=>{await saveExpressions(library);localStorage.setItem(KEY,JSON.stringify(parseFaceRig(profileRef.current,EXPRESSION_SOURCE_SHA)));localStorage.setItem(EYE_KEY,JSON.stringify(eyeAppearance));localStorage.setItem(MOUTH_KEY,JSON.stringify(parseMouthRig(mouthRig)));localStorage.setItem(LID_KEY,JSON.stringify(parseEyelidRig(eyelidRig)));localStorage.setItem(BROW_KEY,JSON.stringify(parseBrowDetail(browDetail)));localStorage.setItem(FEATURE_KEY,JSON.stringify(parseFeatureAlignment(featureAlignment)));},[library,eyeAppearance,featureAlignment,browDetail,eyelidRig,mouthRig]);
  return {mouthRig,setMouthRig,eyelidRig,setEyelidRig,browDetail,setBrowDetail,featureAlignment,setFeatureAlignment,eyeAppearance,setEyeAppearance,showMesh,setShowMesh,profile,setProfile,library,setLibrary,mode,setMode,telemetry,manualValues,error,receive,tick,test,clearTest,resetCapture,calibrate,preview,save};
}
