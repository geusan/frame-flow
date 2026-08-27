"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Background,
  BackgroundVariant,
  Controls,
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
  useEdgesState,
  useNodesState,
  useReactFlow,
} from "@xyflow/react";
import {
  ArrowLeft,
  BadgeCheck,
  Braces,
  ChevronDown,
  ChevronRight,
  CircleAlert,
  CircleCheck,
  CircleDollarSign,
  CircleGauge,
  CircleStop,
  Copy,
  GitFork,
  GripVertical,
  Hand,
  Layers3,
  ListRestart,
  LockKeyhole,
  MousePointer2,
  PanelRightClose,
  Play,
  Plus,
  Redo2,
  RefreshCw,
  Save,
  Search,
  Sparkles,
  Trash2,
  Undo2,
  Workflow,
  X,
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
  type DrawingDocument,
  type IconName,
  type ProviderName,
  type StickyColor,
  type StudioFlowNode,
} from "@/lib/canvas-model";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { Textarea } from "@/components/ui/textarea";
import { SearchField } from "@/components/shared/search-field";
import { CandidateDialog, CompileDialog, type CandidateOption } from "@/features/workflows/components/workflow-dialogs";
import { DrawingCanvasDialog } from "@/features/workflows/components/drawing-canvas-dialog";
import { CanvasNodeStatus, NodeActionsContext, icons, httpUrl, nodeTypes, storedAssetOutput, type NodeActions } from "@/features/workflows/components/workflow-node";
import { frameflowApi, type ArtifactListItem, type CanvasRunRecord, type ExperimentRun, type UploadedArtifact } from "@/lib/api";

