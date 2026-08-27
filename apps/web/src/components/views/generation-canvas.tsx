"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import {
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  MiniMap,
  Position,
  ReactFlow,
  ReactFlowProvider,
  SmoothStepEdge,
  StraightEdge,
  addEdge,
  applyEdgeChanges,
  type Connection,
  type Edge,
  type EdgeChange,
  type EdgeProps,
  type NodeChange,
  type NodeProps,
  useEdgesState,
  useNodesState,
  useReactFlow,
} from "@xyflow/react";
import {
  ArrowRight,
  AudioWaveform,
  BadgeCheck,
  Bot,
  Braces,
  ChevronDown,
  ChevronRight,
  CircleAlert,
  CircleCheck,
  CircleDollarSign,
  CircleGauge,
  CircleStop,
  Clapperboard,
  Copy,
  FilePlus2,
  Film,
  Folder,
  FolderOpen,
  GitFork,
  GripVertical,
  Hand,
  Image as ImageIcon,
  Languages,
  Layers3,
  Link2,
  ListRestart,
  LockKeyhole,
  MessageSquareText,
  Mic2,
  MousePointer2,
  PanelRightClose,
  Play,
  Plus,
  Redo2,
  RefreshCw,
  Rocket,
  Save,
  Search,
  ScrollText,
  ShieldCheck,
  Sparkles,
  Subtitles,
  StickyNote,
  Trash2,
  Type,
  Undo2,
  Upload,
  Video,
  Workflow,
  X,
  Zap,
} from "lucide-react";
import { useStudioStore } from "@/lib/store";
import type { NodeStatus, PortType } from "@/lib/types";
import {
  createNodeFromTemplate,
  graphCost,
  inputHandleId,
  isConnectionCompatible,
  nodeTemplates,
  refreshReadyStatuses,
  stepInputError,
  validateGraph,
  type CanvasOutput,
  type IconName,
  type ProviderName,
  type StudioFlowNode,
} from "@/lib/canvas-model";
import { StatusPill } from "@/components/ui/status-pill";
import { frameflowApi, type ArtifactListItem, type CanvasRunRecord, type ExperimentRun, type UploadedArtifact } from "@/lib/api";

const STORAGE_KEY = "frameflow.canvas.v2";
const EDGE_TYPE = "adaptive";
const SMOOTH_STEP_ROUTING_GAP = 40;

const icons: Record<IconName, typeof Sparkles> = {
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
  changeVoice: AudioWaveform,
  translate: Languages,
};

interface NodeActions {
  runStep: (nodeId: string) => void;
  updateConfig: (nodeId: string, value: string) => void;
  uploadAsset: (nodeId: string, file: File) => void;
  importAssetUrl: (nodeId: string, url: string) => void;
  selectAsset: (nodeId: string, artifactId: string) => void;
  assetOptions: ArtifactListItem[];
}

const NodeActionsContext = createContext<NodeActions>({ runStep: () => undefined, updateConfig: () => undefined, uploadAsset: () => undefined, importAssetUrl: () => undefined, selectAsset: () => undefined, assetOptions: [] });

function AdaptiveEdge(props: EdgeProps) {
  const horizontalGap = props.targetX - props.sourceX;
  const isCloseForwardConnection = props.sourcePosition === Position.Right
    && props.targetPosition === Position.Left
    && horizontalGap >= 0
    && horizontalGap < SMOOTH_STEP_ROUTING_GAP;

  return isCloseForwardConnection ? <StraightEdge {...props} /> : <SmoothStepEdge {...props} />;
}

const edgeTypes = { [EDGE_TYPE]: AdaptiveEdge };

interface GraphSnapshot {
  id?: string;
  nodes: StudioFlowNode[];
  edges: Edge[];
  name?: string;
  activeRunId?: string;
}

interface CandidateOption {
  id: string;
  label: string;
  output: CanvasOutput;
  artifactIds: string[];
}

function cloneGraph(nodes: StudioFlowNode[], edges: Edge[]): GraphSnapshot {
  return JSON.parse(JSON.stringify({ nodes, edges })) as GraphSnapshot;
}

function invalidateDescendants(nodes: StudioFlowNode[], edges: Edge[], sourceId: string): StudioFlowNode[] {
  const descendants = new Set<string>();
  const queue = [sourceId];
  while (queue.length) {
    const current = queue.shift()!;
    for (const edge of edges) {
      if (edge.source !== current || descendants.has(edge.target)) continue;
      descendants.add(edge.target);
      queue.push(edge.target);
    }
  }
  return nodes.map((node) => descendants.has(node.id) ? {
    ...node,
    data: {
      ...node.data,
      status: "STALE" as NodeStatus,
      preview: undefined,
      output: undefined,
      outputArtifactIds: undefined,
      lastExperimentId: undefined,
    },
  } : node);
}

function createCanvasId(): string {
  return `canvas_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 10)}`;
}

function providerFromModel(model?: string): ProviderName {
  return model?.startsWith("openai.") ? "openai" : "google";
}

function providerOptionsForNode(nodeKey: string): Array<{ value: ProviderName; label: string }> {
  return nodeKey === "video.generate" ? [{ value: "google", label: "Google" }] : [{ value: "google", label: "Google" }, { value: "openai", label: "OpenAI" }];
}

function modelOptionsForNode(nodeKey: string, provider: ProviderName): Array<{ value: string; label: string }> {
  if (nodeKey === "image.generate") return provider === "openai" ? [{ value: "openai.image.default", label: "GPT Image 2" }] : [{ value: "image.fast", label: "Gemini Image Fast" }, { value: "image.quality", label: "Gemini Image Quality" }];
  if (nodeKey === "video.generate") return [{ value: "video.fast", label: "Veo Fast" }, { value: "video.quality", label: "Veo Quality" }];
  if (nodeKey === "tts.generate") return provider === "openai" ? [{ value: "openai.tts.default", label: "GPT-4o Mini TTS" }] : [{ value: "tts.fast", label: "Gemini TTS" }];
  return provider === "openai" ? [{ value: "openai.text.fast", label: "GPT-5.6 Luna" }, { value: "openai.text.quality", label: "GPT-5.6 Terra" }, { value: "openai.chat.latest", label: "ChatGPT Latest" }] : [{ value: "text.fast", label: "Gemini Flash" }, { value: "text.quality", label: "Gemini Pro" }];
}

function migrateStoredGraph(graph: GraphSnapshot): GraphSnapshot {
  const isLegacyMockGraph = graph.nodes.some((node) => node.id === "brief" && node.data.description.includes("로마 도로"))
    || graph.nodes.some((node) => node.id === "format" && node.data.label === "Contrarian History");
  if (isLegacyMockGraph) return { ...graph, nodes: [], edges: [], activeRunId: undefined };
  const migratedNodes = graph.nodes.map((node) => {
    const template = nodeTemplates.find((item) => item.data.key === node.data.key);
    if (!template) return node;
    return {
      ...node,
      data: {
        ...node.data,
        inputTypes: template.data.inputTypes,
        requiredInputTypes: template.data.requiredInputTypes,
        multiInputTypes: template.data.multiInputTypes,
        inputsRequired: template.data.inputsRequired,
        outputType: ["asset.upload", "asset.select"].includes(node.data.key) ? node.data.outputType ?? template.data.outputType : template.data.outputType,
        provider: node.data.kind === "generate" ? node.data.provider ?? providerFromModel(node.data.model ?? template.data.model) : node.data.provider,
        model: template.data.model?.startsWith("local.") || node.data.key === "video.translate" ? template.data.model : node.data.model ?? template.data.model,
        resolution: node.data.resolution ?? template.data.resolution,
        aspectRatio: node.data.aspectRatio ?? template.data.aspectRatio,
        batchSize: node.data.batchSize ?? template.data.batchSize,
        executable: template.data.executable,
        transition: node.data.transition ?? template.data.transition,
        targetDurationSeconds: node.data.targetDurationSeconds ?? template.data.targetDurationSeconds,
        frameTimestampMs: node.data.frameTimestampMs ?? template.data.frameTimestampMs,
        sourceLanguage: node.data.sourceLanguage ?? template.data.sourceLanguage,
        targetLanguage: node.data.targetLanguage ?? template.data.targetLanguage,
        voiceName: node.data.voiceName ?? template.data.voiceName,
        configText: template.data.kind === "generate" ? undefined : node.data.configText ?? template.data.configText,
        output: node.data.output?.url?.startsWith("blob:") ? undefined : node.data.output,
      },
    };
  });
  const nodeLookup = new Map(migratedNodes.map((node) => [node.id, node]));
  const migratedEdges = graph.edges.map((edge) => {
    const sourceType = nodeLookup.get(edge.source)?.data.outputType;
    const target = nodeLookup.get(edge.target);
    const index = sourceType && target?.data.inputTypes?.indexOf(sourceType);
    const migratedEdge = edge.type === "smoothstep" || !edge.type ? { ...edge, type: EDGE_TYPE } : edge;
    return sourceType && index !== undefined && index >= 0 ? { ...migratedEdge, targetHandle: inputHandleId(sourceType, index) } : migratedEdge;
  }).filter((edge) => isConnectionCompatible(edge, migratedNodes));
  return { ...graph, nodes: refreshReadyStatuses(migratedNodes, migratedEdges), edges: migratedEdges };
}

function uploadedArtifactOutput(filename: string, artifact: UploadedArtifact): CanvasOutput {
  const kind: CanvasOutput["kind"] = artifact.type === "Image" ? "image" : artifact.type === "Video" ? "video" : artifact.type === "Audio" ? "audio" : "text";
  return {
    kind,
    title: filename,
    url: kind === "text" ? undefined : artifact.url,
    text: kind === "text" ? filename : `${(artifact.size_bytes / 1_000_000).toFixed(1)} MB`,
    mimeType: artifact.content_type,
  };
}

