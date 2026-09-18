/// <reference lib="webworker" />

import { FaceLandmarker, FilesetResolver } from "@mediapipe/tasks-vision";
import type { FaceFrame } from "@/features/live-avatar/face-state";

const scope = self as DedicatedWorkerGlobalScope;
let detector: FaceLandmarker | null = null;
scope.onmessage = async (event: MessageEvent<{ type: "init" | "frame"; bitmap?: ImageBitmap; timestamp?: number }>) => {
  const { type, bitmap, timestamp } = event.data;
  try {
    if (type === "init") {
      const files = await FilesetResolver.forVisionTasks("/mediapipe/wasm");
      detector = await FaceLandmarker.createFromOptions(files, {
        baseOptions: { modelAssetPath: "/mediapipe/face_landmarker.task", delegate: "CPU" },
        runningMode: "VIDEO", numFaces: 1,
        outputFaceBlendshapes: true, outputFacialTransformationMatrixes: true,
        minFaceDetectionConfidence: .5, minFacePresenceConfidence: .5, minTrackingConfidence: .5,
      });
      scope.postMessage({ type: "ready" });
    } else if (bitmap && detector) {
      const result = detector.detectForVideo(bitmap, timestamp!);
      const frame: FaceFrame = {
        timestamp: timestamp!, detected: result.faceLandmarks.length > 0,
        values: Object.fromEntries((result.faceBlendshapes[0]?.categories ?? []).map((v) => [v.categoryName, v.score])),
        landmarks: (result.faceLandmarks[0] ?? []).map(p => [p.x, p.y, p.z]),
        matrix: result.facialTransformationMatrixes[0]?.data ?? [],
      };
      scope.postMessage({ type: "frame", frame });
    }
  } catch (error) {
    scope.postMessage({ type: "error", message: error instanceof Error ? error.message : "얼굴 추적을 시작할 수 없습니다." });
  } finally {
    bitmap?.close();
  }
};
