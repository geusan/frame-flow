"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  ArrowLeft,
  BadgeCheck,
  CircleAlert,
  Crop,
  FlipHorizontal2,
  FlipVertical2,
  Image as ImageIcon,
  LoaderCircle,
  Move,
  Redo2,
  RotateCw,
  Save,
  SlidersHorizontal,
  Sparkles,
  Sun,
  Undo2,
  WandSparkles,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { NativeSelect } from "@/components/ui/native-select";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import {
  API_BASE,
  frameflowApi,
  type ArtifactDetail,
  type ArtifactListItem,
  type ExperimentRun,
  type ImageEditDocument,
} from "@/lib/api";

type AiProvider = "google" | "openai";
type CanvasDrag =
  | { mode: "image"; x: number; y: number; offsetX: number; offsetY: number }
  | { mode: "light" };

const DEFAULT_EDIT: ImageEditDocument = {
  version: "image-edit.v1",
  aspect_ratio: "original",
  transform: {
    rotation: 0,
    zoom: 1,
    offset_x: 0,
    offset_y: 0,
    flip_horizontal: false,
    flip_vertical: false,
  },
  adjustments: {
    brightness: 1,
    contrast: 1,
    saturation: 1,
    blur: 0,
    grayscale: 0,
    sepia: 0,
  },
  lighting: {
    enabled: false,
    x: 0.5,
    y: 0.35,
    intensity: 0.9,
    radius: 0.45,
    softness: 0.75,
    color: "#ffd6a3",
  },
};

const LIGHT_COLOR_PRESETS = [
  { label: "Warm", value: "#ffd6a3" },
  { label: "Daylight", value: "#fff4dd" },
  { label: "Cool", value: "#b9d9ff" },
  { label: "Rose", value: "#ffc2ca" },
];

const AI_MODELS: Record<AiProvider, Array<{ value: string; label: string; description: string }>> = {
  google: [
    { value: "google.image.edit.fast", label: "Nano Banana 2 Lite", description: "Fast single-image edit · about $0.034 at 1K" },
    { value: "google.image.fast", label: "Nano Banana 2", description: "Best balance for iterative edits and identity" },
    { value: "google.image.quality", label: "Nano Banana Pro", description: "Complex instructions and brand-sensitive work" },
  ],
  openai: [
    { value: "openai.image.default", label: "GPT Image 2", description: "High-fidelity semantic image editing" },
  ],
};

function cloneEdit(document: ImageEditDocument): ImageEditDocument {
  return JSON.parse(JSON.stringify(document)) as ImageEditDocument;
}

function artifactFilename(artifact: ArtifactDetail): string {
  return String(artifact.metadata.filename || artifact.metadata.output?.title || `Image · ${artifact.id.slice(0, 10)}`);
}

function aspectValue(aspectRatio: ImageEditDocument["aspect_ratio"], image: HTMLImageElement): number {
  if (aspectRatio === "1:1") return 1;
  if (aspectRatio === "4:5") return 4 / 5;
  if (aspectRatio === "9:16") return 9 / 16;
  if (aspectRatio === "16:9") return 16 / 9;
  return image.naturalWidth / image.naturalHeight;
}

function closestModelAspect(dimensions: { width: number; height: number } | null): string {
  if (!dimensions) return "1:1";
  const ratio = dimensions.width / dimensions.height;
  const candidates = [
    { label: "9:16", value: 9 / 16 },
    { label: "2:3", value: 2 / 3 },
    { label: "3:4", value: 3 / 4 },
    { label: "4:5", value: 4 / 5 },
    { label: "1:1", value: 1 },
    { label: "5:4", value: 5 / 4 },
    { label: "4:3", value: 4 / 3 },
    { label: "3:2", value: 3 / 2 },
    { label: "16:9", value: 16 / 9 },
  ];
  return candidates.reduce((closest, candidate) => (
    Math.abs(candidate.value - ratio) < Math.abs(closest.value - ratio) ? candidate : closest
  )).label;
}

