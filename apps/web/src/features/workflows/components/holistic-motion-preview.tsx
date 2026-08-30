"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Activity, Cpu, Eye, Hand, PersonStanding } from "lucide-react";

import {
  FINGER_DEFINITIONS,
  measureFingerMotion,
  type FingerKey,
  type FingerMotionFrame,
  type HandSide,
  type HolisticWorkerMessage,
  type MotionPreviewFrame,
  type MotionPreviewLandmark,
} from "@/lib/motion-preview";

const POSE_CONNECTIONS = [
  [11, 12], [11, 13], [13, 15], [12, 14], [14, 16], [11, 23], [12, 24], [23, 24],
  [23, 25], [25, 27], [27, 29], [29, 31], [24, 26], [26, 28], [28, 30], [30, 32],
] as const;
const PALM_CONNECTIONS = [[0, 1], [0, 5], [5, 9], [9, 13], [13, 17], [17, 0]] as const;
const FACE_CHAINS = [
  [10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288, 397, 365, 379, 378, 400, 377, 152, 148, 176, 149, 150, 136, 172, 58, 132, 93, 234, 127, 162, 21, 54, 103, 67, 109, 10],
  [33, 160, 158, 133, 153, 144, 33],
  [362, 385, 387, 263, 373, 380, 362],
  [61, 146, 91, 181, 84, 17, 314, 405, 321, 375, 291, 61],
] as const;

interface HolisticMotionPreviewProps {
  videoUrl?: string;
  sampleFps: number;
  minConfidence: number;
}

const drawChain = (
  context: CanvasRenderingContext2D,
  landmarks: MotionPreviewLandmark[],
  connections: readonly (readonly [number, number])[],
  color: string,
  width: number,
) => {
  context.strokeStyle = color;
  context.lineWidth = width;
  context.lineCap = "round";
  for (const [startIndex, endIndex] of connections) {
    const start = landmarks[startIndex];
    const end = landmarks[endIndex];
    if (!start || !end || (start.visibility ?? 1) < 0.2 || (end.visibility ?? 1) < 0.2) continue;
    context.beginPath();
    context.moveTo(start.x * context.canvas.width, start.y * context.canvas.height);
    context.lineTo(end.x * context.canvas.width, end.y * context.canvas.height);
    context.stroke();
  }
};

const drawFrame = (canvas: HTMLCanvasElement, frame: MotionPreviewFrame, width: number, height: number) => {
  if (!width || !height) return;
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext("2d");
  if (!context) return;
  context.clearRect(0, 0, width, height);
  drawChain(context, frame.pose, POSE_CONNECTIONS, "#6ff0e5", Math.max(2, width / 260));
  for (const [hand, palmColor] of [[frame.leftHand, "#ff88bc"], [frame.rightHand, "#d6ff6f"]] as const) {
    drawChain(context, hand, PALM_CONNECTIONS, palmColor, Math.max(2, width / 300));
    for (const finger of FINGER_DEFINITIONS) {
      const connections = finger.landmarks.slice(0, -1).map((index, position) => [index, finger.landmarks[position + 1]] as const);
      drawChain(context, hand, connections, finger.color, Math.max(3, width / 250));
      const tip = hand[finger.landmarks[3]];
      if (!tip) continue;
      context.beginPath();
      context.fillStyle = finger.color;
      context.arc(tip.x * width, tip.y * height, Math.max(4, width / 170), 0, Math.PI * 2);
      context.fill();
    }
  }
  for (const chain of FACE_CHAINS) {
    drawChain(context, frame.face, chain.slice(0, -1).map((index, position) => [index, chain[position + 1]] as const), "rgba(255,255,255,.72)", Math.max(1, width / 520));
  }
};

type FingerHistory = Record<HandSide, Record<FingerKey, number[]>>;

const createFingerHistory = (): FingerHistory => ({
  left: { thumb: [], index: [], middle: [], ring: [], pinky: [] },
  right: { thumb: [], index: [], middle: [], ring: [], pinky: [] },
});

