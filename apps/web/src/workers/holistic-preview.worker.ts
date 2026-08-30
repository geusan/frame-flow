/// <reference lib="webworker" />

import { FilesetResolver, HolisticLandmarker, type HolisticLandmarkerResult, type NormalizedLandmark } from "@mediapipe/tasks-vision";

import type { HolisticWorkerMessage, MotionPreviewFrame, MotionPreviewLandmark } from "@/lib/motion-preview";

type IncomingMessage =
  | { type: "init"; wasmRoot: string; modelUrl: string; minConfidence: number }
  | { type: "frame"; bitmap: ImageBitmap; timestampMs: number }
  | { type: "close" };

const scope = self as DedicatedWorkerGlobalScope;
let landmarker: HolisticLandmarker | null = null;
let lastDetectorTimestampMs = -1;

const serializeLandmark = (landmark: NormalizedLandmark): MotionPreviewLandmark => ({
  x: landmark.x,
  y: landmark.y,
  z: landmark.z,
  visibility: landmark.visibility,
});

const serializeFrame = (result: HolisticLandmarkerResult, timestampMs: number): MotionPreviewFrame => {
  const blendshapeCategories = result.faceBlendshapes[0]?.categories ?? [];
  return {
    timestampMs,
    face: (result.faceLandmarks[0] ?? []).map(serializeLandmark),
    pose: (result.poseLandmarks[0] ?? []).map(serializeLandmark),
    leftHand: (result.leftHandLandmarks[0] ?? []).map(serializeLandmark),
    rightHand: (result.rightHandLandmarks[0] ?? []).map(serializeLandmark),
    blendshapes: Object.fromEntries(blendshapeCategories.map((item) => [item.categoryName, item.score])),
  };
};

const initialize = async (message: Extract<IncomingMessage, { type: "init" }>) => {
  const fileset = await FilesetResolver.forVisionTasks(message.wasmRoot);
  const options = {
    baseOptions: { modelAssetPath: message.modelUrl, delegate: "CPU" as const },
    runningMode: "VIDEO" as const,
    minFaceDetectionConfidence: message.minConfidence,
    minFacePresenceConfidence: message.minConfidence,
    minPoseDetectionConfidence: message.minConfidence,
    minPosePresenceConfidence: message.minConfidence,
    minHandLandmarksConfidence: message.minConfidence,
    outputFaceBlendshapes: true,
    outputPoseSegmentationMasks: false,
  };
  landmarker = await HolisticLandmarker.createFromOptions(fileset, options);
  lastDetectorTimestampMs = -1;
  scope.postMessage({ type: "ready", delegate: "CPU" } satisfies HolisticWorkerMessage);
};

scope.onmessage = async (event: MessageEvent<IncomingMessage>) => {
  const message = event.data;
  let frameClosed = false;
  try {
    if (message.type === "init") {
      await initialize(message);
      return;
    }
    if (message.type === "close") {
      landmarker?.close();
      landmarker = null;
      lastDetectorTimestampMs = -1;
      scope.close();
      return;
    }
    if (!landmarker) throw new Error("Holistic preview model is still loading");
    try {
      const detectorTimestampMs = Math.max(Math.round(performance.now()), lastDetectorTimestampMs + 1);
      lastDetectorTimestampMs = detectorTimestampMs;
      const result = landmarker.detectForVideo(message.bitmap, detectorTimestampMs);
      scope.postMessage({ type: "frame", frame: serializeFrame(result, message.timestampMs) } satisfies HolisticWorkerMessage);
    } finally {
      message.bitmap.close();
      frameClosed = true;
    }
  } catch (error) {
    if (message.type === "frame" && !frameClosed) message.bitmap.close();
    scope.postMessage({ type: "error", message: error instanceof Error ? error.message : "Holistic preview failed" } satisfies HolisticWorkerMessage);
  }
};
