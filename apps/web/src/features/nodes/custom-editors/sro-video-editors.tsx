"use client";

import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import type { Edge } from "@xyflow/react";
import { ArrowRight, Crosshair, Frame, Move, Pause, Play, Scan, ZoomIn } from "lucide-react";

import { NativeSelect } from "@/components/ui/native-select";
import type { StudioFlowNode } from "@/lib/canvas-model";
import type { NodeCustomEditorProps } from "@/features/nodes/custom-editors/registry";


type MotionKeyframe = "start" | "end";
type MotionTransform = { scale: number; x: number; y: number };
type MotionPoint = { x: number; y: number };
type MotionPathPointKey = "start" | "control_1" | "control_2" | "end";

interface MotionPathValue {
  start: MotionTransform;
  control1: MotionPoint;
  control2: MotionPoint;
  end: MotionTransform;
}

interface MotionPreviewFrame {
  ratio: string;
  background: string;
  rect: FrameRect;
}

interface MotionDragGesture {
  pointerId: number;
  clientX: number;
  clientY: number;
}

interface MotionPathGesture {
  pointerId: number;
  point: MotionPathPointKey;
  initial: MotionPoint;
}

type FrameResizeHandle = "north-west" | "north-east" | "south-west" | "south-east";
type FrameRect = { x: number; y: number; width: number; height: number };

interface FramePointerGesture {
  pointerId: number;
  mode: "move" | FrameResizeHandle;
  clientX: number;
  clientY: number;
  initial: FrameRect;
}


function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, value));
}


function numberConfig(node: StudioFlowNode, key: string, fallback: number): number {
  const value = Number(node.data.config?.[key] ?? fallback);
  return Number.isFinite(value) ? value : fallback;
}

function stringConfig(node: StudioFlowNode, key: string, fallback: string): string {
  return String(node.data.config?.[key] ?? fallback);
}

function updateConfig(props: NodeCustomEditorProps, patch: Record<string, string | number>) {
  props.onChange({
    config: { ...(props.node.data.config ?? {}), ...patch },
    status: props.node.data.output || props.node.data.outputArtifactIds?.length ? "STALE" : props.node.data.status,
  });
}

function incomingNodes(node: StudioFlowNode, nodes: StudioFlowNode[], edges: Edge[]): StudioFlowNode[] {
  return edges
    .filter((edge) => edge.target === node.id)
    .map((edge) => nodes.find((candidate) => candidate.id === edge.source))
    .filter((candidate): candidate is StudioFlowNode => Boolean(candidate));
}

function connectedImage(props: NodeCustomEditorProps): StudioFlowNode | undefined {
  const direct = incomingNodes(props.node, props.nodes, props.edges);
  const image = direct.find((candidate) => candidate.data.outputType === "Image");
  if (image) return image;
  const motion = direct.find((candidate) => candidate.data.outputType === "MediaMotion");
  return motion
    ? incomingNodes(motion, props.nodes, props.edges).find((candidate) => candidate.data.outputType === "Image")
    : undefined;
}

function connectedMotionPreviewFrame(props: NodeCustomEditorProps): MotionPreviewFrame | undefined {
  const frameApplyIds = new Set(
    props.edges
      .filter((edge) => edge.source === props.node.id)
      .map((edge) => edge.target)
      .filter((nodeId) => props.nodes.some((node) => node.id === nodeId && node.data.key === "video.frame_apply")),
  );
  const mediaFrameNode = props.edges
    .filter((edge) => frameApplyIds.has(edge.target))
    .map((edge) => props.nodes.find((node) => node.id === edge.source))
    .find((node): node is StudioFlowNode => Boolean(node?.data.outputType === "MediaFrame"));
  if (!mediaFrameNode) return undefined;
  return {
    ratio: stringConfig(mediaFrameNode, "aspect_ratio", "9:16"),
    background: stringConfig(mediaFrameNode, "background_color", "#11100E"),
    rect: {
      x: numberConfig(mediaFrameNode, "frame_x", 0.04),
      y: numberConfig(mediaFrameNode, "frame_y", 0.02),
      width: numberConfig(mediaFrameNode, "frame_width", 0.92),
      height: numberConfig(mediaFrameNode, "frame_height", 0.62),
    },
  };
}

function RangeField({ label, value, min, max, step, suffix, onChange }: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  suffix?: string;
  onChange: (value: number) => void;
}) {
  return <label className="sro-range-field">
    <span>{label}<b>{value.toFixed(step <= 0.01 ? 2 : 1)}{suffix}</b></span>
    <input type="range" min={min} max={max} step={step} value={value} onChange={(event) => onChange(Number(event.target.value))} />
  </label>;
}

function TimingField({ label, value, durationSeconds, onChange }: {
  label: string;
  value: number;
  durationSeconds: number;
  onChange: (value: number) => void;
}) {
  return <label className="sro-range-field motion-timing-field">
    <span>{label}<b>{(durationSeconds * value).toFixed(1)}s · {Math.round(value * 100)}%</b></span>
    <input type="range" min={0.05} max={1} step={0.01} value={value} onChange={(event) => onChange(Number(event.target.value))} />
  </label>;
}

