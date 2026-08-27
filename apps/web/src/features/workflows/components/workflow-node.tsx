"use client";

import { createContext, useCallback, useContext, useLayoutEffect, useRef, useState } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import {
  ArrowRight,
  AudioWaveform,
  BadgeCheck,
  Bot,
  Braces,
  ChevronDown,
  ChevronUp,
  CircleCheck,
  Clapperboard,
  Film,
  Folder,
  FolderOpen,
  GitFork,
  Image as ImageIcon,
  Languages,
  Layers3,
  Link2,
  MessageSquareText,
  Mic2,
  Paintbrush,
  Play,
  RefreshCw,
  ScrollText,
  Search,
  ShieldCheck,
  Sparkles,
  StickyNote,
  Subtitles,
  Type,
  Upload,
  Video,
  Workflow,
  X,
} from "lucide-react";

import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Button } from "@/components/ui/button";
import { StatusPill } from "@/components/ui/status-pill";
import { VideoPlayer } from "@/components/ui/video-player";
import { PromptTokenEditor } from "@/features/workflows/components/prompt-token-editor";
import type { ArtifactListItem } from "@/lib/api";
import { inputHandleId, type CanvasOutput, type IconName, type StickyColor, type StudioFlowNode } from "@/lib/canvas-model";
import type { PortType } from "@/lib/types";

export const icons: Record<IconName, typeof Sparkles> = {
  brief: MessageSquareText,
  format: Braces,
  reference: Layers3,
  resolve: Workflow,
  script: ScrollText,
  shot: Clapperboard,
  image: ImageIcon,
  video: Video,
  voice: Mic2,
  select: BadgeCheck,
  subtitle: Subtitles,
  timeline: Layers3,
  render: Film,
  qc: ShieldCheck,
  upload: Upload,
  assets: FolderOpen,
  folder: Folder,
  assistant: Bot,
  text: Type,
  sticky: StickyNote,
  drawing: Paintbrush,
  changeVoice: AudioWaveform,
  translate: Languages,
};

export interface NodeActions {
  runStep: (nodeId: string) => void;
  updateConfig: (nodeId: string, value: string) => void;
  updateStickyColor: (nodeId: string, color: StickyColor) => void;
  openDrawingEditor: (nodeId: string) => void;
  getPromptImages: (nodeId: string) => Array<{ id: string; title: string; url?: string; outdated: boolean }>;
  uploadAsset: (nodeId: string, file: File) => void;
  importAssetUrl: (nodeId: string, url: string) => void;
  selectAsset: (nodeId: string, artifactId: string) => void;
  assetOptions: ArtifactListItem[];
}

export const NodeActionsContext = createContext<NodeActions>({ runStep: () => undefined, updateConfig: () => undefined, updateStickyColor: () => undefined, openDrawingEditor: () => undefined, getPromptImages: () => [], uploadAsset: () => undefined, importAssetUrl: () => undefined, selectAsset: () => undefined, assetOptions: [] });

export function CanvasNodeStatus({ data, compact = false }: { data: StudioFlowNode["data"]; compact?: boolean }) {
  return <StatusPill status={data.status} compact={compact} />;
}

export function httpUrl(value: string): string | null {
  try {
    const parsed = new URL(value.trim());
    return ["http:", "https:"].includes(parsed.protocol) ? value.trim() : null;
  } catch {
    return null;
  }
}

