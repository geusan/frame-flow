import {expressionRect,type ExpressionImage} from './expression-library';
import {MEDIAPIPE_FACE_POINTS,type FacePoints,type FacePointId} from './face-rig';

export async function inferFacePoints(entry:ExpressionImage,rest:FacePoints,signal:AbortSignal):Promise<FacePoints>{
  const image=new Image();image.src=entry.image;await image.decode();if(signal.aborted)throw new Error('분석 취소');
  const canvas=document.createElement('canvas');canvas.width=720;canvas.height=660;
  const rect=expressionRect(entry);canvas.getContext('2d')!.drawImage(image,(rect[0]-390)*3,(rect[1]-90)*3,rect[2]*3,rect[3]*3);
  const bitmap=await createImageBitmap(canvas);if(signal.aborted){bitmap.close();throw new Error('분석 취소');}
  const worker=new Worker(new URL('../../workers/face-rig-landmarks.worker.ts',import.meta.url),{type:'module'});
  const points=await new Promise<number[][]>((resolve,reject)=>{
    const finish=()=>{clearTimeout(timer);worker.terminate();signal.removeEventListener('abort',abort);};
    const abort=()=>{finish();reject(new Error('분석 취소'));};
    const timer=setTimeout(()=>{finish();reject(new Error('얼굴 기준점 분석 시간이 초과됐습니다.'));},45000);
    signal.addEventListener('abort',abort,{once:true});
    worker.onmessage=(e:MessageEvent<{points?:number[][];error?:string}>)=>{finish();if(e.data.error||!e.data.points)reject(new Error(e.data.error??'기준점 분석 실패'));else resolve(e.data.points);};
    worker.onerror=()=>{finish();reject(new Error('얼굴 기준점 분석을 시작하지 못했습니다.'));};
    worker.postMessage({bitmap},[bitmap]);
  });
  const result=structuredClone(rest);
  for(const [id,index]of Object.entries(MEDIAPIPE_FACE_POINTS)){const p=points[index!];if(p)result[id as FacePointId]=[390+p[0]*240,90+p[1]*220];}
  for(const side of ['left','right'] as const){
    const upper=result[`${side}EyeUpper`],lower=result[`${side}EyeLower`];if(lower[1]<upper[1]+.8)lower[1]=upper[1]+.8;
    if(lower[1]-upper[1]<3)result[`${side}Iris`]=[(result[`${side}EyeInner`][0]+result[`${side}EyeOuter`][0])/2,(upper[1]+lower[1])/2];
  }
  if(result.mouthInnerLower[1]<result.mouthInnerUpper[1]+.8)result.mouthInnerLower[1]=result.mouthInnerUpper[1]+.8;
  return result;
}