function MotionPreview({ url, label, scale, x, y, active, onSelect, onCommit }: {
  url?: string;
  label: string;
  scale: number;
  x: number;
  y: number;
  active: boolean;
  onSelect: () => void;
  onCommit: (value: MotionTransform) => void;
}) {
  const stageRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<MotionDragGesture | null>(null);
  const wheelTimerRef = useRef<number | null>(null);
  const valueRef = useRef<MotionTransform>({ scale, x, y });
  const commitRef = useRef(onCommit);
  const selectRef = useRef(onSelect);
  const [draft, setDraft] = useState<MotionTransform>({ scale, x, y });
  const [dragging, setDragging] = useState(false);

  useEffect(() => {
    commitRef.current = onCommit;
    selectRef.current = onSelect;
  }, [onCommit, onSelect]);

  useEffect(() => {
    if (dragRef.current || wheelTimerRef.current !== null) return;
    const next = { scale, x, y };
    valueRef.current = next;
    setDraft(next);
  }, [scale, x, y]);

  useEffect(() => {
    const stage = stageRef.current;
    if (!stage || !url) return;
    const handleWheel = (event: WheelEvent) => {
      event.preventDefault();
      event.stopPropagation();
      selectRef.current();
      const pixels = event.deltaMode === WheelEvent.DOM_DELTA_LINE ? event.deltaY * 16 : event.deltaY;
      const sensitivity = event.ctrlKey ? 0.012 : 0.0022;
      const next = {
        ...valueRef.current,
        scale: clamp(valueRef.current.scale * Math.exp(-pixels * sensitivity), 1, 2),
      };
      valueRef.current = next;
      setDraft(next);
      if (wheelTimerRef.current !== null) window.clearTimeout(wheelTimerRef.current);
      wheelTimerRef.current = window.setTimeout(() => {
        wheelTimerRef.current = null;
        commitRef.current(valueRef.current);
      }, 180);
    };
    stage.addEventListener("wheel", handleWheel, { passive: false });
    return () => {
      stage.removeEventListener("wheel", handleWheel);
      if (wheelTimerRef.current !== null) window.clearTimeout(wheelTimerRef.current);
      wheelTimerRef.current = null;
    };
  }, [url]);

  const beginDrag = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!url) return;
    event.preventDefault();
    event.stopPropagation();
    selectRef.current();
    dragRef.current = { pointerId: event.pointerId, clientX: event.clientX, clientY: event.clientY };
    event.currentTarget.setPointerCapture(event.pointerId);
    setDragging(true);
  };

  const moveImage = (event: ReactPointerEvent<HTMLDivElement>) => {
    const gesture = dragRef.current;
    const stage = stageRef.current;
    if (!gesture || gesture.pointerId !== event.pointerId || !stage) return;
    event.preventDefault();
    event.stopPropagation();
    const rect = stage.getBoundingClientRect();
    const deltaX = event.clientX - gesture.clientX;
    const deltaY = event.clientY - gesture.clientY;
    gesture.clientX = event.clientX;
    gesture.clientY = event.clientY;
    const panScale = Math.max(0.3, valueRef.current.scale - 1);
    const next = {
      ...valueRef.current,
      x: clamp(valueRef.current.x - deltaX / Math.max(1, rect.width) / panScale, 0, 1),
      y: clamp(valueRef.current.y - deltaY / Math.max(1, rect.height) / panScale, 0, 1),
    };
    valueRef.current = next;
    setDraft(next);
  };

  const finishDrag = (event: ReactPointerEvent<HTMLDivElement>) => {
    const gesture = dragRef.current;
    if (!gesture || gesture.pointerId !== event.pointerId) return;
    event.preventDefault();
    event.stopPropagation();
    dragRef.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
    setDragging(false);
    commitRef.current(valueRef.current);
  };

  return <button type="button" className={`motion-keyframe-card ${active ? "active" : ""}`} onClick={onSelect} aria-label={`${label} motion keyframe`}>
    <span>{label}<b>{draft.scale.toFixed(2)}×</b></span>
    <div
      ref={stageRef}
      className={`motion-keyframe-stage ${dragging ? "dragging" : ""}`}
      onPointerDown={beginDrag}
      onPointerMove={moveImage}
      onPointerUp={finishDrag}
      onPointerCancel={finishDrag}
    >
      {url ? <div className="motion-keyframe-image" style={{ backgroundImage: `url(${url})`, backgroundSize: `${draft.scale * 100}%`, backgroundPosition: `${draft.x * 100}% ${draft.y * 100}%` }} /> : <div className="motion-keyframe-empty"><Scan size={20} /><small>Image를 연결하세요</small></div>}
      <i className="motion-fixed-focus"><Crosshair size={13} /></i>
      {url && <em><Move size={11} /> drag · wheel / pinch</em>}
    </div>
    <small>IMAGE X {Math.round((1 - draft.x) * 100)} · Y {Math.round((1 - draft.y) * 100)}</small>
  </button>;
}

function cubicBezierPoint(start: MotionPoint, control1: MotionPoint, control2: MotionPoint, end: MotionPoint, progress: number): MotionPoint {
  const inverse = 1 - progress;
  return {
    x: inverse ** 3 * start.x + 3 * inverse ** 2 * progress * control1.x + 3 * inverse * progress ** 2 * control2.x + progress ** 3 * end.x,
    y: inverse ** 3 * start.y + 3 * inverse ** 2 * progress * control1.y + 3 * inverse * progress ** 2 * control2.y + progress ** 3 * end.y,
  };
}

function linearMotionPoint(start: MotionPoint, end: MotionPoint, progress: number): MotionPoint {
  return {
    x: start.x + (end.x - start.x) * progress,
    y: start.y + (end.y - start.y) * progress,
  };
}

function easedMotionProgress(progress: number, easing: string): number {
  if (easing === "ease_in") return progress ** 2;
  if (easing === "ease_out") return 1 - (1 - progress) ** 2;
  if (easing === "ease_in_out") return progress ** 2 * (3 - 2 * progress);
  return progress;
}

function cameraCropRegion(point: MotionPoint, scale: number, sourceAspect: number, frame?: MotionPreviewFrame): FrameRect {
  const canvasAspect = frame?.ratio === "16:9" ? 16 / 9 : frame?.ratio === "1:1" ? 1 : 9 / 16;
  const frameAspect = frame ? canvasAspect * frame.rect.width / frame.rect.height : sourceAspect;
  const baseWidth = sourceAspect > frameAspect ? frameAspect / sourceAspect : 1;
  const baseHeight = sourceAspect > frameAspect ? 1 : sourceAspect / frameAspect;
  const baseX = (1 - baseWidth) / 2;
  const baseY = (1 - baseHeight) / 2;
  const width = baseWidth / Math.max(1, scale);
  const height = baseHeight / Math.max(1, scale);
  return {
    x: baseX + point.x * (baseWidth - width),
    y: baseY + point.y * (baseHeight - height),
    width,
    height,
  };
}

function cameraRegionCenter(region: FrameRect): MotionPoint {
  return { x: region.x + region.width / 2, y: region.y + region.height / 2 };
}

function cameraCropRegionFromCenter(center: MotionPoint, scale: number, sourceAspect: number, frame?: MotionPreviewFrame): FrameRect {
  const canvasAspect = frame?.ratio === "16:9" ? 16 / 9 : frame?.ratio === "1:1" ? 1 : 9 / 16;
  const frameAspect = frame ? canvasAspect * frame.rect.width / frame.rect.height : sourceAspect;
  const baseWidth = sourceAspect > frameAspect ? frameAspect / sourceAspect : 1;
  const baseHeight = sourceAspect > frameAspect ? 1 : sourceAspect / frameAspect;
  const width = baseWidth / Math.max(1, scale);
  const height = baseHeight / Math.max(1, scale);
  const clampedCenter = {
    x: clamp(center.x, width / 2, 1 - width / 2),
    y: clamp(center.y, height / 2, 1 - height / 2),
  };
  return { x: clampedCenter.x - width / 2, y: clampedCenter.y - height / 2, width, height };
}

function cameraFocusForCenter(center: MotionPoint, scale: number, sourceAspect: number, frame?: MotionPreviewFrame): MotionPoint {
  const canvasAspect = frame?.ratio === "16:9" ? 16 / 9 : frame?.ratio === "1:1" ? 1 : 9 / 16;
  const frameAspect = frame ? canvasAspect * frame.rect.width / frame.rect.height : sourceAspect;
  const baseWidth = sourceAspect > frameAspect ? frameAspect / sourceAspect : 1;
  const baseHeight = sourceAspect > frameAspect ? 1 : sourceAspect / frameAspect;
  const baseX = (1 - baseWidth) / 2;
  const baseY = (1 - baseHeight) / 2;
  const width = baseWidth / Math.max(1, scale);
  const height = baseHeight / Math.max(1, scale);
  const horizontalTravel = baseWidth - width;
  const verticalTravel = baseHeight - height;
  return {
    x: horizontalTravel > 0.000001 ? clamp((center.x - baseX - width / 2) / horizontalTravel, 0, 1) : 0.5,
    y: verticalTravel > 0.000001 ? clamp((center.y - baseY - height / 2) / verticalTravel, 0, 1) : 0.5,
  };
}