function AssetUploadControl({ nodeId, busy }: { nodeId: string; busy: boolean }) {
  const actions = useContext(NodeActionsContext);
  const [url, setUrl] = useState("");
  const submitUrl = (value: string) => {
    const sourceUrl = httpUrl(value);
    if (!sourceUrl || busy) return;
    setUrl(sourceUrl);
    actions.importAssetUrl(nodeId, sourceUrl);
  };
  return <div className="node-upload-control nodrag nopan">
    <label className="node-upload-drop">
      <Upload size={18} />
      <span><strong>Choose a file</strong><small>Image, video or audio</small></span>
      <input type="file" accept="image/*,video/*,audio/*" disabled={busy} onChange={(event) => { const file = event.target.files?.[0]; if (file) actions.uploadAsset(nodeId, file); }} />
    </label>
    <span className="node-upload-divider">or paste a video URL</span>
    <form className="node-url-import" onSubmit={(event) => { event.preventDefault(); submitUrl(url); }}>
      <Link2 size={13} />
      <input
        value={url}
        type="url"
        inputMode="url"
        placeholder="https://youtube.com/watch?v=…"
        aria-label="Video URL"
        disabled={busy}
        onChange={(event) => setUrl(event.target.value)}
        onKeyDown={(event) => event.stopPropagation()}
        onPaste={(event) => {
          const pastedUrl = httpUrl(event.clipboardData.getData("text/plain"));
          if (!pastedUrl) return;
          event.preventDefault();
          submitUrl(pastedUrl);
        }}
      />
      <button type="submit" aria-label="Import video URL" disabled={busy || !httpUrl(url)}><ArrowRight size={13} /></button>
    </form>
  </div>;
}

export function isVideoAsset(asset: ArtifactListItem): boolean {
  return asset.type === "Video" || asset.type === "FinalVideo";
}

export function storedAssetOutput(asset: ArtifactListItem): { outputType: PortType; output: CanvasOutput } {
  const outputType = (asset.type === "FinalVideo" ? "Video" : asset.type) as PortType;
  const kind: CanvasOutput["kind"] = outputType === "Image" ? "image" : outputType === "Video" ? "video" : outputType === "Text" ? "text" : "audio";
  return {
    outputType,
    output: { kind, title: asset.filename, url: asset.url, mimeType: asset.content_type },
  };
}

function AssetPickerPopover({ nodeId, value }: { nodeId: string; value: string }) {
  const actions = useContext(NodeActionsContext);
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState<"images" | "videos">("images");
  const [query, setQuery] = useState("");
  const selected = actions.assetOptions.find((asset) => asset.id === value);
  const imageCount = actions.assetOptions.filter((asset) => asset.type === "Image").length;
  const videoCount = actions.assetOptions.filter(isVideoAsset).length;
  const visibleAssets = actions.assetOptions.filter((asset) => {
    const matchesType = tab === "images" ? asset.type === "Image" : isVideoAsset(asset);
    return matchesType && (!query.trim() || asset.filename.toLowerCase().includes(query.trim().toLowerCase()));
  });

  const openPicker = () => {
    if (selected) setTab(isVideoAsset(selected) ? "videos" : "images");
    else if (!imageCount && videoCount) setTab("videos");
  };

  return <Popover open={open} onOpenChange={(nextOpen) => { if (nextOpen) openPicker(); setOpen(nextOpen); }}>
    <div className="node-asset-picker nodrag nopan">
    <PopoverTrigger asChild><button className={`node-asset-picker-trigger ${selected ? "has-selection" : ""}`} type="button">
      <span className={`node-asset-trigger-thumb ${selected && isVideoAsset(selected) ? "video" : "image"}`}>
        {selected
          ? isVideoAsset(selected)
            ? <VideoPlayer src={selected.url} mimeType={selected.content_type} title={selected.filename} controls={false} />
            : <i style={{ backgroundImage: `url(${selected.url})` }} />
          : <FolderOpen size={16} />}
      </span>
      <span><strong>{selected?.filename ?? "Choose an asset"}</strong><small>{selected ? `${isVideoAsset(selected) ? "Video" : "Image"} · Click to replace` : `${imageCount} images · ${videoCount} videos`}</small></span>
      <ChevronDown size={14} />
    </button></PopoverTrigger>
    </div>

    <PopoverContent className="node-asset-popover nodrag nopan nowheel" align="start" side="bottom" sideOffset={7} aria-label="Choose an asset">
      <div className="node-asset-popover-head"><span><strong>Assets</strong><small>Select one for this node</small></span><button type="button" onClick={() => setOpen(false)} aria-label="Close asset picker"><X size={13} /></button></div>
      <div className="node-asset-popover-tabs">
        <button type="button" className={tab === "images" ? "active" : ""} onClick={() => setTab("images")}><ImageIcon size={12} /> Images <span>{imageCount}</span></button>
        <button type="button" className={tab === "videos" ? "active" : ""} onClick={() => setTab("videos")}><Film size={12} /> Videos <span>{videoCount}</span></button>
      </div>
      <label className="node-asset-popover-search"><Search size={12} /><input value={query} onChange={(event) => setQuery(event.target.value)} onKeyDown={(event) => event.stopPropagation()} placeholder={`Search ${tab}…`} /></label>
      <div className="node-asset-popover-grid nowheel">
        {visibleAssets.map((asset) => <button type="button" className={asset.id === value ? "selected" : ""} key={asset.id} onClick={() => { actions.selectAsset(nodeId, asset.id); setOpen(false); }} title={asset.filename}>
          <span className="node-asset-popover-media">
            {isVideoAsset(asset) ? <VideoPlayer src={asset.url} mimeType={asset.content_type} title={asset.filename} controls={false} /> : <i style={{ backgroundImage: `url(${asset.url})` }} />}
            {isVideoAsset(asset) && <Film size={13} />}
            {asset.id === value && <b><CircleCheck size={13} /></b>}
          </span>
          <strong>{asset.filename}</strong>
        </button>)}
        {!visibleAssets.length && <div className="node-asset-popover-empty">No {tab} found</div>}
      </div>
      <div className="node-asset-popover-foot"><span>{visibleAssets.length} assets</span>{selected && <button type="button" onClick={() => { actions.selectAsset(nodeId, ""); setOpen(false); }}>Clear selection</button>}</div>
    </PopoverContent>
  </Popover>;
}

