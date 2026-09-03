"use client";

import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import type { Edge } from "@xyflow/react";
import { ArrowRight, Crosshair, Frame, Move, Scan, ZoomIn } from "lucide-react";

import { NativeSelect } from "@/components/ui/native-select";
import type { StudioFlowNode } from "@/lib/canvas-model";
import type { NodeCustomEditorProps } from "@/features/nodes/custom-editors/registry";


type MotionKeyframe = "start" | "end";
type MotionTransform = { scale: number; x: number; y: number };

interface MotionDragGesture {
  pointerId: number;
  clientX: number;
  clientY: number;
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

export function ImageMotionEditor(props: NodeCustomEditorProps) {
  const [keyframe, setKeyframe] = useState<MotionKeyframe>("start");
  const image = connectedImage(props);
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

  return <div className="sro-motion-editor">
    <div className={`editor-input-count ${url ? "connected" : "missing"}`}>
      <span>Single responsibility</span><strong>Motion only</strong>
      <small>이 노드는 한 이미지의 시작·종료 카메라 위치만 저장합니다.</small>
    </div>
    <div className="motion-keyframe-pair">
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
    </div>
    <div className="sro-editor-controls">
      <header><span><Move size={14} /> {keyframe === "start" ? "시작 이미지 위치" : "종료 이미지 위치"}</span><small>중앙 초점은 고정됩니다. 이미지를 드래그하고 휠 또는 트랙패드 핀치로 확대하세요.</small></header>
      <RangeField label="Zoom" value={current.scale} min={1} max={2} step={0.01} suffix="×" onChange={(value) => updateConfig(props, { [`${prefix}_scale`]: value })} />
      <RangeField label="Image position X" value={1 - current.x} min={0} max={1} step={0.01} onChange={(value) => updateConfig(props, { [`${prefix}_x`]: 1 - value })} />
      <RangeField label="Image position Y" value={1 - current.y} min={0} max={1} step={0.01} onChange={(value) => updateConfig(props, { [`${prefix}_y`]: 1 - value })} />
      <RangeField label="장면 길이" value={numberConfig(props.node, "duration_seconds", 10)} min={0.5} max={30} step={0.5} suffix="s" onChange={(value) => updateConfig(props, { duration_seconds: value })} />
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
