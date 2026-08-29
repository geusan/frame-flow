"use client";

import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { AlignCenter, AlignLeft, AlignRight, Move, RotateCcw } from "lucide-react";

import { VideoPlayer } from "@/components/ui/video-player";
import type { CaptionAlignment } from "@/lib/canvas-model";

export interface CaptionLayoutValue {
  x: number;
  y: number;
  align: CaptionAlignment;
  fontSize: number;
}

interface CaptionLayoutEditorProps {
  videoUrl?: string;
  videoMimeType?: string;
  subtitleText?: string;
  value: CaptionLayoutValue;
  onChange: (value: CaptionLayoutValue) => void;
}

interface DragGesture {
  pointerId: number;
  offsetX: number;
  offsetY: number;
}

const DEFAULT_LAYOUT: CaptionLayoutValue = { x: 0.5, y: 0.82, align: "center", fontSize: 54 };

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

function previewCaption(srt?: string) {
  if (!srt?.trim()) return "자막 위치를 드래그해서 조정하세요";
  const firstBlock = srt.trim().split(/\r?\n\s*\r?\n/)[0] ?? "";
  const lines = firstBlock.split(/\r?\n/).filter(Boolean);
  const timestampIndex = lines.findIndex((line) => line.includes("-->"));
  const text = lines.slice(timestampIndex >= 0 ? timestampIndex + 1 : 0).join(" ");
  return text.replace(/<[^>]*>/g, "").trim() || "자막 위치를 드래그해서 조정하세요";
}

function anchorTransform(align: CaptionAlignment) {
  if (align === "left") return "translate(0,-50%)";
  if (align === "right") return "translate(-100%,-50%)";
  return "translate(-50%,-50%)";
}