const stickyColors: Array<{ value: StickyColor; label: string }> = [
  { value: "yellow", label: "Yellow" },
  { value: "pink", label: "Pink" },
  { value: "blue", label: "Blue" },
  { value: "green", label: "Green" },
  { value: "lavender", label: "Lavender" },
  { value: "gray", label: "Gray" },
];

function StickyNoteNode({ id, data, selected }: NodeProps<StudioFlowNode>) {
  const actions = useContext(NodeActionsContext);
  const color = data.stickyColor ?? "yellow";
  return <article className={`sticky-note-node ${selected ? "selected" : ""}`} data-color={color}>
    {selected && <div className="sticky-note-colors nodrag nopan" aria-label="Sticky note color">
      {stickyColors.map((option) => <button
        type="button"
        className={color === option.value ? "active" : ""}
        data-color={option.value}
        title={option.label}
        aria-label={`${option.label} note`}
        aria-pressed={color === option.value}
        onClick={(event) => { event.stopPropagation(); actions.updateStickyColor(id, option.value); }}
        key={option.value}
      />)}
    </div>}
    <NodePromptEditor nodeId={id} value={data.configText ?? ""} onCommit={actions.updateConfig} className="sticky-note-text nodrag nopan nowheel" placeholder="메모를 입력하세요…" collapsible={false} />
  </article>;
}

function DrawingCanvasNode({ id, data, selected }: NodeProps<StudioFlowNode>) {
  const actions = useContext(NodeActionsContext);
  const hasDrawing = Boolean(data.output?.url);
  return <article
    className={`drawing-canvas-node ${selected ? "selected" : ""}`}
    onClick={(event) => { if (!(event.target as HTMLElement).closest(".react-flow__handle")) actions.openDrawingEditor(id); }}
    onDoubleClick={(event) => event.stopPropagation()}
  >
    <div className="drawing-node-head">
      <span><Paintbrush size={15} /></span>
      <div><small>utility.drawing</small><strong>{data.label}</strong></div>
      <CanvasNodeStatus data={data} compact />
    </div>
    <div className={`drawing-node-preview ${hasDrawing ? "has-drawing" : ""}`} style={hasDrawing ? { backgroundImage: `url(${data.output?.url})` } : undefined}>
      {!hasDrawing && <span><Paintbrush size={22} /><strong>Click to draw</strong><small>이미지 붙여넣기 · 배치 · 낙서</small></span>}
      {hasDrawing && <i><Paintbrush size={12} /> 다시 편집</i>}
    </div>
    <div className="drawing-node-foot"><span>{data.drawing?.images.length ?? 0} images</span><span>{data.drawing?.strokes.length ?? 0} strokes</span><b>Image</b></div>
    <Handle type="source" position={Position.Right} id="output" className="typed-handle type-image"><span>Image</span></Handle>
  </article>;
}