function outputSize(image: HTMLImageElement, document: ImageEditDocument, maxSide: number): { width: number; height: number } {
  const ratio = aspectValue(document.aspect_ratio, image);
  const sourceRatio = image.naturalWidth / image.naturalHeight;
  let width = sourceRatio >= ratio ? image.naturalHeight * ratio : image.naturalWidth;
  let height = sourceRatio >= ratio ? image.naturalHeight : image.naturalWidth / ratio;
  const scale = Math.min(1, maxSide / Math.max(width, height));
  width = Math.max(1, Math.round(width * scale));
  height = Math.max(1, Math.round(height * scale));
  return { width, height };
}

function hexToRgb(color: string): { red: number; green: number; blue: number } {
  const match = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(color);
  if (!match) return { red: 255, green: 214, blue: 163 };
  return {
    red: Number.parseInt(match[1], 16),
    green: Number.parseInt(match[2], 16),
    blue: Number.parseInt(match[3], 16),
  };
}

function paintLighting(context: CanvasRenderingContext2D, document: ImageEditDocument, width: number, height: number): void {
  const light = document.lighting;
  if (!light.enabled || light.intensity <= 0) return;

  const centerX = light.x * width;
  const centerY = light.y * height;
  const radius = Math.max(1, light.radius * Math.max(width, height));
  const coreStop = Math.max(0.03, Math.min(0.78, (1 - light.softness) * 0.72));
  const alpha = Math.min(0.9, light.intensity * 0.48);
  const { red, green, blue } = hexToRgb(light.color);
  const gradient = context.createRadialGradient(centerX, centerY, 0, centerX, centerY, radius);
  gradient.addColorStop(0, `rgba(${red}, ${green}, ${blue}, ${alpha})`);
  gradient.addColorStop(coreStop, `rgba(${red}, ${green}, ${blue}, ${alpha * 0.72})`);
  gradient.addColorStop(1, `rgba(${red}, ${green}, ${blue}, 0)`);

  context.save();
  context.globalCompositeOperation = "screen";
  context.fillStyle = gradient;
  context.fillRect(0, 0, width, height);
  context.restore();
}

function paintLightHandle(context: CanvasRenderingContext2D, document: ImageEditDocument, width: number, height: number): void {
  const centerX = document.lighting.x * width;
  const centerY = document.lighting.y * height;
  const markerRadius = Math.max(11, Math.min(width, height) * 0.018);

  context.save();
  context.globalCompositeOperation = "source-over";
  context.lineWidth = Math.max(2, markerRadius * 0.12);
  context.strokeStyle = "rgba(20, 21, 18, 0.75)";
  context.fillStyle = document.lighting.color;
  context.beginPath();
  context.arc(centerX, centerY, markerRadius, 0, Math.PI * 2);
  context.fill();
  context.stroke();
  context.strokeStyle = "rgba(255, 255, 255, 0.95)";
  context.beginPath();
  context.arc(centerX, centerY, markerRadius * 0.68, 0, Math.PI * 2);
  context.stroke();
  context.beginPath();
  context.moveTo(centerX - markerRadius * 1.45, centerY);
  context.lineTo(centerX + markerRadius * 1.45, centerY);
  context.moveTo(centerX, centerY - markerRadius * 1.45);
  context.lineTo(centerX, centerY + markerRadius * 1.45);
  context.stroke();
  context.restore();
}