function httpUrl(value: string): string | null {
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

function isVideoAsset(asset: ArtifactListItem): boolean {
  return asset.type === "Video" || asset.type === "FinalVideo";
}

function AssetPickerPopover({ nodeId, value }: { nodeId: string; value: string }) {
  const actions = useContext(NodeActionsContext);
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState<"images" | "videos">("images");
  const [query, setQuery] = useState("");
  const rootRef = useRef<HTMLDivElement>(null);
  const selected = actions.assetOptions.find((asset) => asset.id === value);
  const imageCount = actions.assetOptions.filter((asset) => asset.type === "Image").length;
  const videoCount = actions.assetOptions.filter(isVideoAsset).length;
  const visibleAssets = actions.assetOptions.filter((asset) => {
    const matchesType = tab === "images" ? asset.type === "Image" : isVideoAsset(asset);
    return matchesType && (!query.trim() || asset.filename.toLowerCase().includes(query.trim().toLowerCase()));
  });

  useEffect(() => {
    if (!open) return;
    const closeOnOutsidePointer = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", closeOnOutsidePointer);
    return () => document.removeEventListener("pointerdown", closeOnOutsidePointer);
  }, [open]);

  const openPicker = () => {
    if (selected) setTab(isVideoAsset(selected) ? "videos" : "images");
    else if (!imageCount && videoCount) setTab("videos");
    setOpen((current) => !current);
  };

  return <div className="node-asset-picker nodrag nopan" ref={rootRef}>
    <button className={`node-asset-picker-trigger ${selected ? "has-selection" : ""}`} type="button" onClick={openPicker} aria-expanded={open}>
      <span className={`node-asset-trigger-thumb ${selected && isVideoAsset(selected) ? "video" : "image"}`}>
        {selected
          ? isVideoAsset(selected)
            ? <video src={selected.url} muted playsInline preload="metadata" />
            : <i style={{ backgroundImage: `url(${selected.url})` }} />
          : <FolderOpen size={16} />}
      </span>
      <span><strong>{selected?.filename ?? "Choose an asset"}</strong><small>{selected ? `${isVideoAsset(selected) ? "Video" : "Image"} · Click to replace` : `${imageCount} images · ${videoCount} videos`}</small></span>
      <ChevronDown size={14} />
    </button>

    {open && <section className="node-asset-popover" aria-label="Choose an asset">
      <div className="node-asset-popover-head"><span><strong>Assets</strong><small>Select one for this node</small></span><button type="button" onClick={() => setOpen(false)} aria-label="Close asset picker"><X size={13} /></button></div>
      <div className="node-asset-popover-tabs">
        <button type="button" className={tab === "images" ? "active" : ""} onClick={() => setTab("images")}><ImageIcon size={12} /> Images <span>{imageCount}</span></button>
        <button type="button" className={tab === "videos" ? "active" : ""} onClick={() => setTab("videos")}><Film size={12} /> Videos <span>{videoCount}</span></button>
      </div>
      <label className="node-asset-popover-search"><Search size={12} /><input value={query} onChange={(event) => setQuery(event.target.value)} onKeyDown={(event) => event.stopPropagation()} placeholder={`Search ${tab}…`} /></label>
      <div className="node-asset-popover-grid nowheel">
        {visibleAssets.map((asset) => <button type="button" className={asset.id === value ? "selected" : ""} key={asset.id} onClick={() => { actions.selectAsset(nodeId, asset.id); setOpen(false); }} title={asset.filename}>
          <span className="node-asset-popover-media">
            {isVideoAsset(asset) ? <video src={asset.url} muted playsInline preload="metadata" /> : <i style={{ backgroundImage: `url(${asset.url})` }} />}
            {isVideoAsset(asset) && <Film size={13} />}
            {asset.id === value && <b><CircleCheck size={13} /></b>}
          </span>
          <strong>{asset.filename}</strong>
        </button>)}
        {!visibleAssets.length && <div className="node-asset-popover-empty">No {tab} found</div>}
      </div>
      <div className="node-asset-popover-foot"><span>{visibleAssets.length} assets</span>{selected && <button type="button" onClick={() => { actions.selectAsset(nodeId, ""); setOpen(false); }}>Clear selection</button>}</div>
    </section>}
  </div>;
}

function WorkflowNode({ id, data, selected }: NodeProps<StudioFlowNode>) {
  const Icon = icons[data.icon];
  const inputs = data.inputTypes ?? [];
  const actions = useContext(NodeActionsContext);
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
        <StatusPill status={data.status} compact />
      </div>
      <p className="node-description">{data.description}</p>
      {data.key === "asset.upload" && <AssetUploadControl nodeId={id} busy={data.status === "RUNNING"} />}
      {data.key === "asset.select" && <AssetPickerPopover nodeId={id} value={data.configText ?? ""} />}
      {data.configText !== undefined && data.key !== "asset.select" && <NodePromptEditor nodeId={id} value={data.configText} onCommit={actions.updateConfig} />}
      {data.output ? <NodeOutput output={data.output} /> : data.preview && <div className={`node-preview preview-${data.icon}`}><span>{data.preview}</span></div>}
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

function NodePromptEditor({ nodeId, value, onCommit }: { nodeId: string; value: string; onCommit: (nodeId: string, value: string) => void }) {
  const [draft, setDraft] = useState(value);
  const composingRef = useRef(false);

  return <textarea
    className="node-inline-prompt nodrag nopan nowheel"
    value={draft}
    placeholder="Describe what to generate…"
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
}

function NodeOutput({ output }: { output: CanvasOutput }) {
  if (output.kind === "image") return <div className="node-output node-output-image"><div className="node-output-art" role="img" aria-label={output.title} style={{ backgroundImage: `url(${output.url})` }} /><span>{output.title}</span></div>;
  if (output.kind === "video") return <div className="node-output node-output-video">{output.mimeType?.startsWith("video/") ? <video className="nodrag nowheel" src={output.url} controls muted /> : <div className="node-output-art" role="img" aria-label={output.title} style={{ backgroundImage: `url(${output.url})` }} />}<span className="video-play"><Play size={19} fill="currentColor" /></span><span className="video-badge">00:06</span></div>;
  if (output.kind === "audio") return <div className="node-output node-output-audio">{output.url ? <audio className="nodrag nowheel" src={output.url} controls /> : <div className="audio-wave">{[10, 18, 27, 15, 34, 23, 38, 16, 29, 21, 35, 14, 26, 18, 31, 12].map((height, index) => <i key={index} style={{ height }} />)}</div>}<span>{output.text}</span></div>;
  if (output.kind === "text") return <div className="node-output node-output-text"><small>{output.title}</small><p>{output.text}</p></div>;
  return <div className="node-output node-output-json"><small>{output.title}</small><pre>{output.text}</pre></div>;
}

const nodeTypes = { studio: WorkflowNode };

export function GenerationCanvas() {
  return <ReactFlowProvider><EditableCanvas /></ReactFlowProvider>;
}

function EditableCanvas() {
  const [nodes, setNodes, applyNodeChanges] = useNodesState<StudioFlowNode>([]);
  const [edges, setEdges] = useEdgesState<Edge>([]);
  const [compileOpen, setCompileOpen] = useState(false);
  const [candidateOpen, setCandidateOpen] = useState(false);
  const [selectedCandidate, setSelectedCandidate] = useState(0);
  const [candidateNodeId, setCandidateNodeId] = useState<string | null>(null);
  const [paletteQuery, setPaletteQuery] = useState("");
  const [pickerQuery, setPickerQuery] = useState("");
  const [pickerOpen, setPickerOpen] = useState(false);
  const [pickerInsertPosition, setPickerInsertPosition] = useState<{ x: number; y: number } | null>(null);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [interactionMode, setInteractionMode] = useState<"select" | "pan">("select");
  const [canvasName, setCanvasName] = useState("Untitled canvas");
  const [saveState, setSaveState] = useState<"Saved" | "Unsaved" | "Saving">("Saved");
  const [toast, setToast] = useState<{ tone: "success" | "error" | "info"; message: string } | null>(null);
  const [graphRunning, setGraphRunning] = useState(false);
  const [graphProgress, setGraphProgress] = useState(0);
  const [activeCanvasRunId, setActiveCanvasRunId] = useState<string | null>(null);
  const [compileErrors, setCompileErrors] = useState<string[]>([]);
  const [history, setHistory] = useState<GraphSnapshot[]>([]);
  const [future, setFuture] = useState<GraphSnapshot[]>([]);
  const [experimentHistory, setExperimentHistory] = useState<ExperimentRun[]>([]);
  const [experimentHistoryNodeId, setExperimentHistoryNodeId] = useState<string | null>(null);
  const [experimentHistoryError, setExperimentHistoryError] = useState<string | null>(null);
  const [assetOptions, setAssetOptions] = useState<ArtifactListItem[]>([]);
  const selectedNodeId = useStudioStore((state) => state.selectedNodeId);
  const selectNode = useStudioStore((state) => state.selectNode);
  const inspectorOpen = useStudioStore((state) => state.inspectorOpen);
  const setInspectorOpen = useStudioStore((state) => state.setInspectorOpen);
  const { screenToFlowPosition } = useReactFlow<StudioFlowNode, Edge>();
  const flowStageRef = useRef<HTMLDivElement>(null);
  const lastCanvasPointerRef = useRef<{ x: number; y: number } | null>(null);
  const loadedRef = useRef(false);
  const sequenceRef = useRef(1);
  const dragStartRef = useRef<GraphSnapshot | null>(null);
  const toastTimerRef = useRef<number | null>(null);
  const cancelRunRef = useRef(false);
  const canvasRunEventsRef = useRef<EventSource | null>(null);
  const canvasIdRef = useRef(createCanvasId());
  const nodesRef = useRef(nodes);
  const edgesRef = useRef(edges);

  useEffect(() => {
    nodesRef.current = nodes;
  }, [nodes]);

  useEffect(() => {
    edgesRef.current = edges;
  }, [edges]);

  useEffect(() => () => canvasRunEventsRef.current?.close(), []);

  const notify = useCallback((message: string, tone: "success" | "error" | "info" = "info") => {
    if (toastTimerRef.current) window.clearTimeout(toastTimerRef.current);
    setToast({ message, tone });
    toastTimerRef.current = window.setTimeout(() => setToast(null), 2800);
  }, []);

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => {
      try {
        const stored = window.localStorage.getItem(STORAGE_KEY);
        if (stored) {
          const graph = JSON.parse(stored) as GraphSnapshot;
          if (Array.isArray(graph.nodes) && Array.isArray(graph.edges)) {
            const migrated = migrateStoredGraph(graph);
            canvasIdRef.current = migrated.id ?? canvasIdRef.current;
            setNodes(migrated.nodes);
            setEdges(migrated.edges);
            if (migrated.name) setCanvasName(migrated.name);
            if (migrated.activeRunId) setActiveCanvasRunId(migrated.activeRunId);
          }
        }
      } catch {
        window.localStorage.removeItem(STORAGE_KEY);
      }
      loadedRef.current = true;
    });
    return () => window.cancelAnimationFrame(frame);
  }, [setEdges, setNodes]);

  useEffect(() => {
    let active = true;
    frameflowApi.listAllArtifacts().then((items) => { if (active) setAssetOptions(items); }).catch(() => undefined);
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (!loadedRef.current || saveState === "Saved") return;
    const timer = window.setTimeout(() => {
      setSaveState("Saving");
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ ...cloneGraph(nodes, edges), id: canvasIdRef.current, name: canvasName, activeRunId: activeCanvasRunId }));
      setSaveState("Saved");
    }, 350);
    return () => window.clearTimeout(timer);
  }, [activeCanvasRunId, canvasName, edges, nodes, saveState]);

  const markUnsaved = useCallback(() => setSaveState("Unsaved"), []);

  const pushHistory = useCallback((snapshot?: GraphSnapshot) => {
    setHistory((current) => [...current, snapshot ?? cloneGraph(nodesRef.current, edgesRef.current)].slice(-40));
    setFuture([]);
  }, []);

  const restoreSnapshot = useCallback((snapshot: GraphSnapshot) => {
    setNodes(snapshot.nodes);
    setEdges(snapshot.edges);
    markUnsaved();
  }, [markUnsaved, setEdges, setNodes]);

  const undo = () => {
    const snapshot = history.at(-1);
    if (!snapshot) return;
    setHistory((current) => current.slice(0, -1));
    setFuture((current) => [...current, cloneGraph(nodesRef.current, edgesRef.current)]);
    restoreSnapshot(snapshot);
  };

  const redo = () => {
    const snapshot = future.at(-1);
    if (!snapshot) return;
    setFuture((current) => current.slice(0, -1));
    setHistory((current) => [...current, cloneGraph(nodesRef.current, edgesRef.current)].slice(-40));
    restoreSnapshot(snapshot);
  };

  const handleNodesChange = useCallback((changes: NodeChange<StudioFlowNode>[]) => {
    const meaningful = changes.some((change) => change.type !== "select" && change.type !== "dimensions" && !(change.type === "position" && change.dragging));
    if (changes.some((change) => change.type === "remove")) pushHistory();
    if (meaningful) markUnsaved();
    applyNodeChanges(changes);
    const removed = new Set(changes.filter((change) => change.type === "remove").map((change) => change.id));
    if (removed.size) {
      const nextEdges = edgesRef.current.filter((edge) => !removed.has(edge.source) && !removed.has(edge.target));
      setEdges(nextEdges);
      setNodes((current) => refreshReadyStatuses(current, nextEdges));
      if (selectedNodeId && removed.has(selectedNodeId)) selectNode(null);
    }
  }, [applyNodeChanges, markUnsaved, pushHistory, selectNode, selectedNodeId, setEdges, setNodes]);

  const handleEdgesChange = useCallback((changes: EdgeChange<Edge>[]) => {
    if (changes.some((change) => change.type === "remove")) pushHistory();
    const next = applyEdgeChanges(changes, edgesRef.current);
    setEdges(next);
    setNodes((current) => refreshReadyStatuses(current, next));
    if (changes.some((change) => change.type !== "select")) markUnsaved();
  }, [markUnsaved, pushHistory, setEdges, setNodes]);

  const isValidConnection = useCallback((connection: Connection | Edge) => {
    if (!isConnectionCompatible(connection, nodesRef.current)) return false;
    const target = nodesRef.current.find((node) => node.id === connection.target);
    const targetType = target?.data.inputTypes?.find((type, index) => connection.targetHandle === inputHandleId(type, index));
    if (targetType && target?.data.multiInputTypes?.includes(targetType)) return true;
    return !edgesRef.current.some((edge) => edge.target === connection.target && edge.targetHandle === connection.targetHandle);
  }, []);

  const onConnect = useCallback((connection: Connection) => {
    if (!isValidConnection(connection)) {
      notify("포트 타입이 다르거나 이미 연결된 입력입니다.", "error");
      return;
    }
    pushHistory();
    const next = addEdge({ ...connection, id: `edge-${Date.now()}`, type: EDGE_TYPE, style: { stroke: "#a8aaa3", strokeWidth: 1.35 } }, edgesRef.current);
    setEdges(next);
    setNodes((current) => refreshReadyStatuses(current, next));
    markUnsaved();
    notify("노드를 연결했습니다.", "success");
  }, [isValidConnection, markUnsaved, notify, pushHistory, setEdges, setNodes]);

  const addTemplateNode = useCallback((templateId: string, position?: { x: number; y: number }) => {
    const bounds = flowStageRef.current?.getBoundingClientRect();
    const basePosition = position ?? pickerInsertPosition ?? screenToFlowPosition({
      x: bounds ? bounds.left + bounds.width / 2 : window.innerWidth / 2,
      y: bounds ? bounds.top + bounds.height / 2 : window.innerHeight / 2,
    });
    const sequence = sequenceRef.current++;
    const targetPosition = position || pickerInsertPosition ? basePosition : { x: basePosition.x + (sequence % 4) * 34, y: basePosition.y + (sequence % 3) * 30 };
    const node = createNodeFromTemplate(templateId, targetPosition, sequence);
    if (!node) return;
    pushHistory();
    setNodes((current) => [...current, node]);
    selectNode(node.id);
    setPickerOpen(false);
    setPickerQuery("");
    setPickerInsertPosition(null);
    markUnsaved();
    notify(`${node.data.label} 노드를 추가했습니다.`, "success");
  }, [markUnsaved, notify, pickerInsertPosition, pushHistory, screenToFlowPosition, selectNode, setNodes]);

  const handleDrop = useCallback((event: React.DragEvent) => {
    event.preventDefault();
    const templateId = event.dataTransfer.getData("application/frameflow-node");
    if (!templateId) return;
    addTemplateNode(templateId, screenToFlowPosition({ x: event.clientX, y: event.clientY }));
  }, [addTemplateNode, screenToFlowPosition]);

  const duplicateSelected = useCallback(() => {
    const source = nodesRef.current.find((node) => node.id === selectedNodeId);
    if (!source) return;
    pushHistory();
    const duplicate: StudioFlowNode = {
      ...JSON.parse(JSON.stringify(source)) as StudioFlowNode,
      id: `${source.data.key.replaceAll(".", "-")}-${Date.now()}`,
      selected: false,
      position: { x: source.position.x + 45, y: source.position.y + 45 },
      data: { ...source.data, label: `${source.data.label} copy`, status: source.data.requiredInputTypes?.length || (source.data.inputTypes?.length && source.data.inputsRequired !== false) ? "BLOCKED" : "READY", preview: undefined, output: undefined, attemptCount: 0, logs: [] },
    };
    setNodes((current) => [...current, duplicate]);
    selectNode(duplicate.id);
    markUnsaved();
    notify("노드를 복제했습니다.", "success");
  }, [markUnsaved, notify, pushHistory, selectNode, selectedNodeId, setNodes]);

  const deleteSelected = useCallback(() => {
    if (!selectedNodeId) return;
    pushHistory();
    const nextEdges = edgesRef.current.filter((edge) => edge.source !== selectedNodeId && edge.target !== selectedNodeId);
    setEdges(nextEdges);
    setNodes((current) => refreshReadyStatuses(current.filter((node) => node.id !== selectedNodeId), nextEdges));
    selectNode(null);
    markUnsaved();
    notify("노드를 삭제했습니다.", "success");
  }, [markUnsaved, notify, pushHistory, selectNode, selectedNodeId, setEdges, setNodes]);

  const updateSelectedData = useCallback((dataPatch: Partial<StudioFlowNode["data"]>) => {
    if (!selectedNodeId) return;
    const executionFields = new Set(["provider", "model", "resolution", "aspectRatio", "batchSize", "transition", "targetDurationSeconds", "frameTimestampMs", "sourceLanguage", "targetLanguage", "voiceName"]);
    const invalidatesOutput = Object.keys(dataPatch).some((key) => executionFields.has(key));
    setNodes((current) => {
      const updated = current.map((node) => node.id === selectedNodeId ? {
        ...node,
        data: {
          ...node.data,
          ...dataPatch,
          ...(invalidatesOutput && node.data.status === "SUCCEEDED" ? { status: "STALE" as NodeStatus, output: undefined, preview: undefined, outputArtifactIds: undefined } : {}),
        },
      } : node);
      return invalidatesOutput ? refreshReadyStatuses(invalidateDescendants(updated, edgesRef.current, selectedNodeId), edgesRef.current) : updated;
    });
    markUnsaved();
  }, [markUnsaved, selectedNodeId, setNodes]);

  const updateNodeConfig = useCallback((nodeId: string, value: string) => {
    setNodes((current) => {
      const updated = current.map((node) => {
        if (node.id === nodeId) {
          const immediateSource = ["prompt.input", "asset.select", "utility.text"].includes(node.data.key);
          const promptStatus: NodeStatus = immediateSource ? (value.trim() ? "SUCCEEDED" : "READY") : node.data.status === "SUCCEEDED" ? "STALE" : node.data.status;
          const selectedAssetOutput: CanvasOutput | undefined = node.data.key === "asset.select" && value.trim() ? { kind: "json", title: "Selected asset", text: JSON.stringify({ asset: value, reference_mode: "single" }, null, 2) } : undefined;
          return { ...node, data: { ...node.data, configText: value, status: promptStatus, output: selectedAssetOutput, preview: node.data.key === "asset.select" && value ? value : undefined } };
        }
        return node;
      });
      return refreshReadyStatuses(invalidateDescendants(updated, edgesRef.current, nodeId), edgesRef.current);
    });
    markUnsaved();
  }, [markUnsaved, setNodes]);

  const uploadNodeAsset = useCallback(async (nodeId: string, file: File) => {
    setNodes((current) => current.map((node) => node.id === nodeId ? { ...node, data: { ...node.data, status: "RUNNING" as NodeStatus, preview: `Uploading ${file.name}…` } } : node));
    try {
      const artifact = await frameflowApi.uploadArtifact(file);
      const output = uploadedArtifactOutput(file.name || artifact.filename, artifact);
      setNodes((current) => {
        const invalidated = invalidateDescendants(current, edgesRef.current, nodeId);
        const updated = invalidated.map((node) => node.id === nodeId ? {
          ...node,
          data: {
            ...node.data,
            status: "SUCCEEDED" as NodeStatus,
            configText: file.name,
            preview: `${file.name} · ${(artifact.size_bytes / 1_000_000).toFixed(1)} MB`,
            output,
            outputType: artifact.type as PortType,
            outputArtifactIds: [artifact.artifact_id],
          },
        } : node);
        return refreshReadyStatuses(updated, edgesRef.current);
      });
      markUnsaved();
      setAssetOptions((current) => [{ id: artifact.artifact_id, created_at: new Date().toISOString(), type: artifact.type, content_type: artifact.content_type, size_bytes: artifact.size_bytes, filename: file.name, source: "canvas_upload", duration_ms: 0, url: artifact.url }, ...current.filter((item) => item.id !== artifact.artifact_id)]);
      notify(`${file.name} 파일을 Artifact로 저장했습니다.`, "success");
    } catch (error) {
      const message = error instanceof Error ? error.message : "Artifact upload failed";
      setNodes((current) => current.map((node) => node.id === nodeId ? { ...node, data: { ...node.data, status: "FAILED" as NodeStatus, preview: undefined, logs: [...(node.data.logs ?? []), message] } } : node));
      notify(message, "error");
    }
  }, [markUnsaved, notify, setNodes]);

  const importNodeAssetUrl = useCallback(async (nodeId: string, sourceUrl: string) => {
    setNodes((current) => current.map((node) => node.id === nodeId ? {
      ...node,
      data: { ...node.data, status: "RUNNING" as NodeStatus, configText: sourceUrl, preview: "Downloading video from URL…" },
    } : node));
    try {
      const artifact = await frameflowApi.importArtifactUrl(sourceUrl);
      const output = uploadedArtifactOutput(artifact.filename, artifact);
      setNodes((current) => {
        const invalidated = invalidateDescendants(current, edgesRef.current, nodeId);
        const updated = invalidated.map((node) => node.id === nodeId ? {
          ...node,
          data: {
            ...node.data,
            status: "SUCCEEDED" as NodeStatus,
            configText: artifact.source_url ?? sourceUrl,
            preview: `${artifact.filename} · ${(artifact.size_bytes / 1_000_000).toFixed(1)} MB`,
            output,
            outputType: artifact.type as PortType,
            outputArtifactIds: [artifact.artifact_id],
          },
        } : node);
        return refreshReadyStatuses(updated, edgesRef.current);
      });
      markUnsaved();
      setAssetOptions((current) => [{ id: artifact.artifact_id, created_at: new Date().toISOString(), type: artifact.type, content_type: artifact.content_type, size_bytes: artifact.size_bytes, filename: artifact.filename, source: "canvas_url_import", duration_ms: 0, url: artifact.url }, ...current.filter((item) => item.id !== artifact.artifact_id)]);
      notify(`${artifact.filename} 영상을 Artifact로 저장했습니다.`, "success");
    } catch (error) {
      const message = error instanceof Error ? error.message : "Video URL import failed";
      setNodes((current) => current.map((node) => node.id === nodeId ? { ...node, data: { ...node.data, status: "FAILED" as NodeStatus, preview: undefined, logs: [...(node.data.logs ?? []), message] } } : node));
      notify(message, "error");
    }
  }, [markUnsaved, notify, setNodes]);

  const selectStoredAsset = useCallback((nodeId: string, artifactId: string) => {
    const artifact = assetOptions.find((item) => item.id === artifactId);
    setNodes((current) => {
      const invalidated = invalidateDescendants(current, edgesRef.current, nodeId);
      const updated = invalidated.map((node) => {
        if (node.id !== nodeId) return node;
        if (!artifact) return { ...node, data: { ...node.data, status: "READY" as NodeStatus, configText: "", output: undefined, preview: undefined, outputArtifactIds: undefined, outputType: "ReferenceAsset" as PortType } };
        const outputType = (artifact.type === "FinalVideo" ? "Video" : artifact.type) as PortType;
        const kind: CanvasOutput["kind"] = outputType === "Image" ? "image" : outputType === "Video" ? "video" : outputType === "Text" ? "text" : "audio";
        return { ...node, data: { ...node.data, status: "SUCCEEDED" as NodeStatus, configText: artifact.id, preview: artifact.filename, outputType, outputArtifactIds: [artifact.id], output: { kind, title: artifact.filename, url: artifact.url, mimeType: artifact.content_type } } };
      });
      return refreshReadyStatuses(updated, edgesRef.current);
    });
    markUnsaved();
  }, [assetOptions, markUnsaved, setNodes]);

  const insertClipboardImage = useCallback((file: File, offset = 0) => {
    const bounds = flowStageRef.current?.getBoundingClientRect();
    const screenPoint = lastCanvasPointerRef.current ?? {
      x: bounds ? bounds.left + bounds.width / 2 : window.innerWidth / 2,
      y: bounds ? bounds.top + bounds.height / 2 : window.innerHeight / 2,
    };
    const position = screenToFlowPosition({ x: screenPoint.x + offset * 28, y: screenPoint.y + offset * 28 });
    const sequence = sequenceRef.current++;
    const node = createNodeFromTemplate("upload", position, sequence);
    if (!node) return;
    const clipboardName = file.name || `clipboard-image-${Date.now()}.png`;
    node.data = { ...node.data, label: "Pasted image", status: "RUNNING", configText: clipboardName, preview: `Uploading ${clipboardName}…` };
    pushHistory();
    setNodes((current) => [...current, node]);
    selectNode(node.id);
    markUnsaved();
    void uploadNodeAsset(node.id, file);
  }, [markUnsaved, pushHistory, screenToFlowPosition, selectNode, setNodes, uploadNodeAsset]);

  const insertPastedVideoUrl = useCallback((sourceUrl: string) => {
    const bounds = flowStageRef.current?.getBoundingClientRect();
    const screenPoint = lastCanvasPointerRef.current ?? {
      x: bounds ? bounds.left + bounds.width / 2 : window.innerWidth / 2,
      y: bounds ? bounds.top + bounds.height / 2 : window.innerHeight / 2,
    };
    const position = screenToFlowPosition(screenPoint);
    const node = createNodeFromTemplate("upload", position, sequenceRef.current++);
    if (!node) return;
    node.data = { ...node.data, label: "URL video", status: "RUNNING", configText: sourceUrl, preview: "Downloading video from URL…" };
    pushHistory();
    setNodes((current) => [...current, node]);
    selectNode(node.id);
    markUnsaved();
    void importNodeAssetUrl(node.id, sourceUrl);
  }, [importNodeAssetUrl, markUnsaved, pushHistory, screenToFlowPosition, selectNode, setNodes]);

  useEffect(() => {
    const handlePaste = (event: ClipboardEvent) => {
      const imageFiles = [...(event.clipboardData?.items ?? [])]
        .filter((item) => item.kind === "file" && item.type.startsWith("image/"))
        .map((item) => item.getAsFile())
        .filter((file): file is File => file !== null);
      if (imageFiles.length) {
        event.preventDefault();
        imageFiles.forEach((file, index) => insertClipboardImage(file, index));
        return;
      }
      const target = event.target;
      const isEditable = target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement || (target instanceof HTMLElement && target.isContentEditable);
      if (isEditable) return;
      const sourceUrl = httpUrl(event.clipboardData?.getData("text/plain") ?? "");
      if (!sourceUrl) return;
      event.preventDefault();
      insertPastedVideoUrl(sourceUrl);
    };
    window.addEventListener("paste", handlePaste);
    return () => window.removeEventListener("paste", handlePaste);
  }, [insertClipboardImage, insertPastedVideoUrl]);

  const completeExperimentNode = useCallback((nodeId: string, experiment: ExperimentRun) => {
    setNodes((current) => {
      const invalidated = invalidateDescendants(current, edgesRef.current, nodeId);
      const completed = invalidated.map((node) => node.id === nodeId ? {
        ...node,
        data: {
          ...node.data,
          status: "SUCCEEDED" as NodeStatus,
          preview: experiment.output.title,
          output: experiment.output,
          duration: experiment.cache_hit ? "cache" : `${experiment.duration_ms}ms`,
          attemptCount: (node.data.attemptCount ?? 0) + 1,
          lastRunAt: experiment.created_at,
          lastExperimentId: experiment.id,
          outputArtifactIds: experiment.output_artifact_ids,
          lastRequestHash: experiment.request_hash,
          executionMode: experiment.execution_mode,
          lastCostUsd: experiment.cost_usd,
          logs: [...(node.data.logs ?? []), `${new Date(experiment.created_at).toLocaleTimeString("ko-KR")} · Experiment ${experiment.id} succeeded${experiment.cache_hit ? " · cache hit" : ""}`],
        },
      } : node);
      return refreshReadyStatuses(completed, edgesRef.current);
    });
    markUnsaved();
  }, [markUnsaved, setNodes]);

  const runStep = useCallback(async (nodeId: string, automatic = false): Promise<boolean> => {
    const node = nodesRef.current.find((candidate) => candidate.id === nodeId);
    if (!node || node.data.status === "RUNNING") return false;
    if (node.data.executable === false) return true;
    const inputError = stepInputError(node, nodesRef.current, edgesRef.current);
    if (inputError) {
      if (!automatic) notify(inputError, "error");
      return false;
    }
    if (node.data.key === "candidate.select") {
      setNodes((current) => current.map((candidate) => candidate.id === nodeId ? { ...candidate, data: { ...candidate.data, status: "WAITING_INPUT" } } : candidate));
      setCandidateNodeId(nodeId);
      setSelectedCandidate(0);
      setCandidateOpen(true);
      notify("후보를 선택하면 다음 Step을 실행할 수 있습니다.", "info");
      return false;
    }
    setNodes((current) => current.map((candidate) => candidate.id === nodeId ? { ...candidate, data: { ...candidate.data, status: "RUNNING", logs: [...(candidate.data.logs ?? []), `${new Date().toLocaleTimeString("ko-KR")} · Step started`] } } : candidate));
    notify(`${node.data.label} 실행 중…`, "info");
    const promptIndex = node.data.inputTypes?.indexOf("Prompt") ?? -1;
    const promptEdge = promptIndex >= 0 ? edgesRef.current.find((edge) => edge.target === nodeId && edge.targetHandle === inputHandleId("Prompt", promptIndex)) : undefined;
    const prompt = nodesRef.current.find((candidate) => candidate.id === promptEdge?.source)?.data.configText?.trim()
      || node.data.configText?.trim()
      || node.data.description;
    const inputSnapshots = edgesRef.current.filter((edge) => edge.target === nodeId).map((edge) => {
      const source = nodesRef.current.find((candidate) => candidate.id === edge.source);
      return {
        node_id: source?.id ?? edge.source,
        node_key: source?.data.key ?? "unknown",
        type: source?.data.outputType ?? "Any",
        label: source?.data.label ?? edge.source,
        description: source?.data.description,
        config_text: source?.data.configText,
        output_title: source?.data.output?.title,
        output_text: source?.data.output?.text,
        mime_type: source?.data.output?.mimeType,
        artifact_ids: source?.data.outputArtifactIds ?? [],
      };
    });
    try {
      const experiment = await frameflowApi.createExperiment({
        canvas_id: canvasIdRef.current,
        node_id: node.id,
        node_key: node.data.key,
        prompt,
        model_alias: node.data.model ?? "local",
        parameters: {
          resolution: node.data.resolution,
          aspect_ratio: node.data.aspectRatio,
          output_count: 1,
          transition: node.data.transition,
          target_duration_seconds: node.data.targetDurationSeconds,
          frame_timestamp_ms: node.data.frameTimestampMs,
          source_language: node.data.sourceLanguage,
          target_language: node.data.targetLanguage,
          voice_name: node.data.voiceName,
          provider: node.data.provider,
        },
        inputs: inputSnapshots,
      });
      if (experiment.status !== "SUCCEEDED") throw new Error(experiment.error ?? "Canvas step execution failed");
      if (cancelRunRef.current) return false;
      completeExperimentNode(nodeId, experiment);
      if (selectedNodeId === nodeId) {
        setExperimentHistory((current) => [experiment, ...current].slice(0, 20));
        setExperimentHistoryNodeId(nodeId);
        setExperimentHistoryError(null);
      }
      notify(`${node.data.label} 결과를 Artifact로 저장했습니다.${experiment.cache_hit ? " 동일 설정의 결과를 재사용했습니다." : ""}`, "success");
      return true;
    } catch (error) {
      const message = error instanceof Error ? error.message : "Canvas step execution failed";
      setNodes((current) => current.map((candidate) => candidate.id === nodeId ? { ...candidate, data: { ...candidate.data, status: "FAILED", logs: [...(candidate.data.logs ?? []), `${new Date().toLocaleTimeString("ko-KR")} · ${message}`] } } : candidate));
      setExperimentHistoryError(message);
      markUnsaved();
      notify(message, "error");
      return false;
    }
  }, [completeExperimentNode, markUnsaved, notify, selectedNodeId, setNodes]);

  const validateAndOpen = useCallback(() => {
    const errors = validateGraph(nodesRef.current, edgesRef.current);
    setCompileErrors(errors);
    setCompileOpen(true);
    notify(errors.length ? `${errors.length}개의 그래프 문제를 확인하세요.` : "그래프 검증을 통과했습니다.", errors.length ? "error" : "success");
  }, [notify]);

  const applyCanvasRunUpdate = useCallback((run: CanvasRunRecord) => {
    const byNodeId = new Map(run.node_runs.map((node) => [node.canvas_node_id, node]));
    setNodes((current) => current.map((node) => {
      const server = byNodeId.get(node.id);
      if (!server) return node;
      const output = Object.keys(server.output ?? {}).length ? server.output as CanvasOutput : undefined;
      const status = server.status as NodeStatus;
      const statusChanged = node.data.status !== status;
      return {
        ...node,
        data: {
          ...node.data,
          status,
          preview: output?.title ?? node.data.preview,
          output: output ?? node.data.output,
          outputArtifactIds: server.output_artifact_ids.length ? server.output_artifact_ids : node.data.outputArtifactIds,
          duration: server.duration_ms ? `${server.duration_ms}ms` : node.data.duration,
          attemptCount: server.attempt_count,
          lastRequestHash: server.request_hash ?? node.data.lastRequestHash,
          lastCostUsd: server.cost_usd,
          logs: statusChanged ? [...(node.data.logs ?? []), `${new Date().toLocaleTimeString("ko-KR")} · Worker ${status}${server.error ? ` · ${server.error}` : ""}`] : node.data.logs,
        },
      };
    }));
    setGraphProgress(run.progress);
    const waiting = run.node_runs.find((node) => node.node_key === "candidate.select" && node.status === "WAITING_INPUT");
    if (waiting) {
      setCandidateNodeId(waiting.canvas_node_id);
      setSelectedCandidate(0);
      setCandidateOpen(true);
    }
    if (["SUCCEEDED", "FAILED", "CANCELED"].includes(run.status)) {
      canvasRunEventsRef.current?.close();
      canvasRunEventsRef.current = null;
      setGraphRunning(false);
      setActiveCanvasRunId(null);
      setSaveState("Unsaved");
      notify(run.status === "SUCCEEDED" ? "Worker가 모든 Step 실행을 완료했습니다." : run.status === "CANCELED" ? "Worker 실행을 중단했습니다." : "Worker 실행이 실패했습니다.", run.status === "SUCCEEDED" ? "success" : "error");
    } else {
      setGraphRunning(true);
    }
  }, [notify, setNodes]);

  const subscribeCanvasRun = useCallback((runId: string) => {
    canvasRunEventsRef.current?.close();
    const source = new EventSource(frameflowApi.canvasRunEventsUrl(runId));
    source.addEventListener("canvas.run.updated", (event) => {
      applyCanvasRunUpdate(JSON.parse((event as MessageEvent<string>).data) as CanvasRunRecord);
    });
    source.onerror = () => {
      void frameflowApi.getCanvasRun(runId).then(applyCanvasRunUpdate).catch(() => undefined);
    };
    canvasRunEventsRef.current = source;
  }, [applyCanvasRunUpdate]);

  useEffect(() => {
    if (!activeCanvasRunId || canvasRunEventsRef.current) return;
    void frameflowApi.getCanvasRun(activeCanvasRunId)
      .then((run) => {
        applyCanvasRunUpdate(run);
        if (!["SUCCEEDED", "FAILED", "CANCELED"].includes(run.status)) subscribeCanvasRun(activeCanvasRunId);
      })
      .catch(() => setActiveCanvasRunId(null));
  }, [activeCanvasRunId, applyCanvasRunUpdate, subscribeCanvasRun]);

  const runGraph = useCallback(async () => {
    const errors = validateGraph(nodesRef.current, edgesRef.current);
    if (errors.length) {
      setCompileErrors(errors);
      setCompileOpen(true);
      return;
    }
    setCompileOpen(false);
    setGraphRunning(true);
    setGraphProgress(0);
    cancelRunRef.current = false;
    setNodes((current) => current.map((node) => node.data.executable === false ? node : { ...node, data: { ...node.data, status: "QUEUED" as NodeStatus, output: undefined, preview: undefined, outputArtifactIds: undefined } }));
    try {
      const run = await frameflowApi.createCanvasRun({
        canvas_id: canvasIdRef.current,
        name: canvasName,
        nodes: nodesRef.current.map((node) => ({ ...node, data: { ...node.data, output: node.data.output?.url?.startsWith("blob:") ? undefined : node.data.output } })) as Array<Record<string, unknown>>,
        edges: edgesRef.current as Array<Record<string, unknown>>,
      });
      setActiveCanvasRunId(run.id);
      setSaveState("Unsaved");
      applyCanvasRunUpdate(run);
      subscribeCanvasRun(run.id);
      notify("Canvas Run을 Worker에 전달했습니다.", "success");
    } catch (error) {
      setGraphRunning(false);
      notify(error instanceof Error ? error.message : "Canvas Run 시작에 실패했습니다.", "error");
    }
  }, [applyCanvasRunUpdate, canvasName, notify, setNodes, subscribeCanvasRun]);

  const stopGraph = async () => {
    cancelRunRef.current = true;
    if (activeCanvasRunId) {
      try {
        applyCanvasRunUpdate(await frameflowApi.cancelCanvasRun(activeCanvasRunId));
      } catch (error) {
        notify(error instanceof Error ? error.message : "Canvas Run 취소에 실패했습니다.", "error");
      }
      return;
    }
    setNodes((current) => current.map((node) => node.data.status === "RUNNING" ? { ...node, data: { ...node.data, status: "CANCELED" } } : node));
  };

  const candidateOptions = useMemo<CandidateOption[]>(() => {
    if (!candidateNodeId) return [];
    return edges
      .filter((edge) => edge.target === candidateNodeId)
      .map((edge) => nodes.find((node) => node.id === edge.source))
      .filter((node): node is StudioFlowNode => Boolean(node?.data.output?.kind === "video" && node.data.outputArtifactIds?.length))
      .map((node) => ({ id: node.id, label: node.data.label, output: node.data.output!, artifactIds: node.data.outputArtifactIds! }));
  }, [candidateNodeId, edges, nodes]);

  const approveCandidates = async () => {
    const selected = candidateOptions[selectedCandidate];
    if (activeCanvasRunId && candidateNodeId && selected) {
      try {
        const run = await frameflowApi.selectCanvasCandidate(activeCanvasRunId, candidateNodeId, selected.artifactIds[0]);
        applyCanvasRunUpdate(run);
        setCandidateOpen(false);
        setCandidateNodeId(null);
      } catch (error) {
        notify(error instanceof Error ? error.message : "Candidate 선택에 실패했습니다.", "error");
      }
      return;
    }
    if (candidateNodeId && selected) {
      setNodes((current) => {
        const invalidated = invalidateDescendants(current, edgesRef.current, candidateNodeId);
        const completed = invalidated.map((node) => node.id === candidateNodeId ? {
          ...node,
          data: {
            ...node.data,
            status: "SUCCEEDED" as NodeStatus,
            preview: selected.output.title,
            output: selected.output,
            outputArtifactIds: selected.artifactIds,
            duration: "selected",
            attemptCount: (node.data.attemptCount ?? 0) + 1,
            lastRunAt: new Date().toISOString(),
            logs: [...(node.data.logs ?? []), `${new Date().toLocaleTimeString("ko-KR")} · ${selected.label} selected`],
          },
        } : node);
        return refreshReadyStatuses(completed, edgesRef.current);
      });
      markUnsaved();
      notify(`${selected.label} 결과를 선택했습니다.`, "success");
    }
    setCandidateOpen(false);
    setCandidateNodeId(null);
  };

  const clearCanvas = () => {
    pushHistory();
    setNodes([]);
    setEdges([]);
    setExperimentHistory([]);
    setActiveCanvasRunId(null);
    selectNode(null);
    markUnsaved();
    notify("Canvas의 모든 노드를 지웠습니다.", "success");
  };

  const newCanvas = () => {
    pushHistory();
    canvasIdRef.current = createCanvasId();
    setNodes([]);
    setEdges([]);
    setExperimentHistory([]);
    setCanvasName("Untitled canvas");
    selectNode(null);
    setPaletteOpen(false);
    setPickerOpen(true);
    setPickerInsertPosition(null);
    markUnsaved();
    notify("새 빈 Canvas를 만들었습니다. + 버튼으로 첫 Step을 추가하세요.", "success");
  };

  const selectedNode = nodes.find((node) => node.id === selectedNodeId);
  const selectedInputError = selectedNode ? stepInputError(selectedNode, nodes, edges) : null;
  const selectedProvider = selectedNode ? selectedNode.data.provider ?? providerFromModel(selectedNode.data.model) : "google";
  const selectedModelOptions = selectedNode ? modelOptionsForNode(selectedNode.data.key, selectedProvider) : [];
  const selectedPromptText = selectedNode ? (() => {
    const promptIndex = selectedNode.data.inputTypes?.indexOf("Prompt") ?? -1;
    if (promptIndex < 0) return "";
    const promptEdge = edges.find((edge) => edge.target === selectedNode.id && edge.targetHandle === inputHandleId("Prompt", promptIndex));
    return nodes.find((node) => node.id === promptEdge?.source)?.data.configText?.trim() ?? "";
  })() : "";
  useEffect(() => {
    if (!selectedNodeId || selectedNode?.data.executable === false || selectedNode?.data.key === "candidate.select") return;
    let active = true;
    frameflowApi.listExperiments(canvasIdRef.current, selectedNodeId)
      .then((items) => { if (active) { setExperimentHistory(items); setExperimentHistoryNodeId(selectedNodeId); setExperimentHistoryError(null); } })
      .catch((error) => { if (active) { setExperimentHistoryNodeId(selectedNodeId); setExperimentHistoryError(error instanceof Error ? error.message : "Experiment history failed"); } });
    return () => { active = false; };
  }, [selectedNode?.data.executable, selectedNode?.data.key, selectedNodeId]);
  const visibleExperimentHistory = experimentHistoryNodeId === selectedNodeId ? experimentHistory : [];

  const markExperimentBaseline = async (experimentId: string) => {
    try {
      const baseline = await frameflowApi.setExperimentBaseline(experimentId);
      setExperimentHistory((current) => current.map((item) => ({ ...item, is_baseline: item.id === baseline.id })));
      notify("비교 기준 실행으로 지정했습니다.", "success");
    } catch (error) {
      notify(error instanceof Error ? error.message : "Baseline update failed", "error");
    }
  };
  const selectedVideoInputCount = selectedNode ? edges.filter((edge) => {
    const source = nodes.find((node) => node.id === edge.source);
    return edge.target === selectedNode.id && source?.data.outputType === "Video";
  }).length : 0;
  const paletteGroups = useMemo(() => {
    const query = paletteQuery.trim().toLowerCase();
    const groups = ["Quick", "References", "Image", "Video", "Audio", "Utilities"] as const;
    return groups.map((group) => ({ group, items: nodeTemplates.filter((template) => template.visible !== false && template.group === group && (!query || `${template.label} ${template.data.key} ${template.data.outputType ?? ""}`.toLowerCase().includes(query))) })).filter((section) => section.items.length);
  }, [paletteQuery]);
  const pickerGroups = useMemo(() => {
    const query = pickerQuery.trim().toLowerCase();
    const groups = ["Quick", "References", "Image", "Video", "Audio", "Utilities"] as const;
    return groups.map((group) => ({ group, items: nodeTemplates.filter((template) => template.visible !== false && template.group === group && (!query || `${template.label} ${template.data.key} ${template.data.outputType ?? ""}`.toLowerCase().includes(query))) })).filter((section) => section.items.length);
  }, [pickerQuery]);
  const cost = graphCost(nodes);
  const successfulCount = nodes.filter((node) => node.data.status === "SUCCEEDED").length;
  const nodeActions = useMemo<NodeActions>(() => ({ runStep: (nodeId) => void runStep(nodeId), updateConfig: updateNodeConfig, uploadAsset: uploadNodeAsset, importAssetUrl: importNodeAssetUrl, selectAsset: selectStoredAsset, assetOptions }), [assetOptions, importNodeAssetUrl, runStep, selectStoredAsset, updateNodeConfig, uploadNodeAsset]);

  return (
    <div className={`canvas-shell ${paletteOpen ? "" : "palette-hidden"} ${inspectorOpen && selectedNode ? "with-inspector" : ""}`}>
      <div className="canvas-toolbar">
        <div className="workflow-switcher canvas-name-field"><span className="workflow-glyph"><Workflow size={16} /></span><span><small>Canvas</small><input value={canvasName} onChange={(event) => { setCanvasName(event.target.value); markUnsaved(); }} aria-label="Canvas name" /></span></div>
        <button className="secondary-button new-canvas-button" type="button" onClick={newCanvas} disabled={graphRunning}><FilePlus2 size={15} /> New</button>
        <span className="canvas-divider" />
        <button className="tool-icon" type="button" onClick={undo} disabled={!history.length} aria-label="Undo"><Undo2 size={16} /></button>
        <button className="tool-icon" type="button" onClick={redo} disabled={!future.length} aria-label="Redo"><Redo2 size={16} /></button>
        <span className="canvas-divider" />
        <button className={`saved-indicator save-${saveState.toLowerCase()}`} type="button" onClick={() => { window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ ...cloneGraph(nodes, edges), id: canvasIdRef.current, name: canvasName, activeRunId: activeCanvasRunId })); setSaveState("Saved"); }}><Save size={13} /> {saveState}</button>
        <button className="tool-icon reset-canvas" type="button" onClick={clearCanvas} disabled={graphRunning || !nodes.length} aria-label="Clear canvas"><Trash2 size={15} /></button>
        <div className="canvas-toolbar-spacer" />
        <button className="secondary-button" type="button" onClick={validateAndOpen}><CircleGauge size={15} /> Validate</button>
        <div className="cost-estimate"><span><CircleDollarSign size={13} /> Est. ${cost.toFixed(2)}</span><small>{nodes.length} steps · {edges.length} connections</small></div>
        {graphRunning && <button className="secondary-button run-stop" type="button" onClick={stopGraph}><CircleStop size={15} /> Stop</button>}
        <button className="primary-button run-button" type="button" onClick={validateAndOpen} disabled={graphRunning}>
          {graphRunning ? <><RefreshCw className="spin" size={15} /> Running {graphProgress}%</> : <><Play size={14} fill="currentColor" /> Run workflow</>}
        </button>
      </div>

      {paletteOpen && <aside className="node-palette">
        <div className="palette-title"><div><span className="subtle-label">Node library</span><strong>Add a step</strong></div><span className="node-count">{nodeTemplates.filter((item) => item.visible !== false).length}</span></div>
        <label className="input-shell palette-search"><Sparkles size={14} /><input value={paletteQuery} onChange={(event) => setPaletteQuery(event.target.value)} placeholder="Find node…" /></label>
        <div className="palette-groups">
          {paletteGroups.map((section) => <div className="palette-group" key={section.group}>
            {section.group !== "Quick" && <div className="palette-group-title"><ChevronDown size={12} />{section.group}</div>}
            {section.items.map((template) => {
              const Icon = icons[template.data.icon];
              return <button className="palette-item" type="button" draggable key={template.id} onClick={() => addTemplateNode(template.id)} onDragStart={(event) => { event.dataTransfer.setData("application/frameflow-node", template.id); event.dataTransfer.effectAllowed = "copy"; }}>
                <GripVertical size={12} /><span className="palette-icon"><Icon size={15} /></span><span><strong>{template.label}</strong><small>{template.data.outputType ?? "Checkpoint"}</small></span><Plus size={13} />
              </button>;
            })}
          </div>)}
          {!paletteGroups.length && <div className="palette-empty">일치하는 노드가 없습니다.</div>}
        </div>
        <div className="palette-note"><LockKeyhole size={15} /><span><strong>Click or drag to add</strong><small>포트 타입이 맞는 Step끼리 연결하세요.</small></span></div>
      </aside>}

      <div className="flow-stage" ref={flowStageRef} onMouseMove={(event) => { lastCanvasPointerRef.current = { x: event.clientX, y: event.clientY }; }}>
        <NodeActionsContext.Provider value={nodeActions}><ReactFlow
          nodes={nodes}
          edges={edges.map((edge) => ({ ...edge, animated: !!nodes.find((node) => node.id === edge.target && node.data.status === "RUNNING"), style: { stroke: nodes.find((node) => node.id === edge.source)?.data.status === "SUCCEEDED" ? "#6f68de" : "#a8aaa3", strokeWidth: 1.5 } }))}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          onNodesChange={handleNodesChange}
          onEdgesChange={handleEdgesChange}
          onConnect={onConnect}
          isValidConnection={isValidConnection}
          onDrop={handleDrop}
          onDragOver={(event) => { event.preventDefault(); event.dataTransfer.dropEffect = "copy"; }}
          onNodeClick={(_, node) => selectNode(node.id)}
          onNodeDoubleClick={(_, node) => void runStep(node.id)}
          onNodeDragStart={() => { dragStartRef.current = cloneGraph(nodesRef.current, edgesRef.current); }}
          onNodeDragStop={() => { if (dragStartRef.current) pushHistory(dragStartRef.current); dragStartRef.current = null; markUnsaved(); }}
          onPaneClick={(event) => { selectNode(null); if (event.detail === 2) { setPickerInsertPosition(screenToFlowPosition({ x: event.clientX, y: event.clientY })); setPickerOpen(true); } }}
          deleteKeyCode={["Backspace", "Delete"]}
          multiSelectionKeyCode={["Meta", "Shift"]}
          selectionOnDrag={interactionMode === "select"}
          panOnDrag={interactionMode === "pan"}
          fitView
          fitViewOptions={{ padding: 0.12, minZoom: 0.42, maxZoom: 0.78 }}
          minZoom={0.2}
          maxZoom={1.6}
          proOptions={{ hideAttribution: true }}
          defaultEdgeOptions={{ type: EDGE_TYPE }}
        >
          <Background variant={BackgroundVariant.Dots} gap={18} size={1} color="#c9cbc4" />
          <Controls position="bottom-center" showInteractive={false} />
          <MiniMap position="bottom-right" pannable zoomable nodeColor={(node) => node.id === selectedNodeId ? "#675cf6" : node.data.status === "SUCCEEDED" ? "#79b9a0" : "#d3d4ce"} maskColor="rgba(246,246,243,.7)" />
          <div className="canvas-legend"><span><i className="port-format" /> Format</span><span><i className="port-media" /> Media</span><span><i className="port-data" /> Data</span><span>Double-click: Run step</span></div>
        </ReactFlow></NodeActionsContext.Provider>
        {!nodes.length && <div className="canvas-empty-state"><span className="empty-spark"><Sparkles size={22} /></span><h2>Start with a blank canvas</h2><p>저장된 실제 Asset과 Prompt 노드를 추가해 Workflow를 구성하세요.</p><div><button className="primary-button" type="button" onClick={() => setPickerOpen(true)}><Plus size={15} /> Add first step</button></div></div>}
      </div>

      {inspectorOpen && selectedNode && (
        <aside className="node-inspector">
          <div className="inspector-heading"><div><span className="subtle-label">Node inspector</span><strong>{selectedNode.data.label}</strong></div><button className="icon-button tiny" type="button" onClick={() => setInspectorOpen(false)}><PanelRightClose size={16} /></button></div>
          <div className="inspector-status"><StatusPill status={selectedNode.data.status} /><span>{selectedNode.data.key}</span></div>
          <div className="inspector-tabs"><span className="active">Settings</span></div>
          <div className="inspector-content">
            {selectedNode.data.executable !== false && <button className="primary-button step-run-button" type="button" onClick={() => void runStep(selectedNode.id)} disabled={selectedNode.data.status === "RUNNING" || graphRunning || !!selectedInputError}>
              {selectedNode.data.status === "RUNNING" ? <><RefreshCw className="spin" size={15} /> Running step…</> : <><Play size={14} fill="currentColor" /> Run this step</>}
            </button>}
            <p className={`step-run-help ${selectedInputError ? "has-error" : ""}`}>{selectedNode.data.executable === false ? "입력 또는 Canvas 정리용 노드입니다." : selectedInputError ?? "이 Step만 실행합니다. 연결된 입력을 사용합니다."}</p>
            {selectedNode.data.kind === "generate" && <div className="generator-settings">
              <div className={`connected-prompt-preview ${selectedPromptText ? "connected" : "missing"}`}><span>Connected prompt</span><p>{selectedPromptText || "Prompt 노드를 연결하고 내용을 입력하세요."}</p></div>
              <div className="generator-setting-grid provider-model-selectors">
                <label><span>Provider</span><select value={selectedProvider} onChange={(event) => { const provider = event.target.value as ProviderName; const model = modelOptionsForNode(selectedNode.data.key, provider)[0]?.value; updateSelectedData({ provider, model }); }}>{providerOptionsForNode(selectedNode.data.key).map((option) => <option value={option.value} key={option.value}>{option.label}</option>)}</select></label>
                <label><span>Model</span><select value={selectedNode.data.model ?? selectedModelOptions[0]?.value ?? ""} onChange={(event) => updateSelectedData({ model: event.target.value })}>{selectedModelOptions.map((option) => <option value={option.value} key={option.value}>{option.label}</option>)}</select></label>
              </div>
              {selectedNode.data.resolution && <div className="generator-setting-grid">
                <label><span>Resolution</span><select value={selectedNode.data.resolution ?? "1080p"} onChange={(event) => updateSelectedData({ resolution: event.target.value })}><option>1080p</option><option>2K</option><option>4K</option><option>24kHz</option></select></label>
                <label><span>Aspect ratio</span><select value={selectedNode.data.aspectRatio ?? "9:16"} onChange={(event) => updateSelectedData({ aspectRatio: event.target.value })}><option>9:16</option><option>1:1</option><option>16:9</option><option>Audio</option></select></label>
              </div>}
              {selectedNode.data.batchSize && <div className="batch-setting single-output-setting"><span><small>Output count</small><strong>Canvas Step은 단일 결과를 출력합니다.</strong></span><b>1</b></div>}
            </div>}
            {selectedNode.data.key === "video.edit" && <div className="video-editor-settings">
              <div className={`editor-input-count ${selectedVideoInputCount ? "connected" : "missing"}`}><span>Connected videos</span><strong>{selectedVideoInputCount}</strong><small>{selectedVideoInputCount ? "여러 입력은 연결 순서대로 편집됩니다." : "Video 출력들을 왼쪽 입력 포트에 연결하세요."}</small></div>
              <label className="field-label"><span>Transition</span><select value={selectedNode.data.transition ?? "hard_cut"} onChange={(event) => updateSelectedData({ transition: event.target.value })}><option value="hard_cut">Hard cut</option><option value="crossfade">Crossfade</option><option value="dip_to_black">Dip to black</option></select></label>
              <div className="generator-setting-grid">
                <label><span>Output ratio</span><select value={selectedNode.data.aspectRatio ?? "9:16"} onChange={(event) => updateSelectedData({ aspectRatio: event.target.value })}><option>9:16</option><option>1:1</option><option>16:9</option></select></label>
                <label><span>Target length</span><select value={String(selectedNode.data.targetDurationSeconds ?? 30)} onChange={(event) => updateSelectedData({ targetDurationSeconds: Number(event.target.value) })}><option value="15">15s</option><option value="30">30s</option><option value="45">45s</option><option value="60">60s</option></select></label>
              </div>
            </div>}
            {selectedNode.data.key === "video.frame_extract" && <div className="video-editor-settings frame-extract-settings">
              <div className="editor-input-count connected"><span>Frame output</span><strong>1</strong><small>연결된 Video에서 지정 시점의 JPEG를 추출합니다.</small></div>
              <label className="field-label"><span>Timestamp (seconds)</span><input type="number" min="0" step="0.1" value={(selectedNode.data.frameTimestampMs ?? 0) / 1000} onChange={(event) => updateSelectedData({ frameTimestampMs: Math.max(0, Math.round(Number(event.target.value || 0) * 1000)) })} /><small>정확한 프레임 탐색을 위해 millisecond로 실행 이력에 저장됩니다.</small></label>
            </div>}
            {selectedNode.data.key === "video.translate" && <div className="video-editor-settings">
              <div className="editor-input-count connected"><span>Live pipeline</span><strong>3</strong><small>Chirp 3 STT → Gemini translation → Gemini TTS</small></div>
              <div className="generator-setting-grid">
                <label><span>Source language</span><select value={selectedNode.data.sourceLanguage ?? "auto"} onChange={(event) => updateSelectedData({ sourceLanguage: event.target.value })}><option value="auto">Auto detect</option><option value="ko-KR">Korean</option><option value="en-US">English</option><option value="ja-JP">Japanese</option><option value="zh-CN">Chinese</option><option value="es-ES">Spanish</option></select></label>
                <label><span>Target language</span><select value={selectedNode.data.targetLanguage ?? "ko-KR"} onChange={(event) => updateSelectedData({ targetLanguage: event.target.value })}><option value="ko-KR">Korean</option><option value="en-US">English</option><option value="ja-JP">Japanese</option><option value="zh-CN">Chinese</option><option value="es-ES">Spanish</option></select></label>
              </div>
              <label className="field-label"><span>Gemini voice</span><select value={selectedNode.data.voiceName ?? "Kore"} onChange={(event) => updateSelectedData({ voiceName: event.target.value })}><option value="Kore">Kore</option><option value="Aoede">Aoede</option><option value="Charon">Charon</option><option value="Puck">Puck</option></select><small>Google Cloud ADC와 Speech-to-Text·Vertex AI 권한이 필요합니다.</small></label>
            </div>}
            <label className="field-label"><span>Node name</span><input value={selectedNode.data.label} onChange={(event) => updateSelectedData({ label: event.target.value })} /></label>
            <label className="field-label"><span>Description</span><textarea value={selectedNode.data.description} onChange={(event) => updateSelectedData({ description: event.target.value })} /></label>
            {selectedNode.data.model && selectedNode.data.kind !== "generate" && <label className="field-label"><span>Runtime engine</span><input value={selectedNode.data.model} readOnly /><small>로컬 실행 엔진과 버전이 실행 이력에 고정됩니다.</small></label>}
            <div className="inspector-section-title"><span>Input contracts</span><Braces size={14} /></div>
            {(selectedNode.data.inputTypes?.length ? selectedNode.data.inputTypes : ["Source node"]).map((type, index) => {
              const connectionCount = type === "Source node" ? 0 : edges.filter((edge) => edge.target === selectedNode.id && edge.targetHandle === inputHandleId(type as PortType, index)).length;
              const connected = connectionCount > 0;
              const required = selectedNode.data.requiredInputTypes?.includes(type as PortType) ?? selectedNode.data.inputsRequired !== false;
              const optional = !required;
              const acceptsMany = selectedNode.data.multiInputTypes?.includes(type as PortType);
              return <div className="port-contract" key={`${type}-${index}`}><span className={`contract-dot type-${String(type).toLowerCase()}`} /><span><strong>{type}{acceptsMany ? " × N" : ""}</strong><small>{type === "Source node" ? "No input required" : connected ? `${connectionCount} connected` : optional ? "Optional input" : "Required · not connected"}</small></span>{type !== "Source node" && (connected ? <CircleCheck size={15} /> : optional ? <span className="optional-port">Optional</span> : <CircleAlert size={15} className="contract-warning" />)}</div>;
            })}
            <div className="inspector-section-title"><span>Runtime</span><CircleGauge size={14} /></div>
            <div className="runtime-grid"><div><small>Last duration</small><strong>{selectedNode.data.duration ?? "—"}</strong></div><div><small>Est. cost</small><strong>{selectedNode.data.cost ?? "$0.00"}</strong></div><div><small>Attempts</small><strong>{selectedNode.data.attemptCount ?? 0}</strong></div><div><small>Output</small><strong>{selectedNode.data.outputType ?? "—"}</strong></div></div>
            {selectedNode.data.executable !== false && selectedNode.data.key !== "candidate.select" && <div className="experiment-history">
              <div className="experiment-history-head"><span><ListRestart size={13} /> Experiment history</span><small>{visibleExperimentHistory.length} runs</small></div>
              {experimentHistoryNodeId === selectedNodeId && experimentHistoryError && <p className="experiment-history-state error">{experimentHistoryError}</p>}
              {experimentHistoryNodeId === selectedNodeId && !experimentHistoryError && !visibleExperimentHistory.length && <p className="experiment-history-state">이 설정으로 저장된 실행이 없습니다.</p>}
              {visibleExperimentHistory.map((experiment) => <article className={`experiment-run ${experiment.is_baseline ? "baseline" : ""}`} key={experiment.id}>
                <div><strong>{experiment.model_alias.replace("google.", "")}</strong><time>{new Date(experiment.created_at).toLocaleString("ko-KR", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" })}</time></div>
                <p>{experiment.prompt}</p>
                <div className="experiment-run-meta"><span>{experiment.cache_hit ? "Cache" : experiment.execution_mode}</span><span>{experiment.duration_ms}ms</span><span>${experiment.cost_usd.toFixed(2)}</span><code>{experiment.request_hash.slice(0, 7)}</code></div>
                <div className="experiment-run-actions">{experiment.is_baseline ? <span><BadgeCheck size={12} /> Baseline</span> : <button type="button" onClick={() => void markExperimentBaseline(experiment.id)}>Set baseline</button>}<button type="button" onClick={() => updateSelectedData({ output: experiment.output, preview: experiment.output.title, lastExperimentId: experiment.id, outputArtifactIds: experiment.output_artifact_ids })}>Show result</button></div>
              </article>)}
            </div>}
            {selectedNode.data.preview && <div className="step-output-preview"><span>Latest output</span><strong>{selectedNode.data.preview}</strong></div>}
            {selectedNode.data.key === "candidate.select" && <button className="candidate-preview-button" type="button" onClick={() => { setCandidateNodeId(selectedNode.id); setSelectedCandidate(0); setCandidateOpen(true); }}><span className="candidate-stack"><i /><i /><i /></span><span><strong>Open candidate grid</strong><small>Compare connected video outputs</small></span><ChevronRight size={16} /></button>}
          </div>
          <div className="inspector-edit-actions"><button className="secondary-button" type="button" onClick={duplicateSelected}><Copy size={14} /> Duplicate</button><button className="danger-button" type="button" onClick={deleteSelected}><Trash2 size={14} /> Delete</button></div>
          {selectedNode.data.executable !== false && <div className="inspector-actions"><button className="secondary-button" type="button" onClick={() => void runStep(selectedNode.id)} disabled={!!selectedInputError}><ListRestart size={13} /> Retry</button><button className="secondary-button" type="button" disabled={!!selectedInputError} onClick={() => { updateSelectedData({ status: selectedNode.data.requiredInputTypes?.length || (selectedNode.data.inputTypes?.length && selectedNode.data.inputsRequired !== false) ? "BLOCKED" : "READY", preview: undefined, output: undefined }); window.setTimeout(() => void runStep(selectedNode.id), 0); }}><RefreshCw size={13} /> Regenerate</button><button className="secondary-button" type="button" onClick={duplicateSelected}><GitFork size={13} /> Fork</button></div>}
        </aside>
      )}

      {!inspectorOpen && selectedNode && <button className="open-inspector" type="button" onClick={() => setInspectorOpen(true)}><ChevronRight size={16} /></button>}

      {graphRunning && <div className="run-progress-toast running"><span className="run-pulse"><i /></span><span><strong>Workflow is running</strong><small>{graphProgress}% · {successfulCount}/{nodes.length} steps · ${cost.toFixed(2)}</small></span><div className="toast-progress"><i style={{ width: `${graphProgress}%` }} /></div></div>}
      {toast && <div className={`canvas-toast toast-${toast.tone}`}>{toast.tone === "success" ? <CircleCheck size={16} /> : toast.tone === "error" ? <CircleAlert size={16} /> : <Sparkles size={16} />}<span>{toast.message}</span></div>}

      <div className="canvas-bottom-toolbar">
        <button className={interactionMode === "select" ? "active" : ""} type="button" onClick={() => setInteractionMode("select")} title="Select"><MousePointer2 size={17} /></button>
        <button className={interactionMode === "pan" ? "active" : ""} type="button" onClick={() => setInteractionMode("pan")} title="Pan"><Hand size={17} /></button>
        <i />
        <button className={paletteOpen ? "active" : ""} type="button" onClick={() => setPaletteOpen((value) => !value)} title="Node library"><Layers3 size={17} /></button>
        <button className="add-step-fab" type="button" onClick={() => { setPickerInsertPosition(null); setPickerOpen((value) => !value); }} title="Add step"><Plus size={19} /></button>
      </div>

      {pickerOpen && <div className="node-picker">
        <div className="node-picker-search"><Search size={16} /><input autoFocus value={pickerQuery} onChange={(event) => setPickerQuery(event.target.value)} placeholder="Search steps…" /><button type="button" onClick={() => { setPickerOpen(false); setPickerInsertPosition(null); }}><X size={15} /></button></div>
        <div className="node-picker-list">{pickerGroups.map((section) => <div key={section.group}>{section.group !== "Quick" && <span>{section.group}</span>}{section.items.map((template) => { const Icon = icons[template.data.icon]; return <button type="button" key={template.id} onClick={() => addTemplateNode(template.id)}><i className={`picker-icon kind-${template.data.kind}`}><Icon size={15} /></i><span><strong>{template.label}</strong><small>{template.data.description}</small></span><Plus size={13} /></button>; })}</div>)}{!pickerGroups.length && <p>No matching steps</p>}</div>
      </div>}

      {compileOpen && <CompileDialog errors={compileErrors} nodeCount={nodes.length} edgeCount={edges.length} estimatedCost={cost} onClose={() => setCompileOpen(false)} onRun={() => void runGraph()} />}
      {candidateOpen && <CandidateDialog candidates={candidateOptions} selected={selectedCandidate} setSelected={setSelectedCandidate} onClose={() => setCandidateOpen(false)} onApprove={() => void approveCandidates()} />}
    </div>
  );
}