function WorkflowNode(props: NodeProps<StudioFlowNode>) {
  const { id, data, selected } = props;
  const actions = useContext(NodeActionsContext);
  if (data.key === "utility.sticky") return <StickyNoteNode {...props} />;
  if (data.key === "utility.drawing") return <DrawingCanvasNode {...props} />;
  const Icon = icons[data.icon];
  const inputs = data.inputTypes ?? [];
  return (
    <article className={`workflow-node kind-${data.kind} ${selected ? "selected" : ""} status-border-${data.status.toLowerCase()}`}>
      {inputs.map((type, index) => (
        <Handle
          key={`${type}-${index}`}
          type="target"
          position={Position.Left}
          id={inputHandleId(type, index)}
          className={`typed-handle type-${type.toLowerCase()}`}
          style={{ top: `${((index + 1) / (inputs.length + 1)) * 100}%` }}
        >
          <span>{type}</span>
        </Handle>
      ))}
      <div className="node-head">
        <span className="node-icon"><Icon size={16} /></span>
        <span className="node-title"><small>{data.key}</small><strong>{data.label}</strong></span>
        <CanvasNodeStatus data={data} compact />
      </div>
      <p className="node-description">{data.description}</p>
      {data.key === "prompt.input" && <PromptTokenEditor nodeId={id} value={data.configText ?? ""} images={actions.getPromptImages(id)} onCommit={actions.updateConfig} />}
      {data.key === "asset.upload" && <AssetUploadControl nodeId={id} busy={data.status === "RUNNING"} />}
      {data.key === "asset.select" && <AssetPickerPopover nodeId={id} value={data.configText ?? ""} />}
      {data.configText !== undefined && !["asset.select", "asset.upload", "prompt.input"].includes(data.key) && <NodePromptEditor nodeId={id} value={data.configText} onCommit={actions.updateConfig} />}
      {data.output ? <NodeOutput output={data.output} stateLabel={data.status === "SUCCEEDED" ? undefined : data.status === "STALE" ? "Outdated" : "Previous result"} /> : data.preview && <div className={`node-preview preview-${data.icon}`}><span>{data.preview}</span></div>}
      <div className="node-meta">
        {data.model && <span><Sparkles size={10} /> {data.provider ? `${data.provider} · ` : ""}{data.model}</span>}
        {data.fanout && <span><GitFork size={10} /> {data.fanout}</span>}
        {!!data.attemptCount && <span><RefreshCw size={10} /> {data.attemptCount}</span>}
        {data.cost && <span className="node-cost">{data.cost}</span>}
        {data.executable !== false && <button className="node-run-inline nodrag" type="button" onClick={() => actions.runStep(id)} disabled={data.status === "RUNNING" || data.status === "BLOCKED"}>{data.status === "RUNNING" ? <RefreshCw className="spin" size={13} /> : <Play size={12} fill="currentColor" />} Run</button>}
      </div>
      {data.outputType && (
        <Handle type="source" position={Position.Right} id="output" className={`typed-handle type-${data.outputType.toLowerCase()}`}>
          <span>{data.outputType}</span>
        </Handle>
      )}
    </article>
  );
}

