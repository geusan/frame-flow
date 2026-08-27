"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  ImagePlus,
  MousePointer2,
  Paintbrush,
  Redo2,
  Save,
  Trash2,
  Undo2,
  X,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import type { DrawingDocument, DrawingImage, DrawingPoint } from "@/lib/canvas-model";

const PEN_COLORS = [
  { value: "#111111", label: "검정" },
  { value: "#ef4444", label: "빨강" },
  { value: "#2563eb", label: "파랑" },
  { value: "#16a34a", label: "초록" },
  { value: "#eab308", label: "노랑" },
  { value: "#9333ea", label: "보라" },
] as const;

const PEN_WIDTHS = [2, 4, 6, 8, 10, 12, 16, 20, 26, 34] as const;
const MIN_IMAGE_SIZE = 48;

type EditorTool = "select" | "pen";

type PointerGesture =
  | { kind: "draw"; strokeId: string }
  | { kind: "move"; imageId: string; start: DrawingPoint; image: DrawingImage; before: DrawingDocument }
  | { kind: "resize"; imageId: string; start: DrawingPoint; image: DrawingImage; before: DrawingDocument };

const imageCache = new Map<string, Promise<HTMLImageElement>>();

interface DrawingCanvasDialogProps {
  document: DrawingDocument;
  nodeName: string;
  onAddImage: (file: File) => Promise<string>;
  onClose: () => void;
  onSave: (document: DrawingDocument, image: Blob) => Promise<void>;
}

function cloneDocument(document: DrawingDocument): DrawingDocument {
  return JSON.parse(JSON.stringify(document)) as DrawingDocument;
}

function loadImage(src: string): Promise<HTMLImageElement> {
  const cached = imageCache.get(src);
  if (cached) return cached;
  const pending = new Promise<HTMLImageElement>((resolve, reject) => {
    const image = new Image();
    image.crossOrigin = "anonymous";
    image.onload = () => resolve(image);
    image.onerror = () => {
      imageCache.delete(src);
      reject(new Error("이미지를 불러오지 못했습니다."));
    };
    image.src = src;
  });
  imageCache.set(src, pending);
  return pending;
}

async function paintDocument(canvas: HTMLCanvasElement, document: DrawingDocument, selectedImageId?: string | null, strict = false) {
  if (canvas.width !== document.width) canvas.width = document.width;
  if (canvas.height !== document.height) canvas.height = document.height;
  const context = canvas.getContext("2d");
  if (!context) return;
  context.clearRect(0, 0, document.width, document.height);
  context.fillStyle = "#ffffff";
  context.fillRect(0, 0, document.width, document.height);

  for (const item of document.images) {
    try {
      const image = await loadImage(item.src);
      context.drawImage(image, item.x, item.y, item.width, item.height);
    } catch (imageError) {
      if (strict) throw imageError;
      context.fillStyle = "#f1f1ed";
      context.fillRect(item.x, item.y, item.width, item.height);
      context.strokeStyle = "#d7d8d2";
      context.strokeRect(item.x, item.y, item.width, item.height);
    }
  }

  for (const stroke of document.strokes) {
    if (!stroke.points.length) continue;
    context.beginPath();
    context.lineCap = "round";
    context.lineJoin = "round";
    context.strokeStyle = stroke.color;
    context.lineWidth = stroke.width;
    const [first, ...points] = stroke.points;
    context.moveTo(first.x, first.y);
    if (!points.length) context.lineTo(first.x + 0.01, first.y + 0.01);
    for (const point of points) context.lineTo(point.x, point.y);
    context.stroke();
  }

  const selected = document.images.find((item) => item.id === selectedImageId);
  if (selected) {
    const handleSize = 18;
    context.save();
    context.strokeStyle = "#675cf6";
    context.lineWidth = 3;
    context.setLineDash([10, 7]);
    context.strokeRect(selected.x, selected.y, selected.width, selected.height);
    context.setLineDash([]);
    context.fillStyle = "#ffffff";
    context.fillRect(selected.x + selected.width - handleSize / 2, selected.y + selected.height - handleSize / 2, handleSize, handleSize);
    context.strokeStyle = "#675cf6";
    context.strokeRect(selected.x + selected.width - handleSize / 2, selected.y + selected.height - handleSize / 2, handleSize, handleSize);
    context.restore();
  }
}