export function CaptionLayoutEditor({ videoUrl, videoMimeType, subtitleText, value, onChange }: CaptionLayoutEditorProps) {
  const [draft, setDraft] = useState(value);
  const [videoRatio, setVideoRatio] = useState("9 / 16");
  const [stageWidth, setStageWidth] = useState(320);
  const stageRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<DragGesture | null>(null);
  const draftRef = useRef(value);

  useEffect(() => {
    if (dragRef.current) return;
    setDraft(value);
    draftRef.current = value;
  }, [value]);

  useEffect(() => {
    const stage = stageRef.current;
    if (!stage) return;
    const measure = () => setStageWidth(stage.getBoundingClientRect().width || 320);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(stage);
    return () => observer.disconnect();
  }, [videoUrl]);

  const updateDraft = (next: CaptionLayoutValue, commit = false) => {
    draftRef.current = next;
    setDraft(next);
    if (commit) onChange(next);
  };

  const beginDrag = (event: ReactPointerEvent<HTMLButtonElement>) => {
    const stage = stageRef.current;
    if (!stage) return;
    event.preventDefault();
    event.stopPropagation();
    const rect = stage.getBoundingClientRect();
    dragRef.current = {
      pointerId: event.pointerId,
      offsetX: event.clientX - (rect.left + draftRef.current.x * rect.width),
      offsetY: event.clientY - (rect.top + draftRef.current.y * rect.height),
    };
    event.currentTarget.setPointerCapture(event.pointerId);
  };

  const moveCaption = (event: ReactPointerEvent<HTMLButtonElement>) => {
    const stage = stageRef.current;
    const gesture = dragRef.current;
    if (!stage || !gesture || gesture.pointerId !== event.pointerId) return;
    event.preventDefault();
    const rect = stage.getBoundingClientRect();
    const x = (event.clientX - rect.left - gesture.offsetX) / rect.width;
    const y = (event.clientY - rect.top - gesture.offsetY) / rect.height;
    updateDraft({ ...draftRef.current, x: clamp(x, 0.06, 0.94), y: clamp(y, 0.08, 0.92) });
  };

  const finishDrag = (event: ReactPointerEvent<HTMLButtonElement>) => {
    const gesture = dragRef.current;
    if (!gesture || gesture.pointerId !== event.pointerId) return;
    dragRef.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
    onChange(draftRef.current);
  };

  const setHorizontal = (align: CaptionAlignment) => {
    updateDraft({ ...draftRef.current, align, x: align === "left" ? 0.08 : align === "right" ? 0.92 : 0.5 }, true);
  };

  const setVertical = (y: number) => updateDraft({ ...draftRef.current, y }, true);
  const displayFontSize = Math.max(13, draft.fontSize * stageWidth / 1080);

  return <div className="caption-layout-editor">
    <div
      ref={stageRef}
      className={`caption-layout-stage ${videoUrl ? "has-video" : "missing-video"}`}
      style={{ aspectRatio: videoRatio }}
    >
      {videoUrl ? <VideoPlayer
        className="caption-layout-video"
        src={videoUrl}
        mimeType={videoMimeType}
        title="Caption layout preview"
        compact
        preload="metadata"
        onMetadata={({ width, height }) => { if (width && height) setVideoRatio(`${width} / ${height}`); }}
      /> : <div className="caption-layout-empty"><Move size={19} /><strong>Video를 연결하세요</strong><span>연결된 영상 위에서 자막 위치를 조정할 수 있습니다.</span></div>}
      {videoUrl && <button
        type="button"
        className={`caption-layout-overlay align-${draft.align}`}
        aria-label="드래그하여 자막 위치 조정"
        style={{
          left: `${draft.x * 100}%`,
          top: `${draft.y * 100}%`,
          transform: anchorTransform(draft.align),
          fontSize: displayFontSize,
          textAlign: draft.align,
        }}
        onPointerDown={beginDrag}
        onPointerMove={moveCaption}
        onPointerUp={finishDrag}
        onPointerCancel={finishDrag}
      ><span>{previewCaption(subtitleText)}</span><i><Move size={11} /> drag</i></button>}
    </div>

    <div className="caption-layout-controls">
      <div className="caption-layout-control-row"><span>가로 정렬</span><div className="caption-layout-segmented">
        <button type="button" className={draft.align === "left" ? "active" : ""} onClick={() => setHorizontal("left")} aria-label="왼쪽 정렬"><AlignLeft size={14} /> 왼쪽</button>
        <button type="button" className={draft.align === "center" ? "active" : ""} onClick={() => setHorizontal("center")} aria-label="가운데 정렬"><AlignCenter size={14} /> 가운데</button>
        <button type="button" className={draft.align === "right" ? "active" : ""} onClick={() => setHorizontal("right")} aria-label="오른쪽 정렬"><AlignRight size={14} /> 오른쪽</button>
      </div></div>
      <div className="caption-layout-control-row"><span>세로 위치</span><div className="caption-layout-segmented compact">
        <button type="button" className={Math.abs(draft.y - 0.18) < 0.02 ? "active" : ""} onClick={() => setVertical(0.18)}>상단</button>
        <button type="button" className={Math.abs(draft.y - 0.5) < 0.02 ? "active" : ""} onClick={() => setVertical(0.5)}>중앙</button>
        <button type="button" className={Math.abs(draft.y - 0.82) < 0.02 ? "active" : ""} onClick={() => setVertical(0.82)}>하단</button>
      </div></div>
      <label className="caption-size-control"><span>글자 크기 <b>{draft.fontSize}px</b></span><input type="range" min="30" max="88" step="2" value={draft.fontSize} onChange={(event) => updateDraft({ ...draftRef.current, fontSize: Number(event.target.value) }, true)} /></label>
      <div className="caption-layout-coordinates"><span>X {Math.round(draft.x * 100)}%</span><span>Y {Math.round(draft.y * 100)}%</span><button type="button" onClick={() => updateDraft(DEFAULT_LAYOUT, true)}><RotateCcw size={12} /> 초기화</button></div>
    </div>
  </div>;
}