function pathPoint(value: MotionPathValue, key: MotionPathPointKey): MotionPoint {
  if (key === "start") return value.start;
  if (key === "control_1") return value.control1;
  if (key === "control_2") return value.control2;
  return value.end;
}

function replacePathPoint(value: MotionPathValue, key: MotionPathPointKey, point: MotionPoint): MotionPathValue {
  if (key === "start") return { ...value, start: { ...value.start, ...point } };
  if (key === "control_1") return { ...value, control1: point };
  if (key === "control_2") return { ...value, control2: point };
  return { ...value, end: { ...value.end, ...point } };
}

function MotionPathEditor({ url, value, pathType, pathEndProgress, zoomEndProgress, zoomEasing, durationSeconds, previewFrame, centerCoordinates, onCommit }: {
  url?: string;
  value: MotionPathValue;
  pathType: string;
  pathEndProgress: number;
  zoomEndProgress: number;
  zoomEasing: string;
  durationSeconds: number;
  previewFrame?: MotionPreviewFrame;
  centerCoordinates: boolean;
  onCommit: (value: MotionPathValue) => void;
}) {
  const stageRef = useRef<HTMLDivElement>(null);
  const gestureRef = useRef<MotionPathGesture | null>(null);
  const valueRef = useRef(value);
  const commitRef = useRef(onCommit);
  const animationRef = useRef<number | null>(null);
  const animationStartRef = useRef(0);
  const previewProgressRef = useRef(0);
  const [draft, setDraft] = useState(value);
  const [selectedPoint, setSelectedPoint] = useState<MotionPathPointKey>("control_1");
  const [previewProgress, setPreviewProgress] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [sourceAspect, setSourceAspect] = useState(9 / 16);
  const previewDurationMs = Math.max(0.5, durationSeconds) * 1000;
  const coordinates = [
    { key: "start" as const, label: "S", className: "start" },
    ...(pathType === "cubic_bezier" ? [
      { key: "control_1" as const, label: "1", className: "control control-1" },
      { key: "control_2" as const, label: "2", className: "control control-2" },
    ] : []),
    { key: "end" as const, label: "H", className: "end hold" },
  ];
  const { start, control1, control2, end } = value;

  useEffect(() => {
    commitRef.current = onCommit;
  }, [onCommit]);

  useEffect(() => {
    if (!url) return;
    let active = true;
    const source = new window.Image();
    source.onload = () => {
      if (active && source.naturalWidth > 0 && source.naturalHeight > 0) setSourceAspect(source.naturalWidth / source.naturalHeight);
    };
    source.src = url;
    return () => { active = false; };
  }, [url]);

  useEffect(() => {
    if (gestureRef.current) return;
    const next = { start, control1, control2, end };
    valueRef.current = next;
    setDraft(next);
  }, [start, control1, control2, end]);

  useEffect(() => {
    if (!playing) return;
    animationStartRef.current = performance.now();
    previewProgressRef.current = 0;
    const tick = (timestamp: number) => {
      const next = clamp((timestamp - animationStartRef.current) / previewDurationMs, 0, 1);
      previewProgressRef.current = next;
      setPreviewProgress(next);
      if (next >= 1) {
        setPlaying(false);
        previewProgressRef.current = 0;
        setPreviewProgress(0);
        animationRef.current = null;
        return;
      }
      animationRef.current = window.requestAnimationFrame(tick);
    };
    animationRef.current = window.requestAnimationFrame(tick);
    return () => {
      if (animationRef.current !== null) window.cancelAnimationFrame(animationRef.current);
      animationRef.current = null;
    };
  }, [playing, previewDurationMs]);

  const beginPointDrag = (event: ReactPointerEvent<HTMLButtonElement>, point: MotionPathPointKey) => {
    event.preventDefault();
    event.stopPropagation();
    setPlaying(false);
    setSelectedPoint(point);
    gestureRef.current = { pointerId: event.pointerId, point, initial: pathPoint(valueRef.current, point) };
    stageRef.current?.setPointerCapture(event.pointerId);
  };

  const referenceScaleForPoint = (point: MotionPathPointKey) => {
    if (point === "start") return draft.start.scale;
    if (point === "end") return draft.end.scale;
    const pathFraction = point === "control_1" ? 1 / 3 : 2 / 3;
    const timelineProgress = pathEndProgress * pathFraction;
    const scaleProgress = easedMotionProgress(clamp(timelineProgress / Math.max(0.05, zoomEndProgress), 0, 1), zoomEasing);
    return draft.start.scale + (draft.end.scale - draft.start.scale) * scaleProgress;
  };

  const cropRegionFor = (point: MotionPoint, scale: number) => centerCoordinates
    ? cameraCropRegionFromCenter(point, scale, sourceAspect, previewFrame)
    : cameraCropRegion(point, scale, sourceAspect, previewFrame);

  const displayPointFor = (value: MotionPathValue, point: MotionPathPointKey) => cameraRegionCenter(
    cropRegionFor(pathPoint(value, point), referenceScaleForPoint(point)),
  );

  const movePoint = (event: ReactPointerEvent<HTMLDivElement>) => {
    const gesture = gestureRef.current;
    const stage = stageRef.current;
    if (!gesture || gesture.pointerId !== event.pointerId || !stage) return;
    event.preventDefault();
    event.stopPropagation();
    const bounds = stage.getBoundingClientRect();
    const center = {
      x: Math.round(clamp((event.clientX - bounds.left) / Math.max(1, bounds.width), 0, 1) * 1000) / 1000,
      y: Math.round(clamp((event.clientY - bounds.top) / Math.max(1, bounds.height), 0, 1) * 1000) / 1000,
    };
    const storedPoint = centerCoordinates
      ? cameraRegionCenter(cameraCropRegionFromCenter(center, referenceScaleForPoint(gesture.point), sourceAspect, previewFrame))
      : cameraFocusForCenter(center, referenceScaleForPoint(gesture.point), sourceAspect, previewFrame);
    const next = replacePathPoint(valueRef.current, gesture.point, storedPoint);
    valueRef.current = next;
    setDraft(next);
  };

  const finishPointDrag = (event: ReactPointerEvent<HTMLDivElement>) => {
    const gesture = gestureRef.current;
    if (!gesture || gesture.pointerId !== event.pointerId) return;
    event.preventDefault();
    event.stopPropagation();
    gestureRef.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
    const current = pathPoint(valueRef.current, gesture.point);
    if (current.x !== gesture.initial.x || current.y !== gesture.initial.y) commitRef.current(valueRef.current);
  };

  const effectiveSelectedPoint = pathType === "linear" && selectedPoint.startsWith("control") ? "start" : selectedPoint;
  const updateSelectedPoint = (axis: "x" | "y", coordinate: number) => {
    const currentCenter = displayPointFor(valueRef.current, effectiveSelectedPoint);
    const nextCenter = { ...currentCenter, [axis]: coordinate };
    const storedPoint = centerCoordinates
      ? cameraRegionCenter(cameraCropRegionFromCenter(nextCenter, referenceScaleForPoint(effectiveSelectedPoint), sourceAspect, previewFrame))
      : cameraFocusForCenter(nextCenter, referenceScaleForPoint(effectiveSelectedPoint), sourceAspect, previewFrame);
    const next = replacePathPoint(valueRef.current, effectiveSelectedPoint, storedPoint);
    valueRef.current = next;
    setDraft(next);
    commitRef.current(next);
  };

  const motionAt = (progress: number) => {
    const positionProgress = clamp(progress / Math.max(0.05, pathEndProgress), 0, 1);
    const scaleProgress = easedMotionProgress(clamp(progress / Math.max(0.05, zoomEndProgress), 0, 1), zoomEasing);
    return {
      positionProgress,
      point: pathType === "cubic_bezier"
        ? cubicBezierPoint(draft.start, draft.control1, draft.control2, draft.end, positionProgress)
        : linearMotionPoint(draft.start, draft.end, positionProgress),
      scale: draft.start.scale + (draft.end.scale - draft.start.scale) * scaleProgress,
    };
  };
  const currentMotion = motionAt(previewProgress);
  const pathProgress = currentMotion.positionProgress;
  const current = currentMotion.point;
  const currentScale = currentMotion.scale;
  const selected = displayPointFor(draft, effectiveSelectedPoint);
  const selectedLabel = { start: "Start", control_1: "Control 1", control_2: "Control 2", end: "Hold" }[effectiveSelectedPoint];
  const startRegion = cropRegionFor(draft.start, draft.start.scale);
  const holdRegion = cropRegionFor(draft.end, draft.end.scale);
  const currentRegion = cropRegionFor(current, currentScale);
  const displayStart = cameraRegionCenter(startRegion);
  const displayHold = cameraRegionCenter(holdRegion);
  const displayControl1 = displayPointFor(draft, "control_1");
  const displayControl2 = displayPointFor(draft, "control_2");
  const miniMapPath = Array.from({ length: 25 }, (_, index) => motionAt(index / 24)).map((motion, index) => {
    const region = cropRegionFor(motion.point, motion.scale);
    const centerX = (region.x + region.width / 2) * 100;
    const centerY = (region.y + region.height / 2) * 100;
    return `${index === 0 ? "M" : "L"} ${centerX} ${centerY}`;
  }).join(" ");
  const holding = previewProgress >= Math.max(pathEndProgress, zoomEndProgress);

  return <div className="motion-bezier-editor">
    <div
      ref={stageRef}
      className={`motion-bezier-stage ${playing ? "previewing" : "editing"}`}
      data-testid="bezier-motion-stage"
      style={{
        aspectRatio: playing && previewFrame ? ratioStyle(previewFrame.ratio) : `${sourceAspect}`,
        backgroundColor: playing && previewFrame ? previewFrame.background : undefined,
      }}
      onPointerMove={movePoint}
      onPointerUp={finishPointDrag}
      onPointerCancel={finishPointDrag}
    >
      {url ? playing && previewFrame ? <div
        className="motion-result-frame"
        data-testid="motion-result-frame"
        style={{
          left: `${previewFrame.rect.x * 100}%`,
          top: `${previewFrame.rect.y * 100}%`,
          width: `${previewFrame.rect.width * 100}%`,
          height: `${previewFrame.rect.height * 100}%`,
        }}
      >
        <div
          className="motion-bezier-image result"
          style={{
            backgroundImage: `url(${url})`,
            backgroundSize: "cover",
            backgroundPosition: `${current.x * 100}% ${current.y * 100}%`,
            transform: `scale(${currentScale})`,
            transformOrigin: `${current.x * 100}% ${current.y * 100}%`,
          }}
        />
      </div> : <div
        className="motion-bezier-image editor-source"
        style={{ backgroundImage: `url(${url})`, backgroundSize: "100% auto", backgroundPosition: "center" }}
      /> : <div className="motion-keyframe-empty"><Scan size={22} /><small>Image를 연결하세요</small></div>}
      {!playing && <>
        <div className="motion-view-region start" style={{ left: `${startRegion.x * 100}%`, top: `${startRegion.y * 100}%`, width: `${startRegion.width * 100}%`, height: `${startRegion.height * 100}%` }}><b>START VIEW</b></div>
        <div className="motion-view-region hold" style={{ left: `${holdRegion.x * 100}%`, top: `${holdRegion.y * 100}%`, width: `${holdRegion.width * 100}%`, height: `${holdRegion.height * 100}%` }}><b>HOLD VIEW</b></div>
      </>}
      <svg className="motion-bezier-path" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
        {pathType === "cubic_bezier" && <>
          <line x1={displayStart.x * 100} y1={displayStart.y * 100} x2={displayControl1.x * 100} y2={displayControl1.y * 100} />
          <line x1={displayHold.x * 100} y1={displayHold.y * 100} x2={displayControl2.x * 100} y2={displayControl2.y * 100} />
        </>}
        <path d={miniMapPath} />
      </svg>
      {coordinates.map((point) => {
        const coordinate = displayPointFor(draft, point.key);
        return <button
          type="button"
          key={point.key}
          className={`motion-path-point ${point.className} ${effectiveSelectedPoint === point.key ? "active" : ""}`}
          data-testid={`motion-path-${point.key}`}
          aria-label={`${point.key} path point`}
          style={{ left: `${coordinate.x * 100}%`, top: `${coordinate.y * 100}%` }}
          onPointerDown={(event) => beginPointDrag(event, point.key)}
        >{point.label}</button>;
      })}
      <span className="motion-bezier-label">{pathType === "cubic_bezier" ? "CUBIC BÉZIER" : "LINEAR"} PATH</span>
      {playing && <span className="motion-result-preview-label">{holding ? "HOLD" : "MOTION PREVIEW"}</span>}
      {playing && <div className="motion-preview-minimap" data-testid="motion-preview-minimap">
        <header><span>MOVE MAP</span><b>{Math.round(pathProgress * 100)}%</b></header>
        <div className="motion-minimap-image" style={{ aspectRatio: `${sourceAspect}`, backgroundImage: url ? `url(${url})` : undefined }}>
          <svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-label="원본 이미지 안의 현재 화면 영역">
            <path d={miniMapPath} />
            <circle className="start" cx={(startRegion.x + startRegion.width / 2) * 100} cy={(startRegion.y + startRegion.height / 2) * 100} r="3.5" />
            <circle className="hold" cx={(holdRegion.x + holdRegion.width / 2) * 100} cy={(holdRegion.y + holdRegion.height / 2) * 100} r="3.5" />
            <circle className="current" cx={(currentRegion.x + currentRegion.width / 2) * 100} cy={(currentRegion.y + currentRegion.height / 2) * 100} r="4.5" />
          </svg>
          <div className="motion-minimap-viewport" data-testid="motion-minimap-viewport" style={{ left: `${currentRegion.x * 100}%`, top: `${currentRegion.y * 100}%`, width: `${currentRegion.width * 100}%`, height: `${currentRegion.height * 100}%` }}><b>VIEW</b></div>
        </div>
        <footer><span>Zoom</span><b>{currentScale.toFixed(2)}×</b></footer>
      </div>}
    </div>
    <div className="motion-preview-transport">
      <button type="button" aria-label={playing ? "Pause path preview" : "Play path preview"} onClick={() => {
        if (playing) {
          setPlaying(false);
          previewProgressRef.current = 0;
          setPreviewProgress(0);
        } else {
          previewProgressRef.current = 0;
          setPreviewProgress(0);
          setPlaying(true);
        }
      }}>{playing ? <Pause size={13} /> : <Play size={13} />}{playing ? "Stop" : "Preview"}</button>
      <div className="motion-preview-progress" role="progressbar" aria-label="Motion preview progress" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(previewProgress * 100)}><i style={{ width: `${previewProgress * 100}%` }} /></div>
      <b>{Math.round(previewProgress * 100)}%</b>
    </div>
    <div className="motion-point-controls">
      <header><span>{selectedLabel}</span><small>포인터는 View 테두리의 중심을 나타냅니다.</small></header>
      <RangeField label="View center X" value={selected.x} min={0} max={1} step={0.01} onChange={(coordinate) => updateSelectedPoint("x", coordinate)} />
      <RangeField label="View center Y" value={selected.y} min={0} max={1} step={0.01} onChange={(coordinate) => updateSelectedPoint("y", coordinate)} />
    </div>
  </div>;
}