function paintImage(
  canvas: HTMLCanvasElement,
  image: HTMLImageElement,
  document: ImageEditDocument,
  maxSide = 1_600,
  showLightHandle = false,
): void {
  const size = outputSize(image, document, maxSide);
  if (canvas.width !== size.width) canvas.width = size.width;
  if (canvas.height !== size.height) canvas.height = size.height;
  const context = canvas.getContext("2d");
  if (!context) return;
  context.clearRect(0, 0, size.width, size.height);
  context.fillStyle = "#f3f3ef";
  context.fillRect(0, 0, size.width, size.height);
  context.imageSmoothingEnabled = true;
  context.imageSmoothingQuality = "high";

  const radians = document.transform.rotation * Math.PI / 180;
  const rotationCoverage = Math.abs(Math.cos(radians)) + Math.abs(Math.sin(radians));
  const coverScale = Math.max(size.width / image.naturalWidth, size.height / image.naturalHeight);
  const scale = coverScale * document.transform.zoom * rotationCoverage;
  const centerX = size.width * (0.5 + document.transform.offset_x);
  const centerY = size.height * (0.5 + document.transform.offset_y);

  context.save();
  context.filter = [
    `brightness(${document.adjustments.brightness})`,
    `contrast(${document.adjustments.contrast})`,
    `saturate(${document.adjustments.saturation})`,
    `blur(${document.adjustments.blur}px)`,
    `grayscale(${document.adjustments.grayscale})`,
    `sepia(${document.adjustments.sepia})`,
  ].join(" ");
  context.translate(centerX, centerY);
  context.rotate(radians);
  context.scale(
    scale * (document.transform.flip_horizontal ? -1 : 1),
    scale * (document.transform.flip_vertical ? -1 : 1),
  );
  context.drawImage(image, -image.naturalWidth / 2, -image.naturalHeight / 2);
  context.restore();
  paintLighting(context, document, size.width, size.height);
  if (showLightHandle && document.lighting.enabled) {
    paintLightHandle(context, document, size.width, size.height);
  }
}

function canvasBlob(canvas: HTMLCanvasElement): Promise<Blob> {
  return new Promise((resolve, reject) => canvas.toBlob((blob) => {
    if (blob) resolve(blob);
    else reject(new Error("브라우저가 편집 이미지를 만들지 못했습니다."));
  }, "image/png"));
}

function RangeControl({ label, value, min, max, step, display, onChange }: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  display: string;
  onChange: (value: number) => void;
}) {
  return <label className="image-editor-range">
    <span><strong>{label}</strong><small>{display}</small></span>
    <input type="range" min={min} max={max} step={step} value={value} onChange={(event) => onChange(Number(event.target.value))} />
  </label>;
}