function canvasBlob(canvas: HTMLCanvasElement): Promise<Blob> {
  return new Promise((resolve, reject) => canvas.toBlob((blob) => {
    if (blob) resolve(blob);
    else reject(new Error("캔버스 이미지를 만들지 못했습니다."));
  }, "image/png"));
}

function pointInImage(point: DrawingPoint, image: DrawingImage) {
  return point.x >= image.x && point.x <= image.x + image.width && point.y >= image.y && point.y <= image.y + image.height;
}

function pointInResizeHandle(point: DrawingPoint, image: DrawingImage) {
  const hitSize = 26;
  return Math.abs(point.x - (image.x + image.width)) <= hitSize && Math.abs(point.y - (image.y + image.height)) <= hitSize;
}

export function DrawingCanvasDialog({ document: initialDocument, nodeName, onAddImage, onClose, onSave }: DrawingCanvasDialogProps) {
  const [document, setDocument] = useState(() => cloneDocument(initialDocument));
  const [tool, setTool] = useState<EditorTool>("pen");
  const [penColor, setPenColor] = useState<(typeof PEN_COLORS)[number]["value"]>(PEN_COLORS[0].value);
  const [penLevel, setPenLevel] = useState(4);
  const [selectedImageId, setSelectedImageId] = useState<string | null>(null);
  const [history, setHistory] = useState<DrawingDocument[]>([]);
  const [future, setFuture] = useState<DrawingDocument[]>([]);
  const [saving, setSaving] = useState(false);
  const [addingImage, setAddingImage] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const gestureRef = useRef<PointerGesture | null>(null);
  const renderVersionRef = useRef(0);
  const latestDocumentRef = useRef(document);
  const latestSelectedImageRef = useRef(selectedImageId);

  useEffect(() => {
    latestDocumentRef.current = document;
    latestSelectedImageRef.current = selectedImageId;
  }, [document, selectedImageId]);

  const commitHistory = useCallback((before = document) => {
    setHistory((current) => [...current, cloneDocument(before)].slice(-40));
    setFuture([]);
  }, [document]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const version = ++renderVersionRef.current;
    void paintDocument(canvas, document, selectedImageId).then(() => {
      if (version !== renderVersionRef.current) void paintDocument(canvas, latestDocumentRef.current, latestSelectedImageRef.current);
    });
  }, [document, selectedImageId]);

  const addImageFile = useCallback(async (file: File) => {
    if (!file.type.startsWith("image/") || addingImage) return;
    setError(null);
    setAddingImage(true);
    try {
      const src = await onAddImage(file);
      const source = await loadImage(src);
      const maxWidth = document.width * 0.72;
      const maxHeight = document.height * 0.72;
      const scale = Math.min(maxWidth / source.naturalWidth, maxHeight / source.naturalHeight, 1);
      const width = Math.max(MIN_IMAGE_SIZE, source.naturalWidth * scale);
      const height = Math.max(MIN_IMAGE_SIZE, source.naturalHeight * scale);
      const offset = document.images.length * 18;
      const image: DrawingImage = {
        id: `drawing-image-${Date.now()}-${document.images.length}`,
        name: file.name || "붙여넣은 이미지",
        src,
        x: Math.max(0, (document.width - width) / 2 + offset),
        y: Math.max(0, (document.height - height) / 2 + offset),
        width,
        height,
      };
      commitHistory();
      setDocument((current) => ({ ...current, images: [...current.images, image] }));
      setSelectedImageId(image.id);
      setTool("select");
    } catch (imageError) {
      setError(imageError instanceof Error ? imageError.message : "이미지를 추가하지 못했습니다.");
    } finally {
      setAddingImage(false);
    }
  }, [addingImage, commitHistory, document.height, document.images.length, document.width, onAddImage]);

  useEffect(() => {
    const handlePaste = (event: ClipboardEvent) => {
      const file = [...(event.clipboardData?.items ?? [])]
        .find((item) => item.kind === "file" && item.type.startsWith("image/"))
        ?.getAsFile();
      if (!file) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      void addImageFile(file);
    };
    window.addEventListener("paste", handlePaste, true);
    return () => window.removeEventListener("paste", handlePaste, true);
  }, [addImageFile]);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "z") {
        event.preventDefault();
        event.stopImmediatePropagation();
        if (event.shiftKey) {
          const snapshot = future.at(-1);
          if (!snapshot) return;
          setFuture((current) => current.slice(0, -1));
          setHistory((current) => [...current, cloneDocument(document)].slice(-40));
          setDocument(cloneDocument(snapshot));
        } else {
          const snapshot = history.at(-1);
          if (!snapshot) return;
          setHistory((current) => current.slice(0, -1));
          setFuture((current) => [...current, cloneDocument(document)].slice(-40));
          setDocument(cloneDocument(snapshot));
        }
      }
      if ((event.key === "Backspace" || event.key === "Delete") && selectedImageId) {
        event.preventDefault();
        event.stopImmediatePropagation();
        commitHistory();
        setDocument((current) => ({ ...current, images: current.images.filter((image) => image.id !== selectedImageId) }));
        setSelectedImageId(null);
      }
    };
    window.addEventListener("keydown", handleKeyDown, true);
    return () => window.removeEventListener("keydown", handleKeyDown, true);
  }, [commitHistory, document, future, history, selectedImageId]);

  const canvasPoint = (event: React.PointerEvent<HTMLCanvasElement>): DrawingPoint => {
    const bounds = event.currentTarget.getBoundingClientRect();
    return {
      x: ((event.clientX - bounds.left) / bounds.width) * document.width,
      y: ((event.clientY - bounds.top) / bounds.height) * document.height,
    };
  };

  const onPointerDown = (event: React.PointerEvent<HTMLCanvasElement>) => {
    event.currentTarget.setPointerCapture(event.pointerId);
    const point = canvasPoint(event);
    if (tool === "pen") {
      const strokeId = `drawing-stroke-${Date.now()}`;
      commitHistory();
      setSelectedImageId(null);
      setDocument((current) => ({
        ...current,
        strokes: [...current.strokes, { id: strokeId, color: penColor, width: PEN_WIDTHS[penLevel - 1], points: [point] }],
      }));
      gestureRef.current = { kind: "draw", strokeId };
      return;
    }

    const selected = document.images.find((image) => image.id === selectedImageId);
    if (selected && pointInResizeHandle(point, selected)) {
      gestureRef.current = { kind: "resize", imageId: selected.id, start: point, image: { ...selected }, before: cloneDocument(document) };
      return;
    }
    const hit = [...document.images].reverse().find((image) => pointInImage(point, image));
    if (!hit) {
      setSelectedImageId(null);
      gestureRef.current = null;
      return;
    }
    setSelectedImageId(hit.id);
    gestureRef.current = { kind: "move", imageId: hit.id, start: point, image: { ...hit }, before: cloneDocument(document) };
  };

  const onPointerMove = (event: React.PointerEvent<HTMLCanvasElement>) => {
    const gesture = gestureRef.current;
    if (!gesture) return;
    const point = canvasPoint(event);
    if (gesture.kind === "draw") {
      setDocument((current) => ({
        ...current,
        strokes: current.strokes.map((stroke) => stroke.id === gesture.strokeId
          ? { ...stroke, points: [...stroke.points, point] }
          : stroke),
      }));
      return;
    }
    const dx = point.x - gesture.start.x;
    const dy = point.y - gesture.start.y;
    setDocument((current) => ({
      ...current,
      images: current.images.map((image) => {
        if (image.id !== gesture.imageId) return image;
        if (gesture.kind === "move") return {
          ...image,
          x: Math.min(current.width - gesture.image.width, Math.max(0, gesture.image.x + dx)),
          y: Math.min(current.height - gesture.image.height, Math.max(0, gesture.image.y + dy)),
        };
        const ratio = gesture.image.width / gesture.image.height;
        const requestedWidth = Math.max(MIN_IMAGE_SIZE, gesture.image.width + dx);
        const requestedHeight = Math.max(MIN_IMAGE_SIZE, gesture.image.height + dy);
        let width = Math.max(requestedWidth, requestedHeight * ratio);
        width = Math.min(width, current.width - gesture.image.x, (current.height - gesture.image.y) * ratio);
        return { ...image, width, height: width / ratio };
      }),
    }));
  };

  const onPointerUp = (event: React.PointerEvent<HTMLCanvasElement>) => {
    const gesture = gestureRef.current;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
    gestureRef.current = null;
    if (gesture && gesture.kind !== "draw") commitHistory(gesture.before);
  };

  const undo = () => {
    const snapshot = history.at(-1);
    if (!snapshot) return;
    setHistory((current) => current.slice(0, -1));
    setFuture((current) => [...current, cloneDocument(document)].slice(-40));
    setDocument(cloneDocument(snapshot));
    setSelectedImageId(null);
  };

  const redo = () => {
    const snapshot = future.at(-1);
    if (!snapshot) return;
    setFuture((current) => current.slice(0, -1));
    setHistory((current) => [...current, cloneDocument(document)].slice(-40));
    setDocument(cloneDocument(snapshot));
    setSelectedImageId(null);
  };

  const deleteSelectedImage = () => {
    if (!selectedImageId) return;
    commitHistory();
    setDocument((current) => ({ ...current, images: current.images.filter((image) => image.id !== selectedImageId) }));
    setSelectedImageId(null);
  };

  const clearMarks = () => {
    if (!document.strokes.length) return;
    commitHistory();
    setDocument((current) => ({ ...current, strokes: [] }));
  };

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      const exportCanvas = window.document.createElement("canvas");
      await paintDocument(exportCanvas, document, null, true);
      await onSave(cloneDocument(document), await canvasBlob(exportCanvas));
      onClose();
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "그림을 저장하지 못했습니다.");
    } finally {
      setSaving(false);
    }
  };

  const selectedImage = document.images.find((image) => image.id === selectedImageId);

  return <Dialog open onOpenChange={(open) => { if (!open && !saving && !addingImage) onClose(); }}>
    <DialogContent className="drawing-dialog" overlayClassName="drawing-dialog-backdrop" data-drawing-editor="true" onPointerDownOutside={(event) => event.preventDefault()}>
      <header className="drawing-dialog-head">
        <div>
          <span className="subtle-label">Image annotation · {document.width} × {document.height}</span>
          <DialogTitle asChild><h2>{nodeName}</h2></DialogTitle>
          <DialogDescription asChild><p>이미지를 붙여넣어 배치하고, 펜으로 Gemini에 전달할 지시사항을 표시하세요.</p></DialogDescription>
        </div>
        <DialogClose asChild><Button variant="secondary" size="icon" type="button" aria-label="그림 편집기 닫기" disabled={saving || addingImage}><X size={17} /></Button></DialogClose>
      </header>

      <div className="drawing-editor-toolbar" aria-label="그림 편집 도구">
        <div className="drawing-tool-group">
          <button type="button" className={tool === "select" ? "active" : ""} aria-pressed={tool === "select"} onClick={() => setTool("select")}><MousePointer2 size={16} /> 선택·배치</button>
          <button type="button" className={tool === "pen" ? "active" : ""} aria-pressed={tool === "pen"} onClick={() => setTool("pen")}><Paintbrush size={16} /> 펜</button>
        </div>
        <span className="drawing-toolbar-divider" />
        <div className="drawing-color-list" aria-label="펜 색상">
          {PEN_COLORS.map((color) => <button
            type="button"
            className={penColor === color.value ? "active" : ""}
            style={{ "--pen-color": color.value } as React.CSSProperties}
            title={color.label}
            aria-label={`${color.label} 펜`}
            aria-pressed={penColor === color.value}
            onClick={() => { setPenColor(color.value); setTool("pen"); }}
            key={color.value}
          />)}
        </div>
        <label className="drawing-width-control">
          <span>두께 <b>{penLevel}</b>/10</span>
          <input type="range" min="1" max="10" step="1" value={penLevel} onChange={(event) => { setPenLevel(Number(event.target.value)); setTool("pen"); }} aria-label="펜 두께" />
          <i style={{ width: PEN_WIDTHS[penLevel - 1], height: PEN_WIDTHS[penLevel - 1], background: penColor }} />
        </label>
        <span className="drawing-toolbar-spacer" />
        <button type="button" className="drawing-icon-tool" onClick={undo} disabled={!history.length} aria-label="실행 취소" title="실행 취소"><Undo2 size={16} /></button>
        <button type="button" className="drawing-icon-tool" onClick={redo} disabled={!future.length} aria-label="다시 실행" title="다시 실행"><Redo2 size={16} /></button>
        <button type="button" className="drawing-clear-tool" onClick={clearMarks} disabled={!document.strokes.length}><Trash2 size={15} /> 낙서 지우기</button>
      </div>

      <div className="drawing-editor-body">
        <aside className="drawing-image-panel">
          <input ref={fileInputRef} type="file" accept="image/*" hidden onChange={(event) => { const file = event.target.files?.[0]; if (file) void addImageFile(file); event.currentTarget.value = ""; }} />
          <button type="button" className="drawing-add-image" onClick={() => fileInputRef.current?.click()} disabled={addingImage}>{addingImage ? <Save className="spin" size={19} /> : <ImagePlus size={19} />}<span><strong>{addingImage ? "이미지 저장 중…" : "이미지 추가"}</strong><small>파일을 고르거나 ⌘V로 붙여넣기</small></span></button>
          <div className="drawing-image-list">
            <span>배치된 이미지 <b>{document.images.length}</b></span>
            {document.images.map((image, index) => <button type="button" className={selectedImageId === image.id ? "active" : ""} onClick={() => { setSelectedImageId(image.id); setTool("select"); }} key={image.id}>
              <i style={{ backgroundImage: `url(${image.src})` }} />
              <span><strong>{image.name}</strong><small>Layer {index + 1} · {Math.round(image.width)} × {Math.round(image.height)}</small></span>
            </button>)}
            {!document.images.length && <p>아직 이미지가 없습니다.<br />빈 캔버스에도 바로 그릴 수 있어요.</p>}
          </div>
          {selectedImage && <button type="button" className="drawing-delete-image" onClick={deleteSelectedImage}><Trash2 size={14} /> 선택 이미지 삭제</button>}
        </aside>

        <main
          className={`drawing-stage tool-${tool}`}
          onDragOver={(event) => { event.preventDefault(); event.dataTransfer.dropEffect = "copy"; }}
          onDrop={(event) => { event.preventDefault(); const file = [...event.dataTransfer.files].find((item) => item.type.startsWith("image/")); if (file) void addImageFile(file); }}
        >
          <canvas
            ref={canvasRef}
            width={document.width}
            height={document.height}
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerUp}
            onPointerCancel={onPointerUp}
            aria-label="이미지 배치와 자유 그리기 캔버스"
          />
          {!document.images.length && !document.strokes.length && <div className="drawing-stage-empty"><ImagePlus size={25} /><strong>이미지를 붙여넣거나 바로 그려보세요</strong><span>선택 도구로 이미지를 이동하고 우측 아래 핸들로 크기를 조절합니다.</span></div>}
        </main>
      </div>

      <footer className="drawing-dialog-foot">
        <span className={error ? "error" : ""}>{error ?? `${document.images.length}개 이미지 · ${document.strokes.length}개 펜 스트로크`}</span>
        <div><Button variant="secondary" type="button" onClick={onClose} disabled={saving || addingImage}>취소</Button><Button type="button" onClick={() => void save()} disabled={saving || addingImage}>{saving ? <><Save className="spin" size={15} /> 이미지 저장 중…</> : <><Save size={15} /> 적용하고 이미지로 저장</>}</Button></div>
      </footer>
    </DialogContent>
  </Dialog>;
}