export function ImageMotionEditor(props: NodeCustomEditorProps) {
  const [keyframe, setKeyframe] = useState<MotionKeyframe>("start");
  const image = connectedImage(props);
  const previewFrame = connectedMotionPreviewFrame(props);
  const url = image?.data.output?.kind === "image" ? image.data.output.url : undefined;
  const prefix = keyframe === "start" ? "start" : "end";
  const start = {
    scale: numberConfig(props.node, "start_scale", 1),
    x: numberConfig(props.node, "start_x", 0.5),
    y: numberConfig(props.node, "start_y", 0.5),
  };
  const end = {
    scale: numberConfig(props.node, "end_scale", 1.12),
    x: numberConfig(props.node, "end_x", 0.5),
    y: numberConfig(props.node, "end_y", 0.5),
  };
  const current = keyframe === "start" ? start : end;
  const supportsPaths = props.definition.contract_version >= 2;
  const supportsKeyframes = props.definition.contract_version >= 3;
  const pathType = stringConfig(props.node, "path_type", "linear");
  const durationSeconds = numberConfig(props.node, "duration_seconds", 10);
  const pathEndProgress = numberConfig(props.node, "path_end_progress", 1);
  const zoomEndProgress = numberConfig(props.node, "zoom_end_progress", 1);
  const zoomEasing = stringConfig(props.node, "zoom_easing", "linear");
  const control1 = {
    x: numberConfig(props.node, "control_1_x", start.x + (end.x - start.x) / 3),
    y: numberConfig(props.node, "control_1_y", start.y + (end.y - start.y) / 3),
  };
  const control2 = {
    x: numberConfig(props.node, "control_2_x", start.x + (end.x - start.x) * 2 / 3),
    y: numberConfig(props.node, "control_2_y", start.y + (end.y - start.y) * 2 / 3),
  };
  const selectPathType = (next: "linear" | "cubic_bezier") => {
    if (next === pathType) return;
    updateConfig(props, { path_type: next });
  };
  const commitPath = (value: MotionPathValue) => updateConfig(props, {
    start_x: value.start.x,
    start_y: value.start.y,
    control_1_x: value.control1.x,
    control_1_y: value.control1.y,
    control_2_x: value.control2.x,
    control_2_y: value.control2.y,
    end_x: value.end.x,
    end_y: value.end.y,
  });

  return <div className="sro-motion-editor">
    <div className={`editor-input-count ${url ? "connected" : "missing"}`}>
      <span>Single responsibility</span><strong>Motion only</strong>
      <small>{supportsPaths ? "이 노드는 한 이미지의 카메라 경로와 Zoom만 저장합니다." : "이 노드는 한 이미지의 시작·종료 카메라 위치만 저장합니다."}</small>
    </div>
    {supportsPaths && <div className="motion-path-mode" role="group" aria-label="Motion path type">
      <button type="button" className={pathType === "linear" ? "active" : ""} onClick={() => selectPathType("linear")}>Linear</button>
      <button type="button" className={pathType === "cubic_bezier" ? "active" : ""} onClick={() => selectPathType("cubic_bezier")}>Bézier curve</button>
    </div>}
    {supportsPaths ? <MotionPathEditor
      url={url}
      value={{ start, control1, control2, end }}
      pathType={pathType}
      pathEndProgress={pathEndProgress}
      zoomEndProgress={zoomEndProgress}
      zoomEasing={zoomEasing}
      durationSeconds={durationSeconds}
      previewFrame={previewFrame}
      centerCoordinates={props.definition.contract_version >= 4}
      onCommit={commitPath}
    /> : <div className="motion-keyframe-pair">
      <MotionPreview
        url={url}
        label="START"
        {...start}
        active={keyframe === "start"}
        onSelect={() => setKeyframe("start")}
        onCommit={(value) => updateConfig(props, { start_scale: value.scale, start_x: value.x, start_y: value.y })}
      />
      <ArrowRight size={17} />
      <MotionPreview
        url={url}
        label="END"
        {...end}
        active={keyframe === "end"}
        onSelect={() => setKeyframe("end")}
        onCommit={(value) => updateConfig(props, { end_scale: value.scale, end_x: value.x, end_y: value.y })}
      />
    </div>}
    <div className="sro-editor-controls">
      <header><span><Move size={14} /> {supportsPaths ? "View timing" : keyframe === "start" ? "시작 이미지 위치" : "종료 이미지 위치"}</span><small>{supportsPaths ? "공간 경로와 Zoom 속도를 따로 정하고, 완료 뒤에는 Hold View를 유지합니다." : "중앙 초점은 고정됩니다. 이미지를 드래그하고 휠 또는 트랙패드 핀치로 확대하세요."}</small></header>
      {supportsPaths ? <>
        <RangeField label="Start zoom" value={start.scale} min={1} max={2} step={0.01} suffix="×" onChange={(value) => updateConfig(props, { start_scale: value })} />
        <RangeField label="Hold zoom" value={end.scale} min={1} max={2} step={0.01} suffix="×" onChange={(value) => updateConfig(props, { end_scale: value })} />
        {supportsKeyframes && <>
          <TimingField label="Position complete" value={pathEndProgress} durationSeconds={durationSeconds} onChange={(value) => updateConfig(props, { path_end_progress: value })} />
          <TimingField label="Zoom complete" value={zoomEndProgress} durationSeconds={durationSeconds} onChange={(value) => updateConfig(props, { zoom_end_progress: value })} />
          <div className="generator-setting-grid motion-speed-grid">
            <label><span>Zoom speed</span><NativeSelect value={zoomEasing} onChange={(event) => updateConfig(props, { zoom_easing: event.target.value })}><option value="linear">Linear</option><option value="ease_in">Ease in</option><option value="ease_out">Ease out</option><option value="ease_in_out">Ease in-out</option></NativeSelect></label>
            <div className="motion-hold-summary"><span>Still from</span><b>{(Math.max(pathEndProgress, zoomEndProgress) * durationSeconds).toFixed(1)}s</b></div>
          </div>
        </>}
      </> : <>
        <RangeField label="Zoom" value={current.scale} min={1} max={2} step={0.01} suffix="×" onChange={(value) => updateConfig(props, { [`${prefix}_scale`]: value })} />
        <RangeField label="Image position X" value={1 - current.x} min={0} max={1} step={0.01} onChange={(value) => updateConfig(props, { [`${prefix}_x`]: 1 - value })} />
        <RangeField label="Image position Y" value={1 - current.y} min={0} max={1} step={0.01} onChange={(value) => updateConfig(props, { [`${prefix}_y`]: 1 - value })} />
      </>}
      <RangeField label="장면 길이" value={durationSeconds} min={0.5} max={30} step={0.5} suffix="s" onChange={(value) => updateConfig(props, { duration_seconds: value })} />
    </div>
  </div>;
}