function CompileDialog({ errors, nodeCount, edgeCount, estimatedCost, onClose, onRun }: { errors: string[]; nodeCount: number; edgeCount: number; estimatedCost: number; onClose: () => void; onRun: () => void }) {
  const valid = errors.length === 0;
  return <div className="modal-backdrop" onMouseDown={onClose}><section className="modal-card compile-modal" onMouseDown={(event) => event.stopPropagation()}>
    <div className="modal-heading"><div><span className="subtle-label">Graph validation</span><h2>{valid ? "Ready to run" : "Graph needs attention"}</h2><p>{valid ? "모든 Step과 포트 연결을 확인했습니다." : "실행 전에 아래 문제를 해결하세요."}</p></div><button className="icon-button" type="button" onClick={onClose}><X size={17} /></button></div>
    {valid ? <div className="compile-checks"><div><BadgeCheck size={17} /><span><strong>Graph contracts valid</strong><small>{nodeCount} nodes · {edgeCount} typed connections · no cycles</small></span></div><div><ShieldCheck size={17} /><span><strong>Reference isolation enforced</strong><small>Generation steps receive structured Format only</small></span></div><div><Zap size={17} /><span><strong>Ready for step execution</strong><small>Steps run in dependency order</small></span></div></div> : <div className="validation-errors">{errors.map((error) => <div key={error}><CircleAlert size={15} /><span>{error}</span></div>)}</div>}
    <div className="compile-summary"><div><small>Steps</small><strong>{nodeCount}</strong></div><div><small>Connections</small><strong>{edgeCount}</strong></div><div><small>Estimated cost</small><strong>${estimatedCost.toFixed(2)}</strong></div><div><small>Execution</small><strong>Dependency DAG</strong></div></div>
    <div className="modal-actions"><button className="secondary-button" type="button" onClick={onClose}>Back to edit</button>{valid && <button className="primary-button" type="button" onClick={onRun}><Rocket size={15} /> Run {nodeCount} steps</button>}</div>
  </section></div>;
}