const appendFingerHistory = (history: FingerHistory, motion: FingerMotionFrame): FingerHistory => ({
  left: Object.fromEntries(FINGER_DEFINITIONS.map((finger) => [
    finger.key,
    motion.left.detected ? [...history.left[finger.key], motion.left.fingers[finger.key].curl].slice(-24) : history.left[finger.key],
  ])) as Record<FingerKey, number[]>,
  right: Object.fromEntries(FINGER_DEFINITIONS.map((finger) => [
    finger.key,
    motion.right.detected ? [...history.right[finger.key], motion.right.fingers[finger.key].curl].slice(-24) : history.right[finger.key],
  ])) as Record<FingerKey, number[]>,
});

function FingerTrace({ values, color }: { values: number[]; color: string }) {
  const points = values.map((value, index) => {
    const x = values.length <= 1 ? 0 : index / (values.length - 1) * 64;
    const y = 17 - value * 16;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  return <svg className="finger-motion-trace" viewBox="0 0 64 18" preserveAspectRatio="none" aria-hidden="true">
    <line x1="0" y1="17" x2="64" y2="17" />
    {points && <polyline points={points} style={{ stroke: color }} />}
  </svg>;
}

function FingerMotionPanel({ motion, history }: { motion: FingerMotionFrame | null; history: FingerHistory }) {
  return <section className="holistic-finger-motion" aria-label="손가락별 움직임">
    <header><span><Hand size={13} /> Finger motion</span><small>굽힘 · 손 기준 속도</small></header>
    <div className="finger-motion-hands">
      {(["left", "right"] as const).map((side) => {
        const hand = motion?.[side];
        return <section className={`finger-motion-hand ${hand?.detected ? "detected" : "missing"}`} key={side} aria-label={`${side === "left" ? "왼손" : "오른손"} 손가락 움직임`}>
          <header><strong>{side === "left" ? "L · 왼손" : "R · 오른손"}</strong><small>{hand?.detected ? "21 points" : "미감지"}</small></header>
          {FINGER_DEFINITIONS.map((finger) => {
            const value = hand?.fingers[finger.key];
            const curlPercent = Math.round((value?.curl ?? 0) * 100);
            return <div className="finger-motion-row" key={finger.key}>
              <span><i style={{ background: finger.color }} /><b>{finger.label}</b></span>
              <FingerTrace values={history[side][finger.key]} color={finger.color} />
              <strong>{hand?.detected ? `${curlPercent}%` : "—"}</strong>
              <div className="finger-curl-meter" role="meter" aria-label={`${side === "left" ? "왼손" : "오른손"} ${finger.label} 굽힘`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={hand?.detected ? curlPercent : 0}><i style={{ width: `${curlPercent}%`, background: finger.color }} /></div>
              <small>{hand?.detected ? `${(value?.speed ?? 0).toFixed(1)}×/s` : "tracking gap"}</small>
            </div>;
          })}
        </section>;
      })}
    </div>
    <footer><span>0% 펴짐</span><span>100% 굽힘</span><span>×/s 손끝 상대 속도</span></footer>
  </section>;
}

export function HolisticMotionPreview({ videoUrl, sampleFps, minConfidence }: HolisticMotionPreviewProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const workerRef = useRef<Worker | null>(null);
  const readyRef = useRef(false);
  const busyRef = useRef(false);
  const lastDispatchRef = useRef(-Infinity);
  const animationRef = useRef<number | null>(null);
  const previousFrameRef = useRef<MotionPreviewFrame | null>(null);
  const [status, setStatus] = useState("Holistic model loading…");
  const [frame, setFrame] = useState<MotionPreviewFrame | null>(null);
  const [fingerMotion, setFingerMotion] = useState<FingerMotionFrame | null>(null);
  const [fingerHistory, setFingerHistory] = useState<FingerHistory>(createFingerHistory);

  const resetFingerMotion = useCallback(() => {
    previousFrameRef.current = null;
    lastDispatchRef.current = -Infinity;
    setFingerMotion(null);
    setFingerHistory(createFingerHistory());
  }, []);

  const processCurrentFrame = useCallback(async (force = false) => {
    const video = videoRef.current;
    const worker = workerRef.current;
    if (!video || !worker || !readyRef.current || busyRef.current || video.readyState < 2) return;
    const timestampMs = Math.round(video.currentTime * 1000);
    if (!force && timestampMs - lastDispatchRef.current < 1000 / Math.max(1, sampleFps)) return;
    busyRef.current = true;
    lastDispatchRef.current = timestampMs;
    try {
      const bitmap = await createImageBitmap(video);
      worker.postMessage({ type: "frame", bitmap, timestampMs }, [bitmap]);
    } catch (error) {
      busyRef.current = false;
      setStatus(error instanceof Error ? error.message : "Unable to read the video frame");
    }
  }, [sampleFps]);

  useEffect(() => {
    const worker = new Worker(new URL("../../../workers/holistic-preview.worker.ts", import.meta.url), { type: "module" });
    workerRef.current = worker;
    worker.onmessage = (event: MessageEvent<HolisticWorkerMessage>) => {
      if (event.data.type === "ready") {
        readyRef.current = true;
        setStatus(`Ready · ${event.data.delegate}`);
        void processCurrentFrame(true);
        return;
      }
      if (event.data.type === "frame") {
        busyRef.current = false;
        setFrame(event.data.frame);
        const nextFingerMotion = measureFingerMotion(event.data.frame, previousFrameRef.current);
        previousFrameRef.current = event.data.frame;
        setFingerMotion(nextFingerMotion);
        setFingerHistory((current) => appendFingerHistory(current, nextFingerMotion));
        const video = videoRef.current;
        const canvas = canvasRef.current;
        if (video && canvas) drawFrame(canvas, event.data.frame, video.videoWidth, video.videoHeight);
        setStatus("Tracking locally");
        return;
      }
      busyRef.current = false;
      setStatus(event.data.message);
    };
    worker.postMessage({
      type: "init",
      wasmRoot: "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@1.0.1/wasm",
      modelUrl: "https://storage.googleapis.com/mediapipe-models/holistic_landmarker/holistic_landmarker/float16/latest/holistic_landmarker.task",
      minConfidence,
    });
    return () => {
      if (animationRef.current !== null) cancelAnimationFrame(animationRef.current);
      worker.postMessage({ type: "close" });
      worker.terminate();
      workerRef.current = null;
      readyRef.current = false;
      previousFrameRef.current = null;
    };
  }, [minConfidence, processCurrentFrame]);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    const tick = () => {
      if (!video.paused && !video.ended) {
        void processCurrentFrame();
        animationRef.current = requestAnimationFrame(tick);
      }
    };
    const start = () => { if (animationRef.current === null) animationRef.current = requestAnimationFrame(tick); };
    const stop = () => {
      if (animationRef.current !== null) cancelAnimationFrame(animationRef.current);
      animationRef.current = null;
    };
    const inspect = () => { resetFingerMotion(); void processCurrentFrame(true); };
    video.addEventListener("play", start);
    video.addEventListener("pause", stop);
    video.addEventListener("ended", stop);
    video.addEventListener("loadeddata", inspect);
    video.addEventListener("seeked", inspect);
    return () => {
      stop();
      video.removeEventListener("play", start);
      video.removeEventListener("pause", stop);
      video.removeEventListener("ended", stop);
      video.removeEventListener("loadeddata", inspect);
      video.removeEventListener("seeked", inspect);
    };
  }, [processCurrentFrame, resetFingerMotion, videoUrl]);

  if (!videoUrl) return <div className="holistic-preview-empty"><PersonStanding size={22} /><span><strong>Connect a Video</strong><small>브라우저에서 Holistic 랜드마크를 미리 확인합니다.</small></span></div>;
  return <div className="holistic-preview">
    <div className="holistic-preview-stage">
      <video ref={videoRef} src={videoUrl} controls muted playsInline crossOrigin="anonymous" />
      <canvas ref={canvasRef} />
    </div>
    <div className="holistic-preview-status"><span><Activity size={13} />{status}</span><span><Cpu size={13} />Web Worker</span></div>
    <div className="holistic-preview-metrics">
      <span><PersonStanding size={13} /><b>{frame?.pose.length ? "Pose" : "—"}</b></span>
      <span><Eye size={13} /><b>{frame?.face.length ? "Face" : "—"}</b></span>
      <span><Hand size={13} /><b>{(frame?.leftHand.length ?? 0) + (frame?.rightHand.length ?? 0) ? "Hands" : "—"}</b></span>
    </div>
    <FingerMotionPanel motion={fingerMotion} history={fingerHistory} />
  </div>;
}
