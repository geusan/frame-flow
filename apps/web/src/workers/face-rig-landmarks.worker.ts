/// <reference lib="webworker" />
import {FaceLandmarker,FilesetResolver} from '@mediapipe/tasks-vision';
const scope=self as DedicatedWorkerGlobalScope;
scope.onmessage=async(event:MessageEvent<{bitmap:ImageBitmap}>)=>{
  let detector:FaceLandmarker|null=null;
  try{
    const files=await FilesetResolver.forVisionTasks('/mediapipe/wasm');
    detector=await FaceLandmarker.createFromOptions(files,{baseOptions:{modelAssetPath:'/mediapipe/face_landmarker.task',delegate:'CPU'},runningMode:'IMAGE',numFaces:1,minFaceDetectionConfidence:.3,minFacePresenceConfidence:.3});
    const result=detector.detect(event.data.bitmap);
    if(!result.faceLandmarks[0])throw new Error('이 그림에서 얼굴을 찾지 못했습니다. 기준점을 직접 맞춰 주세요.');
    scope.postMessage({points:result.faceLandmarks[0].map(p=>[p.x,p.y])});
  }catch(error){scope.postMessage({error:error instanceof Error?error.message:'기준점 분석 실패'});}
  finally{event.data.bitmap.close();detector?.close();scope.close();}
};