const BACKUP_STORAGE_PREFIX = "frameflow.canvas.backup";
const EDGE_TYPE = "adaptive";
const SMOOTH_STEP_ROUTING_GAP = 40;

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
    },
  } : node);
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
  const migratedNodes = graph.nodes.filter((node) => node.data.key !== "video.frame_extract").map((node) => {
    const completedUploadArtifactId = node.data.key === "asset.upload" ? node.data.outputArtifactIds?.[0] : undefined;
    const legacyTextNote = node.data.key === "utility.text";
    const migratedKey = completedUploadArtifactId ? "asset.select" : legacyTextNote ? "utility.sticky" : node.data.key;
    const template = nodeTemplates.find((item) => item.data.key === migratedKey);
    if (!template) return node;
    return {
      ...node,
      data: {
        ...node.data,
        key: migratedKey,
        label: completedUploadArtifactId || legacyTextNote ? template.data.label : node.data.key === "asset.upload" ? "Upload" : node.data.label,
        description: completedUploadArtifactId || legacyTextNote ? template.data.description : node.data.description,
        icon: completedUploadArtifactId || legacyTextNote ? template.data.icon : node.data.icon,
        kind: template.data.kind,
        inputTypes: template.data.inputTypes,
        requiredInputTypes: template.data.requiredInputTypes,
        multiInputTypes: template.data.multiInputTypes,
        inputsRequired: template.data.inputsRequired,
        outputType: ["asset.upload", "asset.select"].includes(migratedKey) ? node.data.outputType ?? template.data.outputType : template.data.outputType,
        provider: node.data.kind === "generate" ? node.data.provider ?? providerFromModel(node.data.model ?? template.data.model) : node.data.provider,
        model: template.data.model?.startsWith("local.") || node.data.key === "video.translate" ? template.data.model : node.data.model ?? template.data.model,
        resolution: node.data.resolution ?? template.data.resolution,
        aspectRatio: node.data.aspectRatio ?? template.data.aspectRatio,
        batchSize: node.data.batchSize ?? template.data.batchSize,
        executable: template.data.executable,
        transition: node.data.transition ?? template.data.transition,
        targetDurationSeconds: node.data.targetDurationSeconds ?? template.data.targetDurationSeconds,
        sourceLanguage: node.data.sourceLanguage ?? template.data.sourceLanguage,
        targetLanguage: node.data.targetLanguage ?? template.data.targetLanguage,
        voiceName: node.data.voiceName ?? template.data.voiceName,
        stickyColor: node.data.stickyColor ?? template.data.stickyColor,
        drawing: node.data.drawing ?? template.data.drawing,
        configText: completedUploadArtifactId ?? (template.data.kind === "generate" ? undefined : node.data.configText ?? template.data.configText),
        output: legacyTextNote || node.data.output?.url?.startsWith("blob:") ? undefined : node.data.output,
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

function reconcileExperimentState(nodes: StudioFlowNode[], edges: Edge[], experiments: ExperimentRun[]): { nodes: StudioFlowNode[]; changed: boolean } {
  const latestByNode = new Map<string, ExperimentRun>();
  for (const experiment of experiments) {
    if (!latestByNode.has(experiment.node_id)) latestByNode.set(experiment.node_id, experiment);
  }
  let changed = false;
  const reconciled = nodes.map((node) => {
    const experiment = latestByNode.get(node.id);
    if (!experiment || node.data.executable === false) return node;
    const deliberatelyStale = node.data.status === "STALE" && node.data.lastExperimentId === experiment.id;
    if (deliberatelyStale && node.data.output && node.data.outputArtifactIds?.length) return node;
    const status = experiment.status as NodeStatus;
    const output = experiment.status === "SUCCEEDED" ? experiment.output : undefined;
    const outputArtifactIds = experiment.status === "SUCCEEDED" ? experiment.output_artifact_ids : undefined;
    const alreadyCurrent = node.data.lastExperimentId === experiment.id
      && node.data.status === status
      && JSON.stringify(node.data.outputArtifactIds ?? []) === JSON.stringify(outputArtifactIds ?? [])
      && JSON.stringify(node.data.output ?? {}) === JSON.stringify(output ?? {});
    if (alreadyCurrent) return node;
    changed = true;
    const logMarker = `Experiment ${experiment.id}`;
    const logs = node.data.logs ?? [];
    const recoveryLog = experiment.status === "SUCCEEDED"
      ? `${new Date(experiment.created_at).toLocaleTimeString("ko-KR")} · ${logMarker} restored · succeeded`
      : experiment.status === "FAILED"
        ? `${new Date(experiment.created_at).toLocaleTimeString("ko-KR")} · ${logMarker} restored · ${experiment.error ?? "failed"}`
        : `${new Date(experiment.created_at).toLocaleTimeString("ko-KR")} · ${logMarker} restored · ${experiment.status}`;
    return {
      ...node,
      data: {
        ...node.data,
        status: deliberatelyStale ? "STALE" as NodeStatus : status,
        preview: output?.title,
        output,
        outputArtifactIds,
        duration: experiment.duration_ms ? `${experiment.duration_ms}ms` : node.data.duration,
        lastRunAt: experiment.created_at,
        lastExperimentId: experiment.id,
        lastRequestHash: experiment.request_hash,
        executionMode: experiment.execution_mode,
        lastCostUsd: experiment.cost_usd,
        logs: logs.some((entry) => entry.includes(logMarker)) ? logs : [...logs, recoveryLog],
      },
    };
  });
  return { nodes: refreshReadyStatuses(reconciled, edges), changed };
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

export function GenerationCanvas({ canvasId, onBack }: { canvasId: string; onBack: () => void }) {
  return <ReactFlowProvider><EditableCanvas canvasId={canvasId} onBack={onBack} /></ReactFlowProvider>;
}

function EditableCanvas({ canvasId, onBack }: { canvasId: string; onBack: () => void }) {
  const [nodes, setNodes, applyNodeChanges] = useNodesState<StudioFlowNode>([]);
  const [edges, setEdges] = useEdgesState<Edge>([]);
  const [compileOpen, setCompileOpen] = useState(false);
  const [candidateOpen, setCandidateOpen] = useState(false);
  const [drawingNodeId, setDrawingNodeId] = useState<string | null>(null);
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
    let active = true;
    const backupKey = `${BACKUP_STORAGE_PREFIX}.${canvasId}`;
    Promise.all([
      frameflowApi.getCanvas(canvasId),
      frameflowApi.listExperiments(canvasId, undefined, 100).catch(() => []),
    ]).then(([document, experiments]) => {
      if (!active) return;
      const migrated = migrateStoredGraph({ id: document.id, name: document.name, nodes: document.nodes as StudioFlowNode[], edges: document.edges as Edge[], activeRunId: document.active_run_id });
      const reconciled = reconcileExperimentState(migrated.nodes, migrated.edges, experiments);
      setNodes(reconciled.nodes);
      setEdges(migrated.edges);
      setCanvasName(document.name);
      setActiveCanvasRunId(document.active_run_id ?? null);
      loadedRef.current = true;
      if (reconciled.changed || migrated.nodes.length !== document.nodes.length || migrated.edges.length !== document.edges.length) setSaveState("Unsaved");
    }).catch(() => {
      try {
        const stored = window.localStorage.getItem(backupKey);
        if (stored) {
          const graph = JSON.parse(stored) as GraphSnapshot;
          if (Array.isArray(graph.nodes) && Array.isArray(graph.edges)) {
            const migrated = migrateStoredGraph(graph);
            setNodes(migrated.nodes);
            setEdges(migrated.edges);
            if (migrated.name) setCanvasName(migrated.name);
            if (migrated.activeRunId) setActiveCanvasRunId(migrated.activeRunId);
          }
        }
      } catch {
        window.localStorage.removeItem(backupKey);
      }
      loadedRef.current = true;
    });
    return () => { active = false; };
  }, [canvasId, setEdges, setNodes]);

  useEffect(() => {
    if (!loadedRef.current || !nodes.some((node) => node.data.executable !== false && node.data.status === "RUNNING")) return;
    let active = true;
    const refreshRunningExperiments = () => {
      void frameflowApi.listExperiments(canvasId, undefined, 100).then((experiments) => {
        if (!active) return;
        setNodes((current) => {
          const reconciled = reconcileExperimentState(current, edgesRef.current, experiments);
          if (reconciled.changed) setSaveState("Unsaved");
          return reconciled.nodes;
        });
      }).catch(() => undefined);
    };
    const timer = window.setInterval(refreshRunningExperiments, 3000);
    refreshRunningExperiments();
    return () => { active = false; window.clearInterval(timer); };
  }, [canvasId, nodes, setNodes]);

  useEffect(() => {
    let active = true;
    frameflowApi.listAllArtifacts().then((items) => { if (active) setAssetOptions(items); }).catch(() => undefined);
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (!assetOptions.length) return;
    const byId = new Map(assetOptions.map((asset) => [asset.id, asset]));
    const needsHydration = nodes.some((node) => {
      const asset = node.data.key === "asset.select" ? byId.get(node.data.configText ?? "") : undefined;
      return Boolean(asset && (node.data.output?.url !== asset.url || node.data.output?.mimeType !== asset.content_type));
    });
    if (!needsHydration) return;
    setNodes((current) => current.map((node) => {
      const asset = node.data.key === "asset.select" ? byId.get(node.data.configText ?? "") : undefined;
      if (!asset) return node;
      const { outputType, output } = storedAssetOutput(asset);
      return { ...node, data: { ...node.data, outputType, output, preview: asset.filename, outputArtifactIds: [asset.id] } };
    }));
  }, [assetOptions, nodes, setNodes]);

  useEffect(() => {
    if (!loadedRef.current || saveState === "Saved") return;
    const timer = window.setTimeout(() => {
      setSaveState("Saving");
      const backup = { ...cloneGraph(nodes, edges), id: canvasId, name: canvasName, activeRunId: activeCanvasRunId ?? undefined };
      window.localStorage.setItem(`${BACKUP_STORAGE_PREFIX}.${canvasId}`, JSON.stringify(backup));
      frameflowApi.saveCanvas(canvasId, { name: canvasName, nodes: backup.nodes, edges: backup.edges, active_run_id: activeCanvasRunId ?? undefined })
        .then(() => setSaveState("Saved"))
        .catch((saveError) => { setSaveState("Unsaved"); notify(saveError instanceof Error ? saveError.message : "Canvas save failed", "error"); });
    }, 350);
    return () => window.clearTimeout(timer);
  }, [activeCanvasRunId, canvasId, canvasName, edges, nodes, notify, saveState]);

  const markUnsaved = useCallback(() => setSaveState("Unsaved"), []);

  const saveNow = useCallback(async () => {
    setSaveState("Saving");
    const backup = { ...cloneGraph(nodesRef.current, edgesRef.current), id: canvasId, name: canvasName, activeRunId: activeCanvasRunId ?? undefined };
    window.localStorage.setItem(`${BACKUP_STORAGE_PREFIX}.${canvasId}`, JSON.stringify(backup));
    try {
      await frameflowApi.saveCanvas(canvasId, { name: canvasName, nodes: backup.nodes, edges: backup.edges, active_run_id: activeCanvasRunId ?? undefined });
      setSaveState("Saved");
      return true;
    } catch (saveError) {
      setSaveState("Unsaved");
      notify(saveError instanceof Error ? saveError.message : "Canvas save failed", "error");
      return false;
    }
  }, [activeCanvasRunId, canvasId, canvasName, notify]);

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
    if (["utility.sticky", "utility.drawing"].includes(node.data.key)) setInspectorOpen(false);
    setPickerOpen(false);
    setPickerQuery("");
    setPickerInsertPosition(null);
    markUnsaved();
    notify(`${node.data.label} 노드를 추가했습니다.`, "success");
  }, [markUnsaved, notify, pickerInsertPosition, pushHistory, screenToFlowPosition, selectNode, setInspectorOpen, setNodes]);

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
      data: {
        ...source.data,
        label: `${source.data.label} copy`,
        status: source.data.requiredInputTypes?.length || (source.data.inputTypes?.length && source.data.inputsRequired !== false) ? "BLOCKED" : "READY",
        configText: source.data.key === "asset.upload" ? undefined : source.data.configText,
        preview: undefined,
        output: undefined,
        outputArtifactIds: undefined,
        attemptCount: 0,
        logs: [],
      },
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
    const executionFields = new Set(["provider", "model", "resolution", "aspectRatio", "batchSize", "transition", "targetDurationSeconds", "sourceLanguage", "targetLanguage", "voiceName"]);
    const invalidatesOutput = Object.keys(dataPatch).some((key) => executionFields.has(key));
    setNodes((current) => {
      const updated = current.map((node) => node.id === selectedNodeId ? {
        ...node,
        data: {
          ...node.data,
          ...dataPatch,
          ...(invalidatesOutput && node.data.status === "SUCCEEDED" ? { status: "STALE" as NodeStatus } : {}),
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
          const immediateSource = ["prompt.input", "asset.select", "utility.sticky"].includes(node.data.key);
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

  const updateStickyColor = useCallback((nodeId: string, stickyColor: StickyColor) => {
    setNodes((current) => current.map((node) => node.id === nodeId ? { ...node, data: { ...node.data, stickyColor } } : node));
    markUnsaved();
  }, [markUnsaved, setNodes]);

  const saveDrawing = useCallback(async (nodeId: string, drawing: DrawingDocument, image: Blob) => {
    const filename = `canvas-drawing-${Date.now()}.png`;
    setNodes((current) => current.map((node) => node.id === nodeId ? {
      ...node,
      data: { ...node.data, status: "RUNNING" as NodeStatus, preview: "Saving drawing…" },
    } : node));
    try {
      const artifact = await frameflowApi.uploadArtifact(new File([image], filename, { type: "image/png" }));
      const output = uploadedArtifactOutput(filename, artifact);
      setNodes((current) => {
        const invalidated = invalidateDescendants(current, edgesRef.current, nodeId);
        const updated = invalidated.map((node) => node.id === nodeId ? {
          ...node,
          data: {
            ...node.data,
            drawing,
            status: "SUCCEEDED" as NodeStatus,
            preview: filename,
            output,
            outputType: "Image" as PortType,
            outputArtifactIds: [artifact.artifact_id],
          },
        } : node);
        return refreshReadyStatuses(updated, edgesRef.current);
      });
      setAssetOptions((current) => [{
        id: artifact.artifact_id,
        created_at: new Date().toISOString(),
        type: artifact.type,
        content_type: artifact.content_type,
        size_bytes: artifact.size_bytes,
        filename,
        source: "canvas_drawing",
        duration_ms: 0,
        url: artifact.url,
      }, ...current.filter((item) => item.id !== artifact.artifact_id)]);
      markUnsaved();
      notify("캔버스 그림을 Image Artifact로 저장했습니다.", "success");
    } catch (saveError) {
      setNodes((current) => current.map((node) => node.id === nodeId ? {
        ...node,
        data: { ...node.data, status: node.data.output ? "SUCCEEDED" as NodeStatus : "FAILED" as NodeStatus, preview: node.data.output?.title },
      } : node));
      const message = saveError instanceof Error ? saveError.message : "캔버스 그림 저장에 실패했습니다.";
      notify(message, "error");
      throw new Error(message);
    }
  }, [markUnsaved, notify, setNodes]);

  const uploadDrawingSource = useCallback(async (file: File) => {
    const artifact = await frameflowApi.uploadArtifact(file);
    setAssetOptions((current) => [{
      id: artifact.artifact_id,
      created_at: new Date().toISOString(),
      type: artifact.type,
      content_type: artifact.content_type,
      size_bytes: artifact.size_bytes,
      filename: file.name || artifact.filename,
      source: "canvas_drawing_source",
      duration_ms: 0,
      url: artifact.url,
    }, ...current.filter((item) => item.id !== artifact.artifact_id)]);
    return artifact.url;
  }, []);

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
            key: "asset.select",
            label: "Assets",
            description: "저장된 이미지·비디오를 Popover에서 선택",
            icon: "assets" as IconName,
            status: "SUCCEEDED" as NodeStatus,
            configText: artifact.artifact_id,
            preview: file.name || artifact.filename,
            output,
            outputType: artifact.type as PortType,
            outputArtifactIds: [artifact.artifact_id],
          },
        } : node);
        return refreshReadyStatuses(updated, edgesRef.current);
      });
      markUnsaved();
      setAssetOptions((current) => [{ id: artifact.artifact_id, created_at: new Date().toISOString(), type: artifact.type, content_type: artifact.content_type, size_bytes: artifact.size_bytes, filename: file.name, source: "canvas_upload", duration_ms: 0, url: artifact.url }, ...current.filter((item) => item.id !== artifact.artifact_id)]);
      notify(`${file.name} 파일을 Asset으로 저장했습니다.`, "success");
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
            key: "asset.select",
            label: "Assets",
            description: "저장된 이미지·비디오를 Popover에서 선택",
            icon: "assets" as IconName,
            status: "SUCCEEDED" as NodeStatus,
            configText: artifact.artifact_id,
            preview: artifact.filename,
            output,
            outputType: artifact.type as PortType,
            outputArtifactIds: [artifact.artifact_id],
          },
        } : node);
        return refreshReadyStatuses(updated, edgesRef.current);
      });
      markUnsaved();
      setAssetOptions((current) => [{ id: artifact.artifact_id, created_at: new Date().toISOString(), type: artifact.type, content_type: artifact.content_type, size_bytes: artifact.size_bytes, filename: artifact.filename, source: "canvas_url_import", duration_ms: 0, url: artifact.url }, ...current.filter((item) => item.id !== artifact.artifact_id)]);
      notify(`${artifact.filename} 영상을 Asset으로 저장했습니다.`, "success");
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
        const { outputType, output } = storedAssetOutput(artifact);
        return { ...node, data: { ...node.data, status: "SUCCEEDED" as NodeStatus, configText: artifact.id, preview: artifact.filename, outputType, outputArtifactIds: [artifact.id], output } };
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
      if (drawingNodeId) return;
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
  }, [drawingNodeId, insertClipboardImage, insertPastedVideoUrl]);

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
    const directInputEdges = edgesRef.current.filter((edge) => edge.target === nodeId);
    const inputSourceIds = directInputEdges.flatMap((edge) => {
      const source = nodesRef.current.find((candidate) => candidate.id === edge.source);
      if (source?.data.key !== "prompt.input") return [edge.source];
      const promptInputIds = edgesRef.current.filter((candidate) => candidate.target === source.id).map((candidate) => candidate.source);
      return [edge.source, ...promptInputIds];
    });
    const inputSnapshots = [...new Set(inputSourceIds)].map((sourceId) => {
      const source = nodesRef.current.find((candidate) => candidate.id === sourceId);
      return {
        node_id: source?.id ?? sourceId,
        node_key: source?.data.key ?? "unknown",
        type: source?.data.outputType ?? "Any",
        label: source?.data.label ?? sourceId,
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
        canvas_id: canvasId,
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
  }, [canvasId, completeExperimentNode, markUnsaved, notify, selectedNodeId, setNodes]);

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
    setNodes((current) => current.map((node) => node.data.executable === false ? node : { ...node, data: { ...node.data, status: "QUEUED" as NodeStatus } }));
    try {
      const run = await frameflowApi.createCanvasRun({
        canvas_id: canvasId,
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
  }, [applyCanvasRunUpdate, canvasId, canvasName, notify, setNodes, subscribeCanvasRun]);

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
    frameflowApi.listExperiments(canvasId, selectedNodeId)
      .then((items) => { if (active) { setExperimentHistory(items); setExperimentHistoryNodeId(selectedNodeId); setExperimentHistoryError(null); } })
      .catch((error) => { if (active) { setExperimentHistoryNodeId(selectedNodeId); setExperimentHistoryError(error instanceof Error ? error.message : "Experiment history failed"); } });
    return () => { active = false; };
  }, [canvasId, selectedNode?.data.executable, selectedNode?.data.key, selectedNodeId]);
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
  const drawingNode = drawingNodeId ? nodes.find((node) => node.id === drawingNodeId && node.data.key === "utility.drawing") : undefined;
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
  const showInspector = Boolean(inspectorOpen && selectedNode && !["utility.sticky", "utility.drawing"].includes(selectedNode.data.key));
  const nodeActions = useMemo<NodeActions>(() => ({
    runStep: (nodeId) => void runStep(nodeId),
    updateConfig: updateNodeConfig,
    updateStickyColor,
    openDrawingEditor: setDrawingNodeId,
    getPromptImages: (nodeId) => edges
      .filter((edge) => edge.target === nodeId)
      .map((edge) => nodes.find((node) => node.id === edge.source))
      .filter((node): node is StudioFlowNode => Boolean(node?.data.outputType === "Image"))
      .map((node) => ({ id: node.id, title: node.data.output?.title ?? node.data.label, url: node.data.output?.url, outdated: node.data.status !== "SUCCEEDED" })),
    uploadAsset: uploadNodeAsset,
    importAssetUrl: importNodeAssetUrl,
    selectAsset: selectStoredAsset,
    assetOptions,
  }), [assetOptions, edges, importNodeAssetUrl, nodes, runStep, selectStoredAsset, updateNodeConfig, updateStickyColor, uploadNodeAsset]);

  return (
    <div className={`canvas-shell ${paletteOpen ? "" : "palette-hidden"} ${showInspector ? "with-inspector" : ""}`}>
      <div className="canvas-toolbar">
        <div className="workflow-switcher canvas-name-field"><span className="workflow-glyph"><Workflow size={16} /></span><span><small>Canvas</small><input value={canvasName} onChange={(event) => { setCanvasName(event.target.value); markUnsaved(); }} aria-label="Canvas name" /></span></div>
        <Button className="new-canvas-button" variant="secondary" type="button" onClick={() => { void saveNow().then((saved) => { if (saved) onBack(); }); }} disabled={graphRunning || saveState === "Saving"}><ArrowLeft size={15} /> Canvases</Button>
        <span className="canvas-divider" />
        <button className="tool-icon" type="button" onClick={undo} disabled={!history.length} aria-label="Undo"><Undo2 size={16} /></button>
        <button className="tool-icon" type="button" onClick={redo} disabled={!future.length} aria-label="Redo"><Redo2 size={16} /></button>
        <span className="canvas-divider" />
        <button className={`saved-indicator save-${saveState.toLowerCase()}`} type="button" onClick={() => void saveNow()} disabled={saveState === "Saving"}><Save size={13} /> {saveState}</button>
        <button className="tool-icon reset-canvas" type="button" onClick={clearCanvas} disabled={graphRunning || !nodes.length} aria-label="Clear canvas"><Trash2 size={15} /></button>
        <div className="canvas-toolbar-spacer" />
        <Button variant="secondary" className="canvas-validate-button" type="button" onClick={validateAndOpen}><CircleGauge size={15} /> Validate</Button>
        <div className="cost-estimate"><span><CircleDollarSign size={13} /> Est. ${cost.toFixed(2)}</span><small>{nodes.length} steps · {edges.length} connections</small></div>
        {graphRunning && <Button variant="secondary" className="run-stop" type="button" onClick={stopGraph}><CircleStop size={15} /> Stop</Button>}
        <Button className="run-button" type="button" onClick={validateAndOpen} disabled={graphRunning}>
          {graphRunning ? <><RefreshCw className="spin" size={15} /> Running {graphProgress}%</> : <><Play size={14} fill="currentColor" /> Run workflow</>}
        </Button>
      </div>

      {paletteOpen && <aside className="node-palette">
        <div className="palette-title"><div><span className="subtle-label">Node library</span><strong>Add a step</strong></div><span className="node-count">{nodeTemplates.filter((item) => item.visible !== false).length}</span></div>
        <SearchField className="palette-search" icon={<Sparkles size={14} />} value={paletteQuery} onChange={(event) => setPaletteQuery(event.target.value)} placeholder="Find node…" />
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
          onNodeClick={(_, node) => { selectNode(node.id); if (["utility.sticky", "utility.drawing"].includes(node.data.key)) setInspectorOpen(false); }}
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
          <Controls position="bottom-right" showInteractive={false} />
          <MiniMap position="bottom-right" pannable zoomable nodeColor={(node) => node.id === selectedNodeId ? "#675cf6" : node.data.status === "SUCCEEDED" ? "#79b9a0" : "#d3d4ce"} maskColor="rgba(246,246,243,.7)" />
          <div className="canvas-legend"><span><i className="port-format" /> Format</span><span><i className="port-media" /> Media</span><span><i className="port-data" /> Data</span><span>Double-click: Run step</span></div>
        </ReactFlow></NodeActionsContext.Provider>
        {!nodes.length && <div className="canvas-empty-state"><span className="empty-spark"><Sparkles size={22} /></span><h2>Start with a blank canvas</h2><p>저장된 실제 Asset과 Prompt 노드를 추가해 Workflow를 구성하세요.</p><div><Button type="button" onClick={() => setPickerOpen(true)}><Plus size={15} /> Add first step</Button></div></div>}
      </div>

      {showInspector && selectedNode && (
        <aside className="node-inspector">
          <div className="inspector-heading"><div><span className="subtle-label">Node inspector</span><strong>{selectedNode.data.label}</strong></div><Button variant="ghost" size="icon-sm" className="size-[25px] min-h-[25px]" type="button" onClick={() => setInspectorOpen(false)} aria-label="Close node inspector"><PanelRightClose size={16} /></Button></div>
          <div className="inspector-status"><CanvasNodeStatus data={selectedNode.data} /><span>{selectedNode.data.key}</span></div>
          <div className="inspector-tabs"><span className="active">Settings</span></div>
          <div className="inspector-content">
            {selectedNode.data.executable !== false && <Button className="step-run-button" type="button" onClick={() => void runStep(selectedNode.id)} disabled={selectedNode.data.status === "RUNNING" || graphRunning || !!selectedInputError}>
              {selectedNode.data.status === "RUNNING" ? <><RefreshCw className="spin" size={15} /> Running step…</> : <><Play size={14} fill="currentColor" /> Run this step</>}
            </Button>}
            <p className={`step-run-help ${selectedInputError ? "has-error" : ""}`}>{selectedNode.data.executable === false ? "입력 또는 Canvas 정리용 노드입니다." : selectedInputError ?? "이 Step만 실행합니다. 연결된 입력을 사용합니다."}</p>
            {selectedNode.data.kind === "generate" && <div className="generator-settings">
              <div className={`connected-prompt-preview ${selectedPromptText ? "connected" : "missing"}`}><span>Connected prompt</span><p>{selectedPromptText || "Prompt 노드를 연결하고 내용을 입력하세요."}</p></div>
              <div className="generator-setting-grid provider-model-selectors">
                <label><span>Provider</span><NativeSelect value={selectedProvider} onChange={(event) => { const provider = event.target.value as ProviderName; const model = modelOptionsForNode(selectedNode.data.key, provider)[0]?.value; updateSelectedData({ provider, model }); }}>{providerOptionsForNode(selectedNode.data.key).map((option) => <option value={option.value} key={option.value}>{option.label}</option>)}</NativeSelect></label>
                <label><span>Model</span><NativeSelect value={selectedNode.data.model ?? selectedModelOptions[0]?.value ?? ""} onChange={(event) => updateSelectedData({ model: event.target.value })}>{selectedModelOptions.map((option) => <option value={option.value} key={option.value}>{option.label}</option>)}</NativeSelect></label>
              </div>
              {selectedNode.data.resolution && <div className="generator-setting-grid">
                <label><span>Resolution</span><NativeSelect value={selectedNode.data.resolution ?? "1080p"} onChange={(event) => updateSelectedData({ resolution: event.target.value })}><option>1080p</option><option>2K</option><option>4K</option><option>24kHz</option></NativeSelect></label>
                <label><span>Aspect ratio</span><NativeSelect value={selectedNode.data.aspectRatio ?? "9:16"} onChange={(event) => updateSelectedData({ aspectRatio: event.target.value })}><option>9:16</option><option>1:1</option><option>16:9</option><option>Audio</option></NativeSelect></label>
              </div>}
              {selectedNode.data.batchSize && <div className="batch-setting single-output-setting"><span><small>Output count</small><strong>Canvas Step은 단일 결과를 출력합니다.</strong></span><b>1</b></div>}
            </div>}
            {selectedNode.data.key === "video.edit" && <div className="video-editor-settings">
              <div className={`editor-input-count ${selectedVideoInputCount ? "connected" : "missing"}`}><span>Connected videos</span><strong>{selectedVideoInputCount}</strong><small>{selectedVideoInputCount ? "여러 입력은 연결 순서대로 편집됩니다." : "Video 출력들을 왼쪽 입력 포트에 연결하세요."}</small></div>
              <label className="field-label"><span>Transition</span><NativeSelect value={selectedNode.data.transition ?? "hard_cut"} onChange={(event) => updateSelectedData({ transition: event.target.value })}><option value="hard_cut">Hard cut</option><option value="crossfade">Crossfade</option><option value="dip_to_black">Dip to black</option></NativeSelect></label>
              <div className="generator-setting-grid">
                <label><span>Output ratio</span><NativeSelect value={selectedNode.data.aspectRatio ?? "9:16"} onChange={(event) => updateSelectedData({ aspectRatio: event.target.value })}><option>9:16</option><option>1:1</option><option>16:9</option></NativeSelect></label>
                <label><span>Target length</span><NativeSelect value={String(selectedNode.data.targetDurationSeconds ?? 30)} onChange={(event) => updateSelectedData({ targetDurationSeconds: Number(event.target.value) })}><option value="15">15s</option><option value="30">30s</option><option value="45">45s</option><option value="60">60s</option></NativeSelect></label>
              </div>
            </div>}
            {selectedNode.data.key === "video.translate" && <div className="video-editor-settings">
              <div className="editor-input-count connected"><span>Live pipeline</span><strong>3</strong><small>Chirp 3 STT → Gemini translation → Gemini TTS</small></div>
              <div className="generator-setting-grid">
                <label><span>Source language</span><NativeSelect value={selectedNode.data.sourceLanguage ?? "auto"} onChange={(event) => updateSelectedData({ sourceLanguage: event.target.value })}><option value="auto">Auto detect</option><option value="ko-KR">Korean</option><option value="en-US">English</option><option value="ja-JP">Japanese</option><option value="zh-CN">Chinese</option><option value="es-ES">Spanish</option></NativeSelect></label>
                <label><span>Target language</span><NativeSelect value={selectedNode.data.targetLanguage ?? "ko-KR"} onChange={(event) => updateSelectedData({ targetLanguage: event.target.value })}><option value="ko-KR">Korean</option><option value="en-US">English</option><option value="ja-JP">Japanese</option><option value="zh-CN">Chinese</option><option value="es-ES">Spanish</option></NativeSelect></label>
              </div>
              <label className="field-label"><span>Gemini voice</span><NativeSelect value={selectedNode.data.voiceName ?? "Kore"} onChange={(event) => updateSelectedData({ voiceName: event.target.value })}><option value="Kore">Kore</option><option value="Aoede">Aoede</option><option value="Charon">Charon</option><option value="Puck">Puck</option></NativeSelect><small>Google Cloud ADC와 Speech-to-Text·Vertex AI 권한이 필요합니다.</small></label>
            </div>}
            <label className="field-label"><span>Node name</span><Input value={selectedNode.data.label} onChange={(event) => updateSelectedData({ label: event.target.value })} /></label>
            <label className="field-label"><span>Description</span><Textarea value={selectedNode.data.description} onChange={(event) => updateSelectedData({ description: event.target.value })} /></label>
            {selectedNode.data.model && selectedNode.data.kind !== "generate" && <label className="field-label"><span>Runtime engine</span><Input value={selectedNode.data.model} readOnly /><small>로컬 실행 엔진과 버전이 실행 이력에 고정됩니다.</small></label>}
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
          <div className="inspector-edit-actions"><Button variant="secondary" type="button" onClick={duplicateSelected}><Copy size={14} /> Duplicate</Button><Button variant="danger" type="button" onClick={deleteSelected}><Trash2 size={14} /> Delete</Button></div>
          {selectedNode.data.executable !== false && <div className="inspector-actions"><Button variant="secondary" size="sm" className="min-w-0 px-1 text-[length:var(--text-2xs)]" type="button" onClick={() => void runStep(selectedNode.id)} disabled={!!selectedInputError}><ListRestart size={13} /> Retry</Button><Button variant="secondary" size="sm" className="min-w-0 px-1 text-[length:var(--text-2xs)]" type="button" disabled={!!selectedInputError} onClick={() => { updateSelectedData({ status: selectedNode.data.requiredInputTypes?.length || (selectedNode.data.inputTypes?.length && selectedNode.data.inputsRequired !== false) ? "BLOCKED" : "READY" }); window.setTimeout(() => void runStep(selectedNode.id), 0); }}><RefreshCw size={13} /> Regenerate</Button><Button variant="secondary" size="sm" className="min-w-0 px-1 text-[length:var(--text-2xs)]" type="button" onClick={duplicateSelected}><GitFork size={13} /> Fork</Button></div>}
        </aside>
      )}

      {!inspectorOpen && selectedNode && !["utility.sticky", "utility.drawing"].includes(selectedNode.data.key) && <button className="open-inspector" type="button" onClick={() => setInspectorOpen(true)}><ChevronRight size={16} /></button>}

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
      {drawingNode && <DrawingCanvasDialog
        document={drawingNode.data.drawing ?? { version: 1, width: 1280, height: 720, images: [], strokes: [] }}
        nodeName={drawingNode.data.label}
        onAddImage={uploadDrawingSource}
        onClose={() => setDrawingNodeId(null)}
        onSave={(drawing, image) => saveDrawing(drawingNode.id, drawing, image)}
      />}
    </div>
  );
}