function CandidateDialog({ candidates, selected, setSelected, onClose, onApprove }: { candidates: CandidateOption[]; selected: number; setSelected: (value: number) => void; onClose: () => void; onApprove: () => void }) {
  const active = candidates[selected];
  return <div className="modal-backdrop candidate-backdrop" onMouseDown={onClose}><section className="candidate-dialog" onMouseDown={(event) => event.stopPropagation()}>
    <div className="candidate-dialog-head"><div><span className="subtle-label">Human review · Candidate Select step</span><h2>Choose a connected video</h2><p>연결된 실제 Video Artifact 중 다음 Step으로 전달할 결과를 선택합니다.</p></div><button className="icon-button" type="button" onClick={onClose}><X size={17} /></button></div>
    <div className="candidate-grid">{candidates.map((candidate, index) => <button type="button" key={candidate.id} onClick={() => setSelected(index)} className={`candidate-card ${selected === index ? "selected" : ""}`}><div className="candidate-video"><video src={candidate.output.url} muted loop autoPlay playsInline preload="metadata" />{selected === index && <i className="selected-check"><BadgeCheck size={18} /></i>}</div><div><span><strong>{candidate.label}</strong><small>{candidate.output.title}</small></span><span className="ai-score"><Film size={11} /> Artifact</span></div></button>)}</div>
    {!candidates.length && <div className="candidate-details"><div><span className="subtle-label">No runnable candidates</span><p>Artifact가 저장된 Video 출력 노드를 하나 이상 연결한 뒤 다시 실행하세요.</p></div></div>}
    {active && <div className="candidate-details"><div><span className="subtle-label">Selected output</span><p>{active.output.title} · {active.artifactIds.join(", ")}</p></div></div>}
    <div className="candidate-footer"><span>{active ? <><BadgeCheck size={16} /> {active.label} selected · original Artifact remains immutable</> : "Video Artifact connection required"}</span><div><button className="primary-button" type="button" onClick={onApprove} disabled={!active}>Use candidate & complete step <ArrowRight size={15} /></button></div></div>
  </section></div>;
}