function ratioStyle(value: string): string {
  if (value === "16:9") return "16 / 9";
  if (value === "1:1") return "1 / 1";
  return "9 / 16";
}

function roundedFrameValue(value: number): number {
  return Math.round(value * 10_000) / 10_000;
}

function resizeFrame(initial: FrameRect, mode: FrameResizeHandle, deltaX: number, deltaY: number): FrameRect {
  const minimum = 0.05;
  let left = initial.x;
  let top = initial.y;
  let right = initial.x + initial.width;
  let bottom = initial.y + initial.height;
  if (mode.includes("west")) left = clamp(initial.x + deltaX, 0, right - minimum);
  if (mode.includes("east")) right = clamp(initial.x + initial.width + deltaX, left + minimum, 1);
  if (mode.includes("north")) top = clamp(initial.y + deltaY, 0, bottom - minimum);
  if (mode.includes("south")) bottom = clamp(initial.y + initial.height + deltaY, top + minimum, 1);
  return {
    x: roundedFrameValue(left),
    y: roundedFrameValue(top),
    width: roundedFrameValue(right - left),
    height: roundedFrameValue(bottom - top),
  };
}

function InteractiveFrameStage({ rect, ratio, fit, background, url, shared, onCommit }: {
  rect: FrameRect;
  ratio: string;
  fit: string;
  background: string;
  url?: string;
  shared: boolean;
  onCommit: (rect: FrameRect) => void;
}) {
  const stageRef = useRef<HTMLDivElement>(null);
  const gestureRef = useRef<FramePointerGesture | null>(null);
  const valueRef = useRef(rect);
  const commitRef = useRef(onCommit);
  const [draft, setDraft] = useState(rect);
  const [dragging, setDragging] = useState(false);
  const { x: rectX, y: rectY, width: rectWidth, height: rectHeight } = rect;

  useEffect(() => {
    commitRef.current = onCommit;
  }, [onCommit]);

  useEffect(() => {
    if (gestureRef.current) return;
    const next = { x: rectX, y: rectY, width: rectWidth, height: rectHeight };
    valueRef.current = next;
    setDraft(next);
  }, [rectX, rectY, rectWidth, rectHeight]);

  const beginGesture = (event: ReactPointerEvent<HTMLElement>, mode: FramePointerGesture["mode"]) => {
    event.preventDefault();
    event.stopPropagation();
    gestureRef.current = {
      pointerId: event.pointerId,
      mode,
      clientX: event.clientX,
      clientY: event.clientY,
      initial: valueRef.current,
    };
    stageRef.current?.setPointerCapture(event.pointerId);
    setDragging(true);
  };

  const updateGesture = (event: ReactPointerEvent<HTMLDivElement>) => {
    const gesture = gestureRef.current;
    const stage = stageRef.current;
    if (!gesture || gesture.pointerId !== event.pointerId || !stage) return;
    event.preventDefault();
    event.stopPropagation();
    const bounds = stage.getBoundingClientRect();
    const deltaX = (event.clientX - gesture.clientX) / Math.max(1, bounds.width);
    const deltaY = (event.clientY - gesture.clientY) / Math.max(1, bounds.height);
    const next = gesture.mode === "move"
      ? {
          ...gesture.initial,
          x: roundedFrameValue(clamp(gesture.initial.x + deltaX, 0, 1 - gesture.initial.width)),
          y: roundedFrameValue(clamp(gesture.initial.y + deltaY, 0, 1 - gesture.initial.height)),
        }
      : resizeFrame(gesture.initial, gesture.mode, deltaX, deltaY);
    valueRef.current = next;
    setDraft(next);
  };

  const finishGesture = (event: ReactPointerEvent<HTMLDivElement>) => {
    const gesture = gestureRef.current;
    if (!gesture || gesture.pointerId !== event.pointerId) return;
    event.preventDefault();
    event.stopPropagation();
    gestureRef.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
    setDragging(false);
    commitRef.current(valueRef.current);
  };

  const handles: Array<{ mode: FrameResizeHandle; label: string }> = [
    { mode: "north-west", label: "왼쪽 위 모서리로 프레임 크기 조절" },
    { mode: "north-east", label: "오른쪽 위 모서리로 프레임 크기 조절" },
    { mode: "south-west", label: "왼쪽 아래 모서리로 프레임 크기 조절" },
    { mode: "south-east", label: "오른쪽 아래 모서리로 프레임 크기 조절" },
  ];

  return <div
    ref={stageRef}
    className={`frame-layout-stage interactive ${dragging ? "dragging" : ""}`}
    data-testid="media-frame-stage"
    style={{ aspectRatio: ratioStyle(ratio), backgroundColor: background }}
    onPointerMove={updateGesture}
    onPointerUp={finishGesture}
    onPointerCancel={finishGesture}
  >
    <div
      className="frame-layout-window"
      data-testid="media-frame-window"
      aria-label="미디어 프레임을 드래그해서 이동"
      style={{ left: `${draft.x * 100}%`, top: `${draft.y * 100}%`, width: `${draft.width * 100}%`, height: `${draft.height * 100}%` }}
      onPointerDown={(event) => beginGesture(event, "move")}
    >
      {url ? <div style={{ backgroundImage: `url(${url})`, backgroundSize: fit, backgroundPosition: "center" }} /> : <span><Frame size={20} /> {shared ? "공유 프레임" : "Motion을 연결하세요"}</span>}
      <b>{shared ? "SHARED MEDIA FRAME" : "MEDIA FRAME"}</b>
      {handles.map((handle) => <button
        type="button"
        key={handle.mode}
        className={`frame-resize-handle ${handle.mode}`}
        aria-label={handle.label}
        onPointerDown={(event) => beginGesture(event, handle.mode)}
      />)}
    </div>
    <em className="frame-layout-hint"><Move size={11} /> drag · corners resize</em>
  </div>;
}