export function ImageEditor({ artifactId }: { artifactId: string }) {
  const router = useRouter();
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const imageRef = useRef<HTMLImageElement | null>(null);
  const dragRef = useRef<CanvasDrag | null>(null);
  const [artifact, setArtifact] = useState<ArtifactDetail | null>(null);
  const [imageDimensions, setImageDimensions] = useState<{ width: number; height: number } | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [edit, setEdit] = useState<ImageEditDocument>(() => cloneEdit(DEFAULT_EDIT));
  const [history, setHistory] = useState<ImageEditDocument[]>([]);
  const [future, setFuture] = useState<ImageEditDocument[]>([]);
  const [saving, setSaving] = useState(false);
  const [savedAsset, setSavedAsset] = useState<ArtifactListItem | null>(null);
  const [manualError, setManualError] = useState<string | null>(null);
  const [interactionMode, setInteractionMode] = useState<"image" | "light">("image");
  const [aiProvider, setAiProvider] = useState<AiProvider>("google");
  const [aiModel, setAiModel] = useState(AI_MODELS.google[0].value);
  const [aiPrompt, setAiPrompt] = useState("");
  const [aiRunning, setAiRunning] = useState(false);
  const [aiResult, setAiResult] = useState<ExperimentRun | null>(null);
  const [aiError, setAiError] = useState<string | null>(null);

  const sourceUrl = `${API_BASE}/artifacts/${artifactId}/content`;
  const imageReady = imageDimensions !== null;
  const isDirty = useMemo(() => JSON.stringify(edit) !== JSON.stringify(DEFAULT_EDIT), [edit]);
  const currentAiModel = AI_MODELS[aiProvider].find((model) => model.value === aiModel) ?? AI_MODELS[aiProvider][0];

  useEffect(() => {
    let active = true;
    frameflowApi.getArtifact(artifactId)
      .then((record) => {
        if (!active) return;
        if (record.type !== "Image") throw new Error("이미지 Artifact만 이미지 편집기에서 열 수 있습니다.");
        setArtifact(record);
      })
      .catch((error) => { if (active) setLoadError(error instanceof Error ? error.message : "이미지를 불러오지 못했습니다."); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [artifactId]);

  useEffect(() => {
    if (!artifact) return;
    let active = true;
    const image = new Image();
    image.crossOrigin = "anonymous";
    image.onload = () => {
      if (!active) return;
      imageRef.current = image;
      setImageDimensions({ width: image.naturalWidth, height: image.naturalHeight });
    };
    image.onerror = () => { if (active) setLoadError("원본 이미지 픽셀을 불러오지 못했습니다."); };
    image.src = sourceUrl;
    return () => { active = false; };
  }, [artifact, sourceUrl]);

  useEffect(() => {
    const canvas = canvasRef.current;
    const image = imageRef.current;
    if (canvas && image && imageReady) {
      paintImage(canvas, image, edit, 1_600, interactionMode === "light");
    }
  }, [edit, imageReady, interactionMode]);

  const commitEdit = useCallback((next: ImageEditDocument) => {
    setHistory((current) => [...current, cloneEdit(edit)].slice(-40));
    setFuture([]);
    setEdit(cloneEdit(next));
    setSavedAsset(null);
    setManualError(null);
  }, [edit]);

  const updateTransform = (patch: Partial<ImageEditDocument["transform"]>) => commitEdit({
    ...edit,
    transform: { ...edit.transform, ...patch },
  });

  const updateAdjustments = (patch: Partial<ImageEditDocument["adjustments"]>) => commitEdit({
    ...edit,
    adjustments: { ...edit.adjustments, ...patch },
  });

  const updateLighting = (patch: Partial<ImageEditDocument["lighting"]>) => commitEdit({
    ...edit,
    lighting: { ...edit.lighting, ...patch },
  });

  const undo = () => {
    const snapshot = history.at(-1);
    if (!snapshot) return;
    setHistory((current) => current.slice(0, -1));
    setFuture((current) => [...current, cloneEdit(edit)].slice(-40));
    setEdit(cloneEdit(snapshot));
  };

  const redo = () => {
    const snapshot = future.at(-1);
    if (!snapshot) return;
    setFuture((current) => current.slice(0, -1));
    setHistory((current) => [...current, cloneEdit(edit)].slice(-40));
    setEdit(cloneEdit(snapshot));
  };

  const reset = () => {
    if (!isDirty) return;
    commitEdit(cloneEdit(DEFAULT_EDIT));
  };

  const exportEdit = useCallback(async (): Promise<Blob> => {
    const image = imageRef.current;
    if (!image) throw new Error("이미지가 아직 준비되지 않았습니다.");
    const canvas = window.document.createElement("canvas");
    paintImage(canvas, image, edit, 4_096);
    return canvasBlob(canvas);
  }, [edit]);

  const persistManualEdit = useCallback(async (): Promise<ArtifactListItem> => {
    const blob = await exportEdit();
    const saved = await frameflowApi.saveManualImageEdit(artifactId, blob, edit);
    window.dispatchEvent(new Event("frameflow:workspace-changed"));
    setSavedAsset(saved);
    return saved;
  }, [artifactId, edit, exportEdit]);

  const saveManualEdit = async () => {
    setSaving(true);
    setManualError(null);
    try {
      await persistManualEdit();
    } catch (error) {
      setManualError(error instanceof Error ? error.message : "편집 이미지를 저장하지 못했습니다.");
    } finally {
      setSaving(false);
    }
  };

  const runAiEdit = async () => {
    if (!aiPrompt.trim() || aiRunning) return;
    setAiRunning(true);
    setAiError(null);
    setAiResult(null);
    try {
      const inputArtifactId = isDirty ? (await persistManualEdit()).id : artifactId;
      const result = await frameflowApi.createExperiment({
        canvas_id: "asset-image-editor",
        node_id: `image-edit-${inputArtifactId}`,
        node_key: "image.edit",
        prompt: `Edit the attached source image according to this instruction: ${aiPrompt.trim()}\n\nPreserve every unspecified subject, identity, object, and visual detail as closely as possible. Return only the edited image.`,
        model_alias: aiModel,
        parameters: {
          provider: aiProvider,
          aspect_ratio: edit.aspect_ratio === "original" ? closestModelAspect(imageDimensions) : edit.aspect_ratio,
          output_count: 1,
          source_artifact_id: inputArtifactId,
          editor: "image-editor.v1",
        },
        inputs: [{ type: "Image", artifact_id: inputArtifactId, role: "source_image" }],
      });
      if (result.status !== "SUCCEEDED" || !result.output_artifact_ids[0]) {
        throw new Error(result.error || "이미지 모델이 편집 결과를 만들지 못했습니다.");
      }
      setAiResult(result);
      window.dispatchEvent(new Event("frameflow:workspace-changed"));
    } catch (error) {
      setAiError(error instanceof Error ? error.message : "AI 이미지 편집에 실패했습니다.");
    } finally {
      setAiRunning(false);
    }
  };

  const lightPositionFromPointer = (event: React.PointerEvent<HTMLCanvasElement>) => {
    const bounds = event.currentTarget.getBoundingClientRect();
    return {
      x: Math.max(0, Math.min(1, (event.clientX - bounds.left) / bounds.width)),
      y: Math.max(0, Math.min(1, (event.clientY - bounds.top) / bounds.height)),
    };
  };

  const onCanvasPointerDown = (event: React.PointerEvent<HTMLCanvasElement>) => {
    event.currentTarget.setPointerCapture(event.pointerId);
    setHistory((current) => [...current, cloneEdit(edit)].slice(-40));
    setFuture([]);
    if (edit.lighting.enabled && interactionMode === "light") {
      dragRef.current = { mode: "light" };
      const position = lightPositionFromPointer(event);
      setEdit((current) => ({ ...current, lighting: { ...current.lighting, ...position } }));
    } else {
      dragRef.current = { mode: "image", x: event.clientX, y: event.clientY, offsetX: edit.transform.offset_x, offsetY: edit.transform.offset_y };
    }
    setSavedAsset(null);
    setManualError(null);
  };

  const onCanvasPointerMove = (event: React.PointerEvent<HTMLCanvasElement>) => {
    const drag = dragRef.current;
    if (!drag) return;
    if (drag.mode === "light") {
      const position = lightPositionFromPointer(event);
      setEdit((current) => ({ ...current, lighting: { ...current.lighting, ...position } }));
      setSavedAsset(null);
      return;
    }
    const bounds = event.currentTarget.getBoundingClientRect();
    setEdit((current) => ({
      ...current,
      transform: {
        ...current.transform,
        offset_x: Math.max(-1, Math.min(1, drag.offsetX + (event.clientX - drag.x) / bounds.width)),
        offset_y: Math.max(-1, Math.min(1, drag.offsetY + (event.clientY - drag.y) / bounds.height)),
      },
    }));
    setSavedAsset(null);
  };

  const onCanvasPointerUp = (event: React.PointerEvent<HTMLCanvasElement>) => {
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
    dragRef.current = null;
  };

  if (loading) return <div className="image-editor-loading"><LoaderCircle className="spin" size={20} /><strong>Loading image editor…</strong></div>;
  if (loadError || !artifact) return <div className="image-editor-loading error"><CircleAlert size={20} /><strong>{loadError || "Image not found"}</strong><Button variant="secondary" type="button" onClick={() => router.push("/asset/images")}><ArrowLeft size={14} /> Back to images</Button></div>;

  return <div className="image-editor-page">
    <div className="image-editor-commandbar">
      <Button variant="ghost" size="icon" type="button" aria-label="Back to images" onClick={() => router.push("/asset/images")}><ArrowLeft size={17} /></Button>
      <span className="image-editor-source"><ImageIcon size={15} /><span><strong>{artifactFilename(artifact)}</strong><small>{imageDimensions ? `${imageDimensions.width} × ${imageDimensions.height}` : "Loading pixels…"}</small></span></span>
      <div className="image-editor-history">
        <Button variant="ghost" size="icon" type="button" onClick={undo} disabled={!history.length} aria-label="Undo"><Undo2 size={16} /></Button>
        <Button variant="ghost" size="icon" type="button" onClick={redo} disabled={!future.length} aria-label="Redo"><Redo2 size={16} /></Button>
        <Button variant="ghost" type="button" onClick={reset} disabled={!isDirty}><RotateCw size={14} /> Reset</Button>
      </div>
      <Button type="button" onClick={() => void saveManualEdit()} disabled={!imageReady || saving || !isDirty}><Save size={14} /> {saving ? "Saving…" : "Save as new image"}</Button>
    </div>

    <div className="image-editor-layout">
      <section className="image-editor-stage" aria-label="Image preview">
        <div className="image-editor-canvas-wrap">
          {!imageReady && <span className="image-editor-pixel-loading"><LoaderCircle className="spin" size={18} /> Loading image pixels…</span>}
          <canvas
            ref={canvasRef}
            className={`${imageReady ? "ready" : ""}${edit.lighting.enabled && interactionMode === "light" ? " light-positioning" : ""}`}
            onPointerDown={onCanvasPointerDown}
            onPointerMove={onCanvasPointerMove}
            onPointerUp={onCanvasPointerUp}
            onPointerCancel={onCanvasPointerUp}
          />
          {imageReady && <span className="image-editor-drag-hint"><Move size={12} /> {edit.lighting.enabled && interactionMode === "light" ? "Drag to reposition light" : "Drag image to reposition"}</span>}
        </div>
        {manualError && <div className="image-editor-notice error"><CircleAlert size={15} /><span>{manualError}</span></div>}
        {savedAsset && <div className="image-editor-notice success"><BadgeCheck size={15} /><span><strong>새 이미지로 저장했습니다.</strong><small>{savedAsset.filename}</small></span><button type="button" onClick={() => router.push(`/asset/images/${savedAsset.id}/edit`)}>Continue editing</button></div>}
      </section>

      <aside className="image-editor-inspector">
        <Tabs defaultValue="manual" className="image-editor-tabs">
          <TabsList className="image-editor-tab-list">
            <TabsTrigger value="manual"><SlidersHorizontal size={14} /> Manual</TabsTrigger>
            <TabsTrigger value="ai"><Sparkles size={14} /> AI edit</TabsTrigger>
          </TabsList>

          <TabsContent value="manual" className="image-editor-tab-content">
            <section className="image-editor-control-section">
              <div className="image-editor-control-head"><span><Crop size={14} /> Crop & transform</span><small>Non-destructive</small></div>
              <label className="image-editor-select"><span>Aspect ratio</span><NativeSelect value={edit.aspect_ratio} onChange={(event) => commitEdit({ ...edit, aspect_ratio: event.target.value as ImageEditDocument["aspect_ratio"] })}><option value="original">Original</option><option value="1:1">1:1 Square</option><option value="4:5">4:5 Portrait</option><option value="9:16">9:16 Story</option><option value="16:9">16:9 Landscape</option></NativeSelect></label>
              <RangeControl label="Zoom" value={edit.transform.zoom} min={1} max={3} step={0.01} display={`${Math.round(edit.transform.zoom * 100)}%`} onChange={(zoom) => updateTransform({ zoom })} />
              <RangeControl label="Rotate" value={edit.transform.rotation} min={-45} max={45} step={0.5} display={`${edit.transform.rotation.toFixed(1)}°`} onChange={(rotation) => updateTransform({ rotation })} />
              <div className="image-editor-flips">
                <Button variant={edit.transform.flip_horizontal ? "default" : "secondary"} type="button" onClick={() => updateTransform({ flip_horizontal: !edit.transform.flip_horizontal })}><FlipHorizontal2 size={14} /> Flip horizontal</Button>
                <Button variant={edit.transform.flip_vertical ? "default" : "secondary"} type="button" onClick={() => updateTransform({ flip_vertical: !edit.transform.flip_vertical })}><FlipVertical2 size={14} /> Flip vertical</Button>
              </div>
            </section>

            <section className="image-editor-control-section">
              <div className="image-editor-control-head"><span><SlidersHorizontal size={14} /> Adjustments</span><small>Canvas 2D</small></div>
              <RangeControl label="Brightness" value={edit.adjustments.brightness} min={0.25} max={1.75} step={0.01} display={`${Math.round(edit.adjustments.brightness * 100)}%`} onChange={(brightness) => updateAdjustments({ brightness })} />
              <RangeControl label="Contrast" value={edit.adjustments.contrast} min={0.25} max={1.75} step={0.01} display={`${Math.round(edit.adjustments.contrast * 100)}%`} onChange={(contrast) => updateAdjustments({ contrast })} />
              <RangeControl label="Saturation" value={edit.adjustments.saturation} min={0} max={2} step={0.01} display={`${Math.round(edit.adjustments.saturation * 100)}%`} onChange={(saturation) => updateAdjustments({ saturation })} />
              <RangeControl label="Blur" value={edit.adjustments.blur} min={0} max={20} step={0.25} display={`${edit.adjustments.blur.toFixed(1)}px`} onChange={(blur) => updateAdjustments({ blur })} />
              <RangeControl label="Grayscale" value={edit.adjustments.grayscale} min={0} max={1} step={0.01} display={`${Math.round(edit.adjustments.grayscale * 100)}%`} onChange={(grayscale) => updateAdjustments({ grayscale })} />
              <RangeControl label="Sepia" value={edit.adjustments.sepia} min={0} max={1} step={0.01} display={`${Math.round(edit.adjustments.sepia * 100)}%`} onChange={(sepia) => updateAdjustments({ sepia })} />
            </section>

            <section className="image-editor-control-section">
              <div className="image-editor-control-head"><span><Sun size={14} /> Lighting</span><small>Soft light</small></div>
              <div className="image-editor-light-toggle">
                <span><strong>Add light</strong><small>밝기와 색을 입히는 2D 광원</small></span>
                <Switch
                  checked={edit.lighting.enabled}
                  onCheckedChange={(enabled) => {
                    setInteractionMode(enabled ? "light" : "image");
                    updateLighting({ enabled });
                  }}
                  aria-label="Toggle lighting effect"
                />
              </div>
              {edit.lighting.enabled && <>
                <div className="image-editor-light-tools">
                  <Button size="sm" variant={interactionMode === "light" ? "default" : "secondary"} type="button" onClick={() => setInteractionMode("light")}><Sun size={13} /> Move light</Button>
                  <Button size="sm" variant={interactionMode === "image" ? "default" : "secondary"} type="button" onClick={() => setInteractionMode("image")}><Move size={13} /> Move image</Button>
                </div>
                <div className="image-editor-light-color">
                  <span><strong>Light color</strong><small>{edit.lighting.color.toUpperCase()}</small></span>
                  <div>
                    <input type="color" value={edit.lighting.color} onChange={(event) => updateLighting({ color: event.target.value })} aria-label="Custom light color" />
                    {LIGHT_COLOR_PRESETS.map((preset) => <button
                      key={preset.value}
                      className={edit.lighting.color === preset.value ? "selected" : ""}
                      type="button"
                      style={{ backgroundColor: preset.value }}
                      aria-label={`${preset.label} light`}
                      title={preset.label}
                      onClick={() => updateLighting({ color: preset.value })}
                    />)}
                  </div>
                </div>
                <RangeControl label="Intensity" value={edit.lighting.intensity} min={0} max={2} step={0.01} display={`${Math.round(edit.lighting.intensity * 100)}%`} onChange={(intensity) => updateLighting({ intensity })} />
                <RangeControl label="Radius" value={edit.lighting.radius} min={0.05} max={1.5} step={0.01} display={`${Math.round(edit.lighting.radius * 100)}%`} onChange={(radius) => updateLighting({ radius })} />
                <RangeControl label="Softness" value={edit.lighting.softness} min={0} max={1} step={0.01} display={`${Math.round(edit.lighting.softness * 100)}%`} onChange={(softness) => updateLighting({ softness })} />
                <div className="image-editor-light-position">
                  <RangeControl label="X position" value={edit.lighting.x} min={0} max={1} step={0.01} display={`${Math.round(edit.lighting.x * 100)}%`} onChange={(x) => updateLighting({ x })} />
                  <RangeControl label="Y position" value={edit.lighting.y} min={0} max={1} step={0.01} display={`${Math.round(edit.lighting.y * 100)}%`} onChange={(y) => updateLighting({ y })} />
                </div>
              </>}
            </section>
          </TabsContent>

          <TabsContent value="ai" className="image-editor-tab-content">
            <section className="image-editor-ai-intro"><span><WandSparkles size={18} /></span><div><strong>Edit with natural language</strong><p>Nano Banana 또는 GPT Image가 현재 이미지를 의미적으로 수정합니다. 수동 변경사항이 있으면 먼저 새 Artifact로 저장해 이어서 편집합니다.</p></div></section>
            <form className="image-editor-ai-form" onSubmit={(event) => { event.preventDefault(); void runAiEdit(); }}>
              <label><span>Edit instruction</span><Textarea value={aiPrompt} onChange={(event) => setAiPrompt(event.target.value)} placeholder="예: 인물은 그대로 유지하고 배경만 따뜻한 저녁 카페로 바꿔줘" /></label>
              <div className="image-editor-ai-models">
                <label><span>Provider</span><NativeSelect value={aiProvider} onChange={(event) => { const provider = event.target.value as AiProvider; setAiProvider(provider); setAiModel(AI_MODELS[provider][0].value); }}><option value="google">Google</option><option value="openai">OpenAI</option></NativeSelect></label>
                <label><span>Model</span><NativeSelect value={aiModel} onChange={(event) => setAiModel(event.target.value)}>{AI_MODELS[aiProvider].map((model) => <option value={model.value} key={model.value}>{model.label}</option>)}</NativeSelect></label>
              </div>
              <div className="image-editor-ai-model-note"><Sparkles size={13} /><span><strong>{currentAiModel.label}</strong><small>{currentAiModel.description}</small></span></div>
              <Button type="submit" size="lg" disabled={!aiPrompt.trim() || aiRunning}>{aiRunning ? <LoaderCircle className="spin" size={15} /> : <WandSparkles size={15} />} {aiRunning ? "Creating edit…" : "Generate AI edit"}</Button>
            </form>
            {aiError && <div className="image-editor-ai-error"><CircleAlert size={15} /> {aiError}</div>}
            {aiResult && <section className="image-editor-ai-result">
              <div className="image-editor-control-head"><span><BadgeCheck size={14} /> AI result</span><small>${aiResult.cost_usd.toFixed(3)} · {aiResult.duration_ms}ms</small></div>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={aiResult.output.url} alt="AI edited result" />
              <div><span><strong>{aiResult.exact_model_id}</strong><small>Original and prompt are preserved in lineage.</small></span><Button type="button" onClick={() => router.push(`/asset/images/${aiResult.output_artifact_ids[0]}/edit`)}>Continue editing <ArrowLeft className="image-editor-forward" size={14} /></Button></div>
            </section>}
          </TabsContent>
        </Tabs>
      </aside>
    </div>
  </div>;
}