function NodePromptEditor({ nodeId, value, onCommit, className = "node-inline-prompt nodrag nopan nowheel", placeholder = "Describe what to generate…", collapsible = true }: { nodeId: string; value: string; onCommit: (nodeId: string, value: string) => void; className?: string; placeholder?: string; collapsible?: boolean }) {
  const [draft, setDraft] = useState(value);
  const [collapsed, setCollapsed] = useState(false);
  const composingRef = useRef(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const textareaId = `node-prompt-${nodeId}`;
  const resizeTextarea = useCallback(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    textarea.style.height = "0px";
    textarea.style.height = `${textarea.scrollHeight}px`;
  }, []);

  useLayoutEffect(() => {
    if (!collapsed) resizeTextarea();
  }, [collapsed, draft, resizeTextarea]);

  const textarea = <textarea
    ref={textareaRef}
    id={textareaId}
    rows={1}
    hidden={collapsible && collapsed}
    className={className}
    value={draft}
    placeholder={placeholder}
    onKeyDown={(event) => event.stopPropagation()}
    onCompositionStart={() => { composingRef.current = true; }}
    onCompositionEnd={(event) => {
      composingRef.current = false;
      const completed = event.currentTarget.value;
      setDraft(completed);
      onCommit(nodeId, completed);
    }}
    onChange={(event) => {
      const nextValue = event.target.value;
      setDraft(nextValue);
      if (!composingRef.current) onCommit(nodeId, nextValue);
    }}
    onBlur={(event) => onCommit(nodeId, event.target.value)}
  />;

  if (!collapsible) return textarea;

  return <div className="node-prompt-editor nodrag nopan nowheel" data-collapsed={collapsed}>
    <div className="node-prompt-toolbar">
      <span className="node-prompt-label">Prompt</span>
      <Button
        type="button"
        variant="ghost"
        size="sm"
        className="node-prompt-toggle nodrag nopan"
        aria-expanded={!collapsed}
        aria-controls={textareaId}
        onClick={(event) => { event.stopPropagation(); setCollapsed((current) => !current); }}
      >
        {collapsed ? <><ChevronDown size={13} /> 펼치기</> : <><ChevronUp size={13} /> 접기</>}
      </Button>
    </div>
    {collapsed && <p className="node-prompt-summary" title={draft || placeholder}>{draft.trim() || placeholder}</p>}
    {textarea}
  </div>;
}

function NodeOutput({ output, stateLabel }: { output: CanvasOutput; stateLabel?: string }) {
  const state = stateLabel && <b className="node-output-state">{stateLabel}</b>;
  if (output.kind === "image") return <div className="node-output node-output-image"><div className="node-output-art" role="img" aria-label={output.title} style={{ backgroundImage: `url(${output.url})` }} /><span>{output.title}</span>{state}</div>;
  if (output.kind === "video") {
    const playable = output.mimeType?.startsWith("video/");
    return <div className={`node-output node-output-video ${playable ? "native-ratio" : "thumbnail-ratio"}`}>{playable ? <VideoPlayer className="nodrag nowheel" src={output.url ?? ""} mimeType={output.mimeType} title={output.title} compact preload="auto" /> : <div className="node-output-art" role="img" aria-label={output.title} style={{ backgroundImage: `url(${output.url})` }} />}{state}</div>;
  }
  if (output.kind === "audio") return <div className="node-output node-output-audio">{output.url ? <audio className="nodrag nowheel" src={output.url} controls /> : <div className="audio-wave">{[10, 18, 27, 15, 34, 23, 38, 16, 29, 21, 35, 14, 26, 18, 31, 12].map((height, index) => <i key={index} style={{ height }} />)}</div>}<span>{output.text}</span>{state}</div>;
  if (output.kind === "text") return <div className="node-output node-output-text"><small>{output.title}</small><p>{output.text}</p>{state}</div>;
  return <div className="node-output node-output-json"><small>{output.title}</small><pre>{output.text}</pre>{state}</div>;
}

export const nodeTypes = { studio: WorkflowNode };