export function FrameLayoutEditor(props: NodeCustomEditorProps) {
  const image = connectedImage(props);
  const url = image?.data.output?.kind === "image" ? image.data.output.url : undefined;
  const x = numberConfig(props.node, "frame_x", 0.04);
  const y = numberConfig(props.node, "frame_y", 0.02);
  const width = numberConfig(props.node, "frame_width", 0.92);
  const height = numberConfig(props.node, "frame_height", 0.62);
  const ratio = stringConfig(props.node, "aspect_ratio", "9:16");
  const fit = stringConfig(props.node, "media_fit", "cover");
  const background = stringConfig(props.node, "background_color", "#11100E");
  const shared = props.node.data.key === "layout.media_frame";
  const commitFrame = (next: FrameRect) => updateConfig(props, {
    frame_x: next.x,
    frame_y: next.y,
    frame_width: next.width,
    frame_height: next.height,
  });

  return <div className="sro-frame-editor">
    {shared && <div className="editor-input-count connected"><span>Reusable layout Artifact</span><strong>Shared</strong><small>이 프레임 출력 하나를 여러 Frame Apply 노드에 연결하면 모든 장면이 같은 위치를 사용합니다.</small></div>}
    <InteractiveFrameStage rect={{ x, y, width, height }} ratio={ratio} fit={fit} background={background} url={url} shared={shared} onCommit={commitFrame} />
    <div className="sro-editor-controls">
      <header><span><Frame size={14} /> {shared ? "공유 출력 프레임" : "출력 프레임"}</span><small>프레임을 드래그하고 네 모서리로 크기를 조절하세요.</small></header>
      <div className="generator-setting-grid">
        <label><span>Canvas</span><NativeSelect value={ratio} onChange={(event) => updateConfig(props, { aspect_ratio: event.target.value })}><option>9:16</option><option>16:9</option><option>1:1</option></NativeSelect></label>
        <label><span>Fit</span><NativeSelect value={fit} onChange={(event) => updateConfig(props, { media_fit: event.target.value })}><option value="cover">cover</option><option value="contain">contain</option></NativeSelect></label>
      </div>
      <RangeField label="X" value={x} min={0} max={Math.max(0, 1 - width)} step={0.01} onChange={(value) => updateConfig(props, { frame_x: value })} />
      <RangeField label="Y" value={y} min={0} max={Math.max(0, 1 - height)} step={0.01} onChange={(value) => updateConfig(props, { frame_y: value })} />
      <RangeField label="Width" value={width} min={0.05} max={Math.max(0.05, 1 - x)} step={0.01} onChange={(value) => updateConfig(props, { frame_width: value })} />
      <RangeField label="Height" value={height} min={0.05} max={Math.max(0.05, 1 - y)} step={0.01} onChange={(value) => updateConfig(props, { frame_height: value })} />
    </div>
  </div>;
}

function subtitlePreview(node: StudioFlowNode | undefined): string {
  const text = node?.data.output?.text ?? "";
  if (node?.data.outputType === "CaptionDocument") {
    try {
      const document = JSON.parse(text) as { cues?: Array<{ runs?: Array<{ text?: string }> }> };
      const richText = document.cues?.[0]?.runs?.map((run) => run.text ?? "").join("").trim();
      if (richText) return richText;
    } catch {
      // The source can still be a human-gate draft without a materialized Artifact.
    }
  }
  const lines = text.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  const timing = lines.findIndex((line) => line.includes("-->"));
  return lines.slice(timing >= 0 ? timing + 1 : 0).filter((line) => !/^\d+$/.test(line))[0] ?? "자막 표시 영역";
}

interface MediaFramePreview {
  ratio: string;
  resolution: string;
  background: string;
  rect: FrameRect;
}

function mediaFramePreview(node: StudioFlowNode | undefined): MediaFramePreview | null {
  if (!node) return null;
  const text = node.data.output?.text;
  let snapshot: Partial<MediaFramePreview> | null = null;
  try {
    const payload = JSON.parse(text ?? "") as {
      schema_version?: string;
      canvas?: { aspect_ratio?: string; resolution?: string; background_color?: string };
      frame?: { x?: number; y?: number; width?: number; height?: number };
    };
    if (payload.schema_version === "layout.media_frame.v1") snapshot = {
      ratio: payload.canvas?.aspect_ratio,
      resolution: payload.canvas?.resolution,
      background: payload.canvas?.background_color,
      rect: {
        x: Number(payload.frame?.x ?? 0.04),
        y: Number(payload.frame?.y ?? 0.02),
        width: Number(payload.frame?.width ?? 0.92),
        height: Number(payload.frame?.height ?? 0.62),
      },
    };
  } catch {
    // A draft Media Frame can still be previewed directly from its config.
  }
  return {
    ratio: stringConfig(node, "aspect_ratio", snapshot?.ratio ?? "9:16"),
    resolution: stringConfig(node, "resolution", snapshot?.resolution ?? "1080p"),
    background: stringConfig(node, "background_color", snapshot?.background ?? "#11100E"),
    rect: {
      x: numberConfig(node, "frame_x", snapshot?.rect?.x ?? 0.04),
      y: numberConfig(node, "frame_y", snapshot?.rect?.y ?? 0.02),
      width: numberConfig(node, "frame_width", snapshot?.rect?.width ?? 0.92),
      height: numberConfig(node, "frame_height", snapshot?.rect?.height ?? 0.62),
    },
  };
}

function CaptionFrameStage({ captionRect, mediaFrame, align, preview, onCommit }: {
  captionRect: FrameRect;
  mediaFrame: MediaFramePreview;
  align: "left" | "center" | "right";
  preview: string;
  onCommit: (rect: FrameRect) => void;
}) {
  const stageRef = useRef<HTMLDivElement>(null);
  const gestureRef = useRef<FramePointerGesture | null>(null);
  const valueRef = useRef(captionRect);
  const commitRef = useRef(onCommit);
  const [draft, setDraft] = useState(captionRect);
  const [dragging, setDragging] = useState(false);
  const { x, y, width, height } = captionRect;

  useEffect(() => {
    commitRef.current = onCommit;
  }, [onCommit]);

  useEffect(() => {
    if (gestureRef.current) return;
    const next = { x, y, width, height };
    valueRef.current = next;
    setDraft(next);
  }, [x, y, width, height]);

  const beginGesture = (event: ReactPointerEvent<HTMLElement>, mode: FramePointerGesture["mode"]) => {
    event.preventDefault();
    event.stopPropagation();
    gestureRef.current = {
      pointerId: event.pointerId,
      mode,
      clientX: event.clientX,
      clientY: event.clientY,
      initial: valueRef.current,
    };
    stageRef.current?.setPointerCapture(event.pointerId);
    setDragging(true);
  };

  const updateGesture = (event: ReactPointerEvent<HTMLDivElement>) => {
    const gesture = gestureRef.current;
    const stage = stageRef.current;
    if (!gesture || gesture.pointerId !== event.pointerId || !stage) return;
    event.preventDefault();
    event.stopPropagation();
    const bounds = stage.getBoundingClientRect();
    const deltaX = (event.clientX - gesture.clientX) / Math.max(1, bounds.width);
    const deltaY = (event.clientY - gesture.clientY) / Math.max(1, bounds.height);
    const next = gesture.mode === "move"
      ? {
          ...gesture.initial,
          x: roundedFrameValue(clamp(gesture.initial.x + deltaX, 0, 1 - gesture.initial.width)),
          y: roundedFrameValue(clamp(gesture.initial.y + deltaY, 0, 1 - gesture.initial.height)),
        }
      : resizeFrame(gesture.initial, gesture.mode, deltaX, deltaY);
    valueRef.current = next;
    setDraft(next);
  };

  const finishGesture = (event: ReactPointerEvent<HTMLDivElement>) => {
    const gesture = gestureRef.current;
    if (!gesture || gesture.pointerId !== event.pointerId) return;
    event.preventDefault();
    event.stopPropagation();
    gestureRef.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
    setDragging(false);
    commitRef.current(valueRef.current);
  };

  const handles: Array<{ mode: FrameResizeHandle; label: string }> = [
    { mode: "north-west", label: "왼쪽 위 모서리로 자막 영역 크기 조절" },
    { mode: "north-east", label: "오른쪽 위 모서리로 자막 영역 크기 조절" },
    { mode: "south-west", label: "왼쪽 아래 모서리로 자막 영역 크기 조절" },
    { mode: "south-east", label: "오른쪽 아래 모서리로 자막 영역 크기 조절" },
  ];

  return <div
    ref={stageRef}
    className={`subtitle-region-stage caption-frame-stage ${dragging ? "dragging" : ""}`}
    data-testid="caption-frame-stage"
    style={{ aspectRatio: ratioStyle(mediaFrame.ratio), backgroundColor: mediaFrame.background }}
    onPointerMove={updateGesture}
    onPointerUp={finishGesture}
    onPointerCancel={finishGesture}
  >
    <div
      className="caption-media-reference"
      data-testid="caption-media-reference"
      style={{
        left: `${mediaFrame.rect.x * 100}%`,
        top: `${mediaFrame.rect.y * 100}%`,
        width: `${mediaFrame.rect.width * 100}%`,
        height: `${mediaFrame.rect.height * 100}%`,
      }}
    >
      <b>MEDIA FRAME</b>
      <span>연결된 공유 프레임</span>
    </div>
    <div
      className="subtitle-region-box editable"
      data-testid="caption-frame-window"
      aria-label="자막 프레임을 드래그해서 이동"
      style={{ left: `${draft.x * 100}%`, top: `${draft.y * 100}%`, width: `${draft.width * 100}%`, height: `${draft.height * 100}%`, textAlign: align }}
      onPointerDown={(event) => beginGesture(event, "move")}
    >
      <span>{preview}</span>
      <b>CAPTION</b>
      {handles.map((handle) => <button
        type="button"
        key={handle.mode}
        className={`frame-resize-handle ${handle.mode}`}
        aria-label={handle.label}
        onPointerDown={(event) => beginGesture(event, handle.mode)}
      />)}
    </div>
    <em className="frame-layout-hint"><Move size={11} /> caption drag · corners resize</em>
  </div>;
}

export function SubtitleRegionEditor(props: NodeCustomEditorProps) {
  const incoming = incomingNodes(props.node, props.nodes, props.edges);
  const subtitle = incoming.find((candidate) => ["Subtitle", "CaptionDocument"].includes(String(candidate.data.outputType)));
  const video = incoming.find((candidate) => candidate.data.outputType === "Video");
  const mediaFrameNode = incoming.find((candidate) => candidate.data.outputType === "MediaFrame");
  const mediaFrame = mediaFramePreview(mediaFrameNode);
  const videoUrl = video?.data.output?.kind === "video" ? video.data.output.url : undefined;
  const richLayout = props.definition.contract_version >= 2;
  const frameAwareLayout = props.definition.contract_version >= 3;
  const x = numberConfig(props.node, "frame_x", 0.06);
  const y = numberConfig(props.node, "frame_y", 0.68);
  const width = numberConfig(props.node, "frame_width", 0.88);
  const height = numberConfig(props.node, "frame_height", 0.28);
  const ratio = mediaFrame?.ratio ?? stringConfig(props.node, "aspect_ratio", "9:16");
  const align = stringConfig(props.node, "align", "center") as "left" | "center" | "right";
  const fontSize = numberConfig(props.node, "font_size", 58);

  const commitFrame = (next: FrameRect) => updateConfig(props, {
    frame_x: next.x,
    frame_y: next.y,
    frame_width: next.width,
    frame_height: next.height,
  });

  return <div className="sro-subtitle-editor">
    {frameAwareLayout && <div className={`editor-input-count ${mediaFrame ? "connected" : "missing"}`}>
      <span>Shared Media Frame</span><strong>{mediaFrame ? `${mediaFrame.ratio} · ${mediaFrame.resolution}` : "연결 필요"}</strong>
      <small>미디어 프레임은 기준선으로 표시되고, 이 노드에서는 자막 프레임만 수정합니다.</small>
    </div>}
    {frameAwareLayout && mediaFrame ? <CaptionFrameStage
      captionRect={{ x, y, width, height }}
      mediaFrame={mediaFrame}
      align={align}
      preview={subtitlePreview(subtitle)}
      onCommit={commitFrame}
    /> : <div className="subtitle-region-stage" style={{ aspectRatio: ratioStyle(ratio) }}>
      {videoUrl && <video className="subtitle-region-video" src={videoUrl} muted playsInline preload="metadata" />}
      <div className="subtitle-region-box" style={{ left: `${x * 100}%`, top: `${y * 100}%`, width: `${width * 100}%`, height: `${height * 100}%`, textAlign: align }}>
        <span style={{ fontSize: `${Math.max(12, fontSize * 0.28)}px` }}>{subtitlePreview(subtitle)}</span>
        <b>CAPTION REGION</b>
      </div>
    </div>
    }
    <div className="sro-editor-controls">
      <header><span><ZoomIn size={14} /> 자막 영역</span><small>{frameAwareLayout ? "공유 Media Frame과 비교하면서 Caption 영역만 정의합니다." : richLayout ? "연결된 Video 위에서 Caption Document의 표시 영역만 정의합니다." : "영상과 무관하게 자막의 안전 영역만 정의합니다."}</small></header>
      <div className="generator-setting-grid">
        {frameAwareLayout ? <label><span>Canvas</span><input value={`${ratio} · ${mediaFrame?.resolution ?? "Media Frame"}`} readOnly /></label> : <label><span>Canvas</span><NativeSelect value={ratio} onChange={(event) => updateConfig(props, { aspect_ratio: event.target.value })}><option>9:16</option><option>16:9</option><option>1:1</option></NativeSelect></label>}
        <label><span>정렬</span><NativeSelect value={align} onChange={(event) => updateConfig(props, { align: event.target.value })}><option value="left">왼쪽</option><option value="center">가운데</option><option value="right">오른쪽</option></NativeSelect></label>
      </div>
      <RangeField label="X" value={x} min={0} max={Math.max(0, 1 - width)} step={0.01} onChange={(value) => updateConfig(props, { frame_x: value })} />
      <RangeField label="Y" value={y} min={0} max={Math.max(0, 1 - height)} step={0.01} onChange={(value) => updateConfig(props, { frame_y: value })} />
      <RangeField label="Width" value={width} min={0.05} max={Math.max(0.05, 1 - x)} step={0.01} onChange={(value) => updateConfig(props, { frame_width: value })} />
      <RangeField label="Height" value={height} min={0.05} max={Math.max(0.05, 1 - y)} step={0.01} onChange={(value) => updateConfig(props, { frame_height: value })} />
      {!richLayout && <RangeField label="Font size" value={fontSize} min={20} max={120} step={1} suffix="px" onChange={(value) => updateConfig(props, { font_size: value })} />}
    </div>
  </div>;
}
