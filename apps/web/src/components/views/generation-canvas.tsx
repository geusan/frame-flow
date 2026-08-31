"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
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
  Unlink2,
  Workflow,
  X,
} from "lucide-react";
import { useStudioStore } from "@/lib/store";
import type { NodeStatus, PortType } from "@/lib/types";
import {
  createNodeFromTemplate,
  canvasElementTemplates,
  graphCost,
  inputHandleId,
  nodeTemplates,
  refreshReadyStatuses,
  stepInputError,
  validateGraph,
  type CanvasOutput,
  type ConnectionCompatibilityValidator,
  type DrawingDocument,
  type IconName,
  type NodeTemplate,
  type ProviderName,
  type StickyColor,
  type StudioFlowNode,
} from "@/lib/canvas-model";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { VideoPlayer } from "@/components/ui/video-player";
import { SearchField } from "@/components/shared/search-field";
import { CharacterViewGallery } from "@/components/characters/character-view-gallery";
import { ReferenceResultDetail } from "@/components/views/reference-results-view";
import { CandidateDialog, CompileDialog, type CandidateOption } from "@/features/workflows/components/workflow-dialogs";
import { DrawingCanvasDialog } from "@/features/workflows/components/drawing-canvas-dialog";
import { WorkflowInputsPanel } from "@/features/workflows/components/workflow-inputs-panel";
import { latestNodeTemplates } from "@/features/nodes/contracts";
import { LEGACY_CONFIG_DATA_FIELDS, serializeCanvasDocument } from "@/features/nodes/canvas-document-adapter";
import { NodeInspectorEditor } from "@/features/nodes/node-inspector-editor";
import { nodeConnectionCompatible, targetPortContract } from "@/features/nodes/port-contracts";
import { CanvasNodeStatus, NodeActionsContext, icons, httpUrl, nodeTypes, storedAssetOutput, type CanvasSpaceHoldRequest, type NodeActions } from "@/features/workflows/components/workflow-node";
import { frameflowApi, type ArtifactListItem, type CanvasRunRecord, type CharacterRecord, type ExperimentRun, type ModelRecord, type NodeDefinitionRecord, type NodePortTypeRegistryRecord, type ProjectSkillRecord, type UploadedArtifact, type WorkflowDraftContract, type WorkflowInputDefinition } from "@/lib/api";
import { migrateLegacyGoogleTextModelAlias } from "@/lib/model-options";

const BACKUP_STORAGE_PREFIX = "frameflow.canvas.backup";
const EDGE_TYPE = "adaptive";
const SMOOTH_STEP_ROUTING_GAP = 40;
const SPACE_PAN_HOLD_DELAY_MS = 600;
const EMPTY_WORKFLOW_DRAFT: WorkflowDraftContract = { schema_version: "workflow.contract.draft.v1", inputs: [], bindings: [], outputs: [] };
const EMPTY_PORT_TYPE_REGISTRY: NodePortTypeRegistryRecord = { schema_version: "port-types.v1", types: [] };
function exposedConfigValue(node: StudioFlowNode, configKey: string, fallback: unknown): unknown {
  if (node.data.config && node.data.config[configKey] !== undefined) return node.data.config[configKey];
  if (configKey === "text") return node.data.configText ?? fallback;
  if (configKey === "artifact_id" || configKey === "character_id") return node.data.configText || node.data.outputArtifactIds?.[0] || fallback;
  if (configKey === "artifact_type") return node.data.outputType ?? fallback;
  const dataKey = LEGACY_CONFIG_DATA_FIELDS[configKey];
  return dataKey && node.data[dataKey] !== undefined ? node.data[dataKey] : fallback;
}

function uniqueWorkflowInputKey(configKey: string, inputs: WorkflowInputDefinition[]): string {
  const base = configKey.toLowerCase().replace(/[^a-z0-9_]/g, "_").replace(/^[^a-z]+/, "") || "input";
  if (!inputs.some((input) => input.key === base)) return base;
  let suffix = 2;
  while (inputs.some((input) => input.key === `${base}_${suffix}`)) suffix += 1;
  return `${base}_${suffix}`;
}

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

function TextOutputEditor({ output, edited, onSave }: { output: CanvasOutput; edited: boolean; onSave: (text: string) => void }) {
  const currentText = output.text ?? "";
  const [draft, setDraft] = useState(currentText);
  const dirty = draft !== currentText;

  return <div className="node-detail-result-editor">
    <Textarea
      value={draft}
      onChange={(event) => setDraft(event.currentTarget.value)}
      aria-label="Generated master prompt result"
      spellCheck={false}
    />
    <footer>
      <span>{dirty ? "저장하지 않은 수정 사항이 있습니다." : edited ? "수동으로 수정된 결과입니다." : "실행 결과를 직접 수정할 수 있습니다."}</span>
      <Button type="button" size="sm" onClick={() => onSave(draft)} disabled={!dirty || !draft.trim()}><Save size={13} /> Save result</Button>
    </footer>
  </div>;
}

function CharacterOutputGallery({ characterId, fallbackUrl, title }: { characterId?: string; fallbackUrl?: string; title: string }) {
  const [character, setCharacter] = useState<CharacterRecord | null>(null);
  const [loading, setLoading] = useState(Boolean(characterId));

  useEffect(() => {
    if (!characterId) return;
    let active = true;
    frameflowApi.listCharacters()
      .then((items) => { if (active) setCharacter(items.find((item) => item.id === characterId) ?? null); })
      .catch(() => undefined)
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [characterId]);

  if (character?.images.length) return <CharacterViewGallery character={character} />;

  return <div className="node-detail-character-fallback">
    {fallbackUrl && <div role="img" aria-label={title} style={{ backgroundImage: `url(${fallbackUrl})` }} />}
    {loading && <span><RefreshCw className="spin" size={15} /> Loading all character views…</span>}
    {!loading && <span>Character view manifest is unavailable.</span>}
  </div>;
}

function NodeDetailSurface({ node, open, onClose, onTextOutputSave, children }: { node: StudioFlowNode; open: boolean; onClose: () => void; onTextOutputSave: (text: string) => void; children: ReactNode }) {
  if (!open) return children;
  const output = node.data.output;
  const hasReferenceAnalysis = node.data.key === "reference.decompose" && Boolean(output?.text || node.data.outputArtifactIds?.[0]);
  const hasMedia = Boolean(output?.url && ["image", "video"].includes(output.kind));
  const hasMotionTrack = node.data.outputType === "MotionTrack" && Boolean(output);
  const hasText = !hasReferenceAnalysis && !hasMotionTrack && Boolean(output?.text && ["text", "json"].includes(output.kind));
  const hasOutput = hasReferenceAnalysis || hasMedia || hasMotionTrack || hasText;
  return <Dialog open onOpenChange={(nextOpen) => { if (!nextOpen) onClose(); }}>
    <DialogContent className={`node-detail-dialog ${hasOutput ? "has-output" : "settings-only"}${hasReferenceAnalysis ? " reference-output" : ""}`} overlayClassName="node-detail-backdrop">
      <DialogTitle className="sr-only">{node.data.label} node details</DialogTitle>
      <DialogDescription className="sr-only">Preview and edit the selected canvas node.</DialogDescription>
      {hasReferenceAnalysis && <section className="node-detail-reference-output">
        <ReferenceResultDetail
          artifactId={node.data.outputArtifactIds?.[0]}
          fallbackTitle={output?.title ?? node.data.label}
          fallbackText={output?.text}
          onBack={onClose}
        />
      </section>}
      {hasMedia && output && <section className={`node-detail-media ${node.data.outputType === "Character" ? "character-output" : ""}`}>
        <header><span><small>{node.data.outputType === "Character" ? "character output" : `${output.kind} output`}</small><strong title={output.title}>{output.title}</strong></span><b>{node.data.outputType === "Character" ? `${output.imageCount ?? ""} views`.trim() : node.data.outputType}</b></header>
        <div className={node.data.outputType === "Character" ? "node-detail-character-stage" : undefined}>
          {output.kind === "image" && node.data.outputType !== "Character" && <>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={output.url} alt={output.title} />
          </>}
          {output.kind === "image" && node.data.outputType === "Character" && <CharacterOutputGallery key={output.characterId ?? node.data.outputArtifactIds?.[0]} characterId={output.characterId ?? node.data.outputArtifactIds?.[0]} fallbackUrl={output.url} title={output.title} />}
          {output.kind === "video" && <VideoPlayer src={output.url ?? ""} mimeType={output.mimeType} title={output.title} />}
        </div>
      </section>}
      {hasText && output && <section className="node-detail-text-output">
        <header><span><small>{output.kind} output</small><strong title={output.title}>{output.title}</strong></span><b>{node.data.outputEdited ? "Edited" : node.data.outputType}</b></header>
        <div>
          {node.data.key === "skill.execute"
            ? <TextOutputEditor key={`${node.id}:${node.data.lastExperimentId ?? ""}:${node.data.outputEdited ? "edited" : "generated"}`} output={output} edited={Boolean(node.data.outputEdited)} onSave={onTextOutputSave} />
            : <pre>{output.text}</pre>}
        </div>
      </section>}
      {hasMotionTrack && output && <section className="node-detail-text-output">
        <header><span><small>motion track output</small><strong title={output.title}>{output.title}</strong></span><b>MotionTrack</b></header>
        <div className="node-detail-motion-track">
          <strong>{output.frameCount ?? 0} frames · {output.sampleFps ?? 0} fps</strong>
          <section>
            <span><b>{Math.round((output.poseCoverage ?? 0) * 100)}%</b><small>Pose</small></span>
            <span><b>{Math.round((output.faceCoverage ?? 0) * 100)}%</b><small>Face</small></span>
            <span><b>{Math.round((output.leftHandCoverage ?? 0) * 100)}%</b><small>L hand</small></span>
            <span><b>{Math.round((output.rightHandCoverage ?? 0) * 100)}%</b><small>R hand</small></span>
          </section>
          <p>전체 랜드마크 JSON은 MotionTrack Artifact에 보관됩니다.</p>
        </div>
      </section>}
      {children}
    </DialogContent>
  </Dialog>;
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

function promptOutputText(node: StudioFlowNode | undefined): string {
  if (!node) return "";
  if (node.data.output?.kind === "text" && node.data.output.text?.trim()) return node.data.output.text.trim();
  return node.data.configText?.trim() ?? "";
}

function propagateConnectedPrompts(nodes: StudioFlowNode[], edges: Edge[], sourceId?: string, force = false): StudioFlowNode[] {
  const byId = new Map(nodes.map((node) => [node.id, node]));
  return nodes.map((node) => {
    if (node.data.key !== "prompt.input") return node;
    const promptIndex = node.data.inputTypes?.indexOf("Prompt") ?? -1;
    if (promptIndex < 0) return node;
    const promptEdge = edges.find((edge) => edge.target === node.id && edge.targetHandle === inputHandleId("Prompt", promptIndex));
    if (!promptEdge || (sourceId && promptEdge.source !== sourceId)) return node;
    const upstreamText = promptOutputText(byId.get(promptEdge.source));
    if (!upstreamText || (!force && node.data.promptEdited) || node.data.configText === upstreamText) return node;
    return {
      ...node,
      data: {
        ...node.data,
        configText: upstreamText,
        status: "SUCCEEDED" as NodeStatus,
        promptEdited: false,
      },
    };
  });
}

function providerFromModel(model?: string): ProviderName {
  return model?.startsWith("openai.") ? "openai" : model?.startsWith("xai.") ? "xai" : model?.startsWith("fal.") ? "fal" : "google";
}

function migrateStoredGraph(graph: GraphSnapshot, templates: NodeTemplate[] = nodeTemplates): GraphSnapshot {
  const isLegacyMockGraph = graph.nodes.some((node) => node.id === "brief" && node.data.description.includes("로마 도로"))
    || graph.nodes.some((node) => node.id === "format" && node.data.label === "Contrarian History");
  if (isLegacyMockGraph) return { ...graph, nodes: [], edges: [], activeRunId: undefined };
  const migratedNodes = graph.nodes.filter((node) => node.data.key !== "video.frame_extract").map((node) => {
    const completedUploadArtifactId = node.data.key === "asset.upload" ? node.data.outputArtifactIds?.[0] : undefined;
    const legacyTextNote = node.data.key === "utility.text";
    const migratedKey = completedUploadArtifactId ? "asset.select" : legacyTextNote ? "utility.sticky" : node.data.key;
    const template = templates.find((item) => item.data.key === migratedKey);
    if (!template) return node;
    return {
      ...node,
      data: {
        ...node.data,
        key: migratedKey,
        label: completedUploadArtifactId || legacyTextNote ? template.data.label : node.data.key === "asset.upload" ? "Upload" : node.data.label,
        description: completedUploadArtifactId || legacyTextNote || ["character.generate", "lora.image.generate"].includes(node.data.key) ? template.data.description : node.data.description,
        icon: completedUploadArtifactId || legacyTextNote ? template.data.icon : node.data.icon,
        kind: template.data.kind,
        inputTypes: template.data.inputTypes,
        requiredInputTypes: template.data.requiredInputTypes,
        multiInputTypes: template.data.multiInputTypes,
        inputsRequired: template.data.inputsRequired,
        outputType: ["asset.upload", "asset.select"].includes(migratedKey) ? node.data.outputType ?? template.data.outputType : template.data.outputType,
        provider: node.data.kind === "generate" ? node.data.provider ?? providerFromModel(node.data.model ?? template.data.model) : node.data.provider,
        model: template.data.model?.startsWith("local.") || node.data.key === "video.translate" ? template.data.model : migrateLegacyGoogleTextModelAlias(node.data.model ?? template.data.model),
        resolution: node.data.resolution ?? template.data.resolution,
        aspectRatio: node.data.aspectRatio ?? template.data.aspectRatio,
        batchSize: node.data.batchSize ?? template.data.batchSize,
        characterName: node.data.characterName ?? template.data.characterName,
        shotCount: node.data.shotCount ?? template.data.shotCount,
        durationSeconds: node.data.durationSeconds ?? template.data.durationSeconds,
        loraUrl: node.data.loraUrl ?? template.data.loraUrl,
        loraScale: node.data.loraScale ?? template.data.loraScale,
        triggerWord: node.data.triggerWord ?? template.data.triggerWord,
        executable: template.data.executable,
        transition: node.data.transition ?? template.data.transition,
        targetDurationSeconds: node.data.targetDurationSeconds ?? template.data.targetDurationSeconds,
        sourceLanguage: node.data.sourceLanguage ?? template.data.sourceLanguage,
        separateMusic: node.data.separateMusic ?? template.data.separateMusic,
        sceneThreshold: node.data.sceneThreshold ?? template.data.sceneThreshold,
        targetLanguage: node.data.targetLanguage ?? template.data.targetLanguage,
        voiceName: node.data.voiceName ?? template.data.voiceName,
        captionX: node.data.captionX ?? template.data.captionX,
        captionY: node.data.captionY ?? template.data.captionY,
        captionAlign: node.data.captionAlign ?? template.data.captionAlign,
        captionFontSize: node.data.captionFontSize ?? template.data.captionFontSize,
        waitForInput: node.data.waitForInput ?? template.data.waitForInput,
        skillId: node.data.skillId ?? template.data.skillId,
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
  });
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
    if (node.data.outputEdited && node.data.output) return node;
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
        runProgress: experiment.status === "RUNNING" ? 5 : experiment.status === "SUCCEEDED" ? 100 : undefined,
        logs: logs.some((entry) => entry.includes(logMarker)) ? logs : [...logs, recoveryLog],
      },
    };
  });
  const propagated = propagateConnectedPrompts(reconciled, edges);
  const promptChanged = propagated.some((node, index) => node.data.configText !== reconciled[index]?.data.configText);
  return { nodes: refreshReadyStatuses(propagated, edges), changed: changed || promptChanged };
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

export function GenerationCanvas({ canvasId, nodeDetailId, onOpenNodeDetail, onCloseNodeDetail, onBack }: { canvasId: string; nodeDetailId?: string; onOpenNodeDetail: (nodeId: string) => void; onCloseNodeDetail: () => void; onBack: () => void }) {
  return <ReactFlowProvider><EditableCanvas canvasId={canvasId} nodeDetailId={nodeDetailId} onOpenNodeDetail={onOpenNodeDetail} onCloseNodeDetail={onCloseNodeDetail} onBack={onBack} /></ReactFlowProvider>;
}

function EditableCanvas({ canvasId, nodeDetailId, onOpenNodeDetail, onCloseNodeDetail, onBack }: { canvasId: string; nodeDetailId?: string; onOpenNodeDetail: (nodeId: string) => void; onCloseNodeDetail: () => void; onBack: () => void }) {
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
  const [spacePanActive, setSpacePanActive] = useState(false);
  const [canvasName, setCanvasName] = useState("Untitled canvas");
  const [workflowDefinitionId, setWorkflowDefinitionId] = useState<string | null>(null);
  const [baseVersionId, setBaseVersionId] = useState<string | null>(null);
  const [canvasRevision, setCanvasRevision] = useState(1);
  const [draftContract, setDraftContract] = useState<WorkflowDraftContract>(EMPTY_WORKFLOW_DRAFT);
  const [inputsPanelOpen, setInputsPanelOpen] = useState(false);
  const [publishing, setPublishing] = useState(false);
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
  const [characterOptions, setCharacterOptions] = useState<CharacterRecord[]>([]);
  const [projectSkills, setProjectSkills] = useState<ProjectSkillRecord[]>([]);
  const [nodeDefinitions, setNodeDefinitions] = useState<NodeDefinitionRecord[]>([]);
  const [portTypeRegistry, setPortTypeRegistry] = useState<NodePortTypeRegistryRecord>(EMPTY_PORT_TYPE_REGISTRY);
  const [models, setModels] = useState<ModelRecord[]>([]);
  const [registryTemplates, setRegistryTemplates] = useState<NodeTemplate[]>([]);
  const selectedNodeId = useStudioStore((state) => state.selectedNodeId);
  const selectNode = useStudioStore((state) => state.selectNode);
  const inspectorOpen = useStudioStore((state) => state.inspectorOpen);
  const setInspectorOpen = useStudioStore((state) => state.setInspectorOpen);
  const { getViewport, screenToFlowPosition, setViewport } = useReactFlow<StudioFlowNode, Edge>();
  const flowStageRef = useRef<HTMLDivElement>(null);
  const lastCanvasPointerRef = useRef<{ x: number; y: number } | null>(null);
  const loadedRef = useRef(false);
  const sequenceRef = useRef(1);
  const dragStartRef = useRef<GraphSnapshot | null>(null);
  const toastTimerRef = useRef<number | null>(null);
  const spaceHoldTimerRef = useRef<number | null>(null);
  const spaceHoldRef = useRef<(CanvasSpaceHoldRequest & { activated: boolean }) | null>(null);
  const cancelRunRef = useRef(false);
  const canvasRunEventsRef = useRef<EventSource | null>(null);
  const waitingInputNodeRef = useRef<string | null>(null);
  const previousNodeDetailIdRef = useRef(nodeDetailId);
  const nodesRef = useRef(nodes);
  const edgesRef = useRef(edges);

  useEffect(() => {
    nodesRef.current = nodes;
  }, [nodes]);

  useEffect(() => {
    edgesRef.current = edges;
  }, [edges]);

  useEffect(() => {
    const previousNodeDetailId = previousNodeDetailIdRef.current;
    previousNodeDetailIdRef.current = nodeDetailId;
    if (previousNodeDetailId && !nodeDetailId) setInspectorOpen(true);
  }, [nodeDetailId, setInspectorOpen]);

  const finishSpaceHold = useCallback((commitPending: boolean) => {
    if (spaceHoldTimerRef.current !== null) {
      window.clearTimeout(spaceHoldTimerRef.current);
      spaceHoldTimerRef.current = null;
    }
    const hold = spaceHoldRef.current;
    spaceHoldRef.current = null;
    if (commitPending && hold && !hold.activated && hold.isFocused()) hold.commit();
    setSpacePanActive(false);
  }, []);

  const beginSpaceHold = useCallback((request: CanvasSpaceHoldRequest) => {
    finishSpaceHold(false);
    spaceHoldRef.current = { ...request, activated: false };
    spaceHoldTimerRef.current = window.setTimeout(() => {
      spaceHoldTimerRef.current = null;
      const hold = spaceHoldRef.current;
      if (!hold) return;
      if (!hold.isFocused()) {
        spaceHoldRef.current = null;
        return;
      }
      hold.activated = true;
      hold.blur();
      setSpacePanActive(true);
    }, SPACE_PAN_HOLD_DELAY_MS);
  }, [finishSpaceHold]);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.code !== "Space" && spaceHoldRef.current) finishSpaceHold(true);
    };
    const handleKeyUp = (event: KeyboardEvent) => {
      if (event.code === "Space") finishSpaceHold(true);
    };
    const handleWindowBlur = () => finishSpaceHold(false);
    window.addEventListener("keydown", handleKeyDown, true);
    window.addEventListener("keyup", handleKeyUp, true);
    window.addEventListener("blur", handleWindowBlur);
    return () => {
      window.removeEventListener("keydown", handleKeyDown, true);
      window.removeEventListener("keyup", handleKeyUp, true);
      window.removeEventListener("blur", handleWindowBlur);
      if (spaceHoldTimerRef.current !== null) window.clearTimeout(spaceHoldTimerRef.current);
      spaceHoldTimerRef.current = null;
      spaceHoldRef.current = null;
    };
  }, [finishSpaceHold]);

  useEffect(() => {
    const stage = flowStageRef.current;
    if (!stage) return;
    let frameId: number | null = null;
    let pendingX = 0;
    let pendingY = 0;
    const flushPan = () => {
      frameId = null;
      const x = pendingX;
      const y = pendingY;
      pendingX = 0;
      pendingY = 0;
      const viewport = getViewport();
      void setViewport({ ...viewport, x: viewport.x + x, y: viewport.y + y });
    };
    const handleTrackpadScroll = (event: WheelEvent) => {
      // macOS reports a real trackpad pinch as ctrl+wheel. Leave that event to
      // React Flow's pinch zoom and consume every ordinary two-finger scroll as pan.
      if (event.ctrlKey) return;
      event.preventDefault();
      event.stopPropagation();
      const scale = event.deltaMode === WheelEvent.DOM_DELTA_LINE ? 20 : event.deltaMode === WheelEvent.DOM_DELTA_PAGE ? stage.clientHeight : 1;
      pendingX -= event.deltaX * scale;
      pendingY -= event.deltaY * scale;
      if (frameId === null) frameId = window.requestAnimationFrame(flushPan);
    };
    stage.addEventListener("wheel", handleTrackpadScroll, { capture: true, passive: false });
    return () => {
      stage.removeEventListener("wheel", handleTrackpadScroll, { capture: true });
      if (frameId !== null) window.cancelAnimationFrame(frameId);
    };
  }, [getViewport, setViewport]);

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
      frameflowApi.listNodeDefinitions().catch(() => []),
      frameflowApi.listNodePortTypes().catch(() => EMPTY_PORT_TYPE_REGISTRY),
      frameflowApi.listModels().catch(() => []),
    ]).then(([document, experiments, definitions, availablePortTypes, availableModels]) => {
      if (!active) return;
      const manifestTemplates = latestNodeTemplates(definitions);
      const templates = [...canvasElementTemplates, ...manifestTemplates];
      setNodeDefinitions(definitions);
      setPortTypeRegistry(availablePortTypes);
      setModels(availableModels);
      setRegistryTemplates(manifestTemplates);
      const migrated = migrateStoredGraph({ id: document.id, name: document.name, nodes: document.nodes as StudioFlowNode[], edges: document.edges as Edge[], activeRunId: document.active_run_id }, templates);
      const reconciled = reconcileExperimentState(migrated.nodes, migrated.edges, experiments);
      setNodes(reconciled.nodes);
      setEdges(migrated.edges);
      setCanvasName(document.name);
      setWorkflowDefinitionId(document.workflow_definition_id ?? null);
      setBaseVersionId(document.base_version_id ?? null);
      setCanvasRevision(document.revision ?? 1);
      setDraftContract(document.draft_contract ?? EMPTY_WORKFLOW_DRAFT);
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
    Promise.all([
      frameflowApi.listAllArtifacts(["Image", "Video", "FinalVideo", "Audio"]),
      frameflowApi.listCharacters(),
    ]).then(([assets, characters]) => {
      if (!active) return;
      setAssetOptions(assets);
      setCharacterOptions(characters);
    }).catch(() => undefined);
    return () => { active = false; };
  }, []);

  useEffect(() => {
    let active = true;
    frameflowApi.listSkills().then((items) => { if (active) setProjectSkills(items); }).catch(() => undefined);
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
    if (!characterOptions.length) return;
    const byId = new Map(characterOptions.map((character) => [character.id, character]));
    const needsHydration = nodes.some((node) => {
      const character = node.data.key === "character.select" ? byId.get(node.data.configText ?? "") : undefined;
      return Boolean(character && node.data.output?.url !== character.cover_url);
    });
    if (!needsHydration) return;
    setNodes((current) => current.map((node) => {
      const character = node.data.key === "character.select" ? byId.get(node.data.configText ?? "") : undefined;
      if (!character) return node;
      return { ...node, data: { ...node.data, status: "SUCCEEDED" as NodeStatus, outputType: "Character" as PortType, preview: character.name, outputArtifactIds: [character.id], output: { kind: "image", title: `${character.name} · ${character.image_count} views`, url: character.cover_url, mimeType: "image/png" } } };
    }));
  }, [characterOptions, nodes, setNodes]);

  useEffect(() => {
    if (!loadedRef.current || saveState === "Saved") return;
    const timer = window.setTimeout(() => {
      setSaveState("Saving");
      const backup = { ...cloneGraph(nodes, edges), id: canvasId, name: canvasName, activeRunId: activeCanvasRunId ?? undefined };
      window.localStorage.setItem(`${BACKUP_STORAGE_PREFIX}.${canvasId}`, JSON.stringify(backup));
      frameflowApi.saveCanvas(canvasId, { name: canvasName, document: serializeCanvasDocument(nodes, edges, nodeDefinitions), active_run_id: activeCanvasRunId ?? undefined, draft_contract: draftContract })
        .then((document) => { setCanvasRevision(document.revision); setSaveState("Saved"); })
        .catch((saveError) => { setSaveState("Unsaved"); notify(saveError instanceof Error ? saveError.message : "Canvas save failed", "error"); });
    }, 350);
    return () => window.clearTimeout(timer);
  }, [activeCanvasRunId, canvasId, canvasName, draftContract, edges, nodeDefinitions, nodes, notify, saveState]);

  const markUnsaved = useCallback(() => setSaveState("Unsaved"), []);

  const saveNow = useCallback(async () => {
    setSaveState("Saving");
    const backup = { ...cloneGraph(nodesRef.current, edgesRef.current), id: canvasId, name: canvasName, activeRunId: activeCanvasRunId ?? undefined };
    window.localStorage.setItem(`${BACKUP_STORAGE_PREFIX}.${canvasId}`, JSON.stringify(backup));
    try {
      const document = await frameflowApi.saveCanvas(canvasId, { name: canvasName, document: serializeCanvasDocument(nodesRef.current, edgesRef.current, nodeDefinitions), active_run_id: activeCanvasRunId ?? undefined, draft_contract: draftContract });
      setCanvasRevision(document.revision);
      setSaveState("Saved");
      return document;
    } catch (saveError) {
      setSaveState("Unsaved");
      notify(saveError instanceof Error ? saveError.message : "Canvas save failed", "error");
      return null;
    }
  }, [activeCanvasRunId, canvasId, canvasName, draftContract, nodeDefinitions, notify]);

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

  const disconnectInput = useCallback((nodeId: string, type: PortType, index: number) => {
    const target = nodesRef.current.find((node) => node.id === nodeId);
    if (!target) return;
    const handleId = inputHandleId(type, index);
    const isMatchingInput = (edge: Edge) => edge.target === nodeId
      && (edge.targetHandle === handleId || (!edge.targetHandle && target.data.inputTypes?.length === 1));
    if (!edgesRef.current.some(isMatchingInput)) return;
    pushHistory();
    const nextEdges = edgesRef.current.filter((edge) => !isMatchingInput(edge));
    setEdges(nextEdges);
    setNodes((current) => {
      const invalidated = invalidateDescendants(current, nextEdges, nodeId);
      const resetTarget = invalidated.map((node) => node.id === nodeId && node.data.executable !== false ? {
        ...node,
        data: {
          ...node.data,
          status: node.data.output || node.data.outputArtifactIds?.length ? "STALE" as NodeStatus : "READY" as NodeStatus,
        },
      } : node);
      return refreshReadyStatuses(resetTarget, nextEdges);
    });
    markUnsaved();
    notify(`${type} 입력 연결을 해제했습니다.`, "success");
  }, [markUnsaved, notify, pushHistory, setEdges, setNodes]);

  const registryConnectionCompatible = useCallback<ConnectionCompatibilityValidator>((connection, currentNodes) => (
    nodeConnectionCompatible(connection, currentNodes, nodeDefinitions, portTypeRegistry)
  ), [nodeDefinitions, portTypeRegistry]);

  const isValidConnection = useCallback((connection: Connection | Edge) => {
    if (!registryConnectionCompatible(connection, nodesRef.current)) return false;
    const targetPort = targetPortContract(connection, nodesRef.current, nodeDefinitions, portTypeRegistry);
    if (targetPort?.multiple) return true;
    const target = nodesRef.current.find((node) => node.id === connection.target);
    const targetType = target?.data.inputTypes?.find((type, index) => connection.targetHandle === inputHandleId(type, index));
    if (!targetPort && targetType && target?.data.multiInputTypes?.includes(targetType)) return true;
    return !edgesRef.current.some((edge) => edge.target === connection.target && edge.targetHandle === connection.targetHandle);
  }, [nodeDefinitions, portTypeRegistry, registryConnectionCompatible]);

  const onConnect = useCallback((connection: Connection) => {
    if (!isValidConnection(connection)) {
      notify("포트 타입이 다르거나 이미 연결된 입력입니다.", "error");
      return;
    }
    pushHistory();
    const next = addEdge({ ...connection, id: `edge-${Date.now()}`, type: EDGE_TYPE, style: { stroke: "#a8aaa3", strokeWidth: 1.35 } }, edgesRef.current);
    setEdges(next);
    setNodes((current) => refreshReadyStatuses(propagateConnectedPrompts(current, next, connection.source), next));
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
    const node = createNodeFromTemplate(templateId, targetPosition, sequence, [...canvasElementTemplates, ...registryTemplates]);
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
  }, [markUnsaved, notify, pickerInsertPosition, pushHistory, registryTemplates, screenToFlowPosition, selectNode, setInspectorOpen, setNodes]);

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
    const executionFields = new Set(["provider", "model", "resolution", "aspectRatio", "batchSize", "characterName", "shotCount", "durationSeconds", "loraUrl", "loraScale", "triggerWord", "transition", "targetDurationSeconds", "sourceLanguage", "separateMusic", "sceneThreshold", "targetLanguage", "voiceName", "captionX", "captionY", "captionAlign", "captionFontSize", "skillId"]);
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

  const saveSelectedTextOutput = useCallback((text: string) => {
    if (!selectedNodeId || !text.trim()) return;
    pushHistory();
    setNodes((current) => {
      const invalidated = invalidateDescendants(current, edgesRef.current, selectedNodeId);
      const updated = invalidated.map((node) => node.id === selectedNodeId && node.data.output && ["text", "json"].includes(node.data.output.kind) ? {
        ...node,
        data: {
          ...node.data,
          status: "SUCCEEDED" as NodeStatus,
          output: { ...node.data.output, text },
          outputEdited: true,
          preview: node.data.output.title,
        },
      } : node);
      return refreshReadyStatuses(propagateConnectedPrompts(updated, edgesRef.current, selectedNodeId, true), edgesRef.current);
    });
    markUnsaved();
    notify("수정한 결과를 저장하고 다음 Step 입력에 반영했습니다.", "success");
  }, [markUnsaved, notify, pushHistory, selectedNodeId, setNodes]);

  const updateNodeConfig = useCallback((nodeId: string, value: string) => {
    setNodes((current) => {
      const updated = current.map((node) => {
        if (node.id === nodeId) {
          const immediateSource = ["prompt.input", "asset.select", "character.select", "utility.sticky"].includes(node.data.key);
          const promptStatus: NodeStatus = immediateSource ? (value.trim() ? "SUCCEEDED" : "READY") : node.data.status === "SUCCEEDED" ? "STALE" : node.data.status;
          const selectedAssetOutput: CanvasOutput | undefined = node.data.key === "asset.select" && value.trim() ? { kind: "json", title: "Selected asset", text: JSON.stringify({ asset: value, reference_mode: "single" }, null, 2) } : undefined;
          return {
            ...node,
            data: {
              ...node.data,
              configText: value,
              status: promptStatus,
              output: selectedAssetOutput,
              preview: node.data.key === "asset.select" && value ? value : undefined,
              promptEdited: node.data.key === "prompt.input" ? true : node.data.promptEdited,
            },
          };
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

  const selectStoredCharacter = useCallback((nodeId: string, characterId: string) => {
    const character = characterOptions.find((item) => item.id === characterId);
    setNodes((current) => {
      const invalidated = invalidateDescendants(current, edgesRef.current, nodeId);
      const updated = invalidated.map((node) => {
        if (node.id !== nodeId) return node;
        if (!character) return { ...node, data: { ...node.data, status: "READY" as NodeStatus, configText: "", output: undefined, preview: undefined, outputArtifactIds: undefined, outputType: "Character" as PortType } };
        return { ...node, data: {
          ...node.data,
          status: "SUCCEEDED" as NodeStatus,
          configText: character.id,
          preview: character.name,
          outputType: "Character" as PortType,
          outputArtifactIds: [character.id],
          output: { kind: "image", title: `${character.name} · ${character.image_count} views`, url: character.cover_url, mimeType: "image/png" } as CanvasOutput,
        } };
      });
      return refreshReadyStatuses(updated, edgesRef.current);
    });
    markUnsaved();
  }, [characterOptions, markUnsaved, setNodes]);

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
    setGraphRunning(true);
    setGraphProgress(0);
    cancelRunRef.current = false;
    setNodes((current) => {
      const invalidated = invalidateDescendants(current, edgesRef.current, nodeId);
      return invalidated.map((candidate) => candidate.id === nodeId ? { ...candidate, data: { ...candidate.data, status: "QUEUED", runProgress: 0, logs: [...(candidate.data.logs ?? []), `${new Date().toLocaleTimeString("ko-KR")} · Step queued for Worker`] } } : candidate);
    });
    notify(`${node.data.label}을 Worker에 전달하는 중…`, "info");
    try {
      const saved = await saveNow();
      if (!saved) throw new Error("Canvas snapshot save failed");
      const run = await frameflowApi.createCanvasRun({
        canvas_id: canvasId,
        name: `${canvasName} · ${node.data.label}`.slice(0, 255),
        canvas_revision: saved.revision,
        target_node_id: nodeId,
      });
      setActiveCanvasRunId(run.id);
      setSaveState("Unsaved");
      notify(`${node.data.label} 단독 실행을 Worker에 전달했습니다.`, "success");
      return true;
    } catch (error) {
      const message = error instanceof Error ? error.message : "Canvas step execution failed";
      setGraphRunning(false);
      setNodes((current) => current.map((candidate) => candidate.id === nodeId ? { ...candidate, data: { ...candidate.data, status: "FAILED", runProgress: undefined, logs: [...(candidate.data.logs ?? []), `${new Date().toLocaleTimeString("ko-KR")} · ${message}`] } } : candidate));
      setExperimentHistoryError(message);
      markUnsaved();
      notify(message, "error");
      return false;
    }
  }, [canvasId, canvasName, markUnsaved, notify, saveNow, setNodes]);

  const validateAndOpen = useCallback(() => {
    const errors = validateGraph(nodesRef.current, edgesRef.current, registryConnectionCompatible);
    setCompileErrors(errors);
    setCompileOpen(true);
    notify(errors.length ? `${errors.length}개의 그래프 문제를 확인하세요.` : "그래프 검증을 통과했습니다.", errors.length ? "error" : "success");
  }, [notify, registryConnectionCompatible]);

  const publishDraft = useCallback(async () => {
    if (!workflowDefinitionId) return;
    const errors = validateGraph(nodesRef.current, edgesRef.current, registryConnectionCompatible);
    if (errors.length) {
      setCompileErrors(errors);
      setCompileOpen(true);
      return;
    }
    const existingOutputs = draftContract.outputs;
    const terminalNodes = nodesRef.current.filter((node) => node.data.outputType && !edgesRef.current.some((edge) => edge.source === node.id) && !["utility.sticky", "utility.drawing", "folder.group"].includes(node.data.key));
    if (!existingOutputs.length && terminalNodes.length !== 1) {
      notify(`Publish하려면 Primary output을 하나로 결정해야 합니다. 현재 terminal output은 ${terminalNodes.length}개입니다.`, "error");
      return;
    }
    const outputContract = existingOutputs.length ? existingOutputs : [{
      key: "primary_output",
      label: terminalNodes[0].data.label,
      node_id: terminalNodes[0].id,
      port_type: terminalNodes[0].data.outputType!,
      primary: true,
    }];
    const nextContract: WorkflowDraftContract = { ...draftContract, schema_version: "workflow.contract.draft.v1", outputs: outputContract };
    setPublishing(true);
    try {
      const backup = { ...cloneGraph(nodesRef.current, edgesRef.current), id: canvasId, name: canvasName, activeRunId: activeCanvasRunId ?? undefined };
      const saved = await frameflowApi.saveCanvas(canvasId, {
        name: canvasName,
        document: serializeCanvasDocument(backup.nodes, backup.edges, nodeDefinitions),
        active_run_id: activeCanvasRunId ?? undefined,
        draft_contract: nextContract,
      });
      setCanvasRevision(saved.revision);
      setDraftContract(nextContract);
      setSaveState("Saved");
      const version = await frameflowApi.publishWorkflow(workflowDefinitionId, {
        expected_canvas_revision: saved.revision,
        release_notes: baseVersionId ? "Published Canvas changes" : "Initial Canvas publish",
      });
      setBaseVersionId(version.id);
      window.dispatchEvent(new Event("frameflow:workspace-changed"));
      notify(`Workflow v${version.version_number}을 게시했습니다.${version.warnings?.length ? ` ${version.warnings.length}개 미사용 Node를 제외했습니다.` : ""}`, "success");
    } catch (publishError) {
      notify(publishError instanceof Error ? publishError.message : "Workflow Publish failed", "error");
    } finally {
      setPublishing(false);
    }
  }, [activeCanvasRunId, baseVersionId, canvasId, canvasName, draftContract, nodeDefinitions, notify, registryConnectionCompatible, workflowDefinitionId]);

  const applyCanvasRunUpdate = useCallback((run: CanvasRunRecord) => {
    const targetNodeId = typeof run.graph.target_node_id === "string" ? run.graph.target_node_id : undefined;
    const byNodeId = new Map(run.node_runs.map((node) => [node.canvas_node_id, node]));
    setNodes((current) => {
      const updated = current.map((node) => {
        if (targetNodeId && node.id !== targetNodeId) return node;
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
            outputEdited: output ? false : node.data.outputEdited,
            outputArtifactIds: server.output_artifact_ids.length ? server.output_artifact_ids : node.data.outputArtifactIds,
            duration: server.duration_ms ? `${server.duration_ms}ms` : node.data.duration,
            attemptCount: server.attempt_count,
            lastRequestHash: server.request_hash ?? node.data.lastRequestHash,
            lastCostUsd: server.cost_usd,
            runProgress: server.progress,
            logs: statusChanged ? [...(node.data.logs ?? []), `${new Date().toLocaleTimeString("ko-KR")} · Worker ${status}${server.error ? ` · ${server.error}` : ""}`] : node.data.logs,
          },
        };
      });
      return refreshReadyStatuses(propagateConnectedPrompts(updated, edgesRef.current, undefined, true), edgesRef.current);
    });
    const targetRun = targetNodeId ? byNodeId.get(targetNodeId) : undefined;
    setGraphProgress(targetRun?.progress ?? run.progress);
    const waiting = run.node_runs.find((node) => node.node_key === "candidate.select" && node.status === "WAITING_INPUT");
    if (waiting) {
      setCandidateNodeId(waiting.canvas_node_id);
      setSelectedCandidate(0);
      setCandidateOpen(true);
    }
    const waitingApproval = run.node_runs.find((node) => node.node_key === "timeline.compose" && node.status === "WAITING_INPUT");
    if (waitingApproval && waitingInputNodeRef.current !== waitingApproval.canvas_node_id) {
      waitingInputNodeRef.current = waitingApproval.canvas_node_id;
      selectNode(waitingApproval.canvas_node_id);
      setInspectorOpen(true);
      notify("자막 위치를 조정한 뒤 워크플로우를 계속 진행하세요.", "info");
    } else if (!waitingApproval) {
      waitingInputNodeRef.current = null;
    }
    if (["SUCCEEDED", "FAILED", "CANCELED"].includes(run.status)) {
      canvasRunEventsRef.current?.close();
      canvasRunEventsRef.current = null;
      setGraphRunning(false);
      setActiveCanvasRunId(null);
      setSaveState("Unsaved");
      if (run.status === "SUCCEEDED" && run.node_runs.some((node) => ["character.generate", "lora.train"].includes(node.node_key))) {
        void frameflowApi.listCharacters().then(setCharacterOptions).catch(() => undefined);
        window.dispatchEvent(new Event("frameflow:workspace-changed"));
      }
      if (targetNodeId && selectedNodeId === targetNodeId) {
        void frameflowApi.listExperiments(canvasId, targetNodeId)
          .then((items) => {
            setExperimentHistory(items);
            setExperimentHistoryNodeId(targetNodeId);
            setExperimentHistoryError(null);
          })
          .catch((error) => setExperimentHistoryError(error instanceof Error ? error.message : "Experiment history failed"));
      }
      const scope = targetNodeId ? "Step" : "모든 Step";
      notify(run.status === "SUCCEEDED" ? `Worker가 ${scope} 실행을 완료했습니다.` : run.status === "CANCELED" ? `Worker ${scope} 실행을 중단했습니다.` : `Worker ${scope} 실행이 실패했습니다.`, run.status === "SUCCEEDED" ? "success" : "error");
    } else {
      setGraphRunning(true);
    }
  }, [canvasId, notify, selectNode, selectedNodeId, setInspectorOpen, setNodes]);

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
    const errors = validateGraph(nodesRef.current, edgesRef.current, registryConnectionCompatible);
    if (errors.length) {
      setCompileErrors(errors);
      setCompileOpen(true);
      return;
    }
    setCompileOpen(false);
    setGraphRunning(true);
    setGraphProgress(0);
    cancelRunRef.current = false;
    setNodes((current) => current.map((node) => node.data.executable === false ? node : { ...node, data: { ...node.data, status: "QUEUED" as NodeStatus, runProgress: 0 } }));
    try {
      const saved = await saveNow();
      if (!saved) throw new Error("Canvas snapshot save failed");
      const run = await frameflowApi.createCanvasRun({
        canvas_id: canvasId,
        name: canvasName,
        canvas_revision: saved.revision,
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
  }, [applyCanvasRunUpdate, canvasId, canvasName, notify, registryConnectionCompatible, saveNow, setNodes, subscribeCanvasRun]);

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
  const selectedDefinition = selectedNode ? nodeDefinitions.find((definition) => definition.type_key === selectedNode.data.key && definition.contract_version === (selectedNode.data.contractVersion ?? 1)) : undefined;
  const selectedExposableFields = selectedDefinition ? Object.entries(selectedDefinition.config_schema.properties).filter(([, field]) => field["x-workflow-input"]?.enabled) : [];
  const exposeWorkflowInput = (configKey: string, field: NodeDefinitionRecord["config_schema"]["properties"][string]) => {
    if (!selectedNode || !field["x-workflow-input"]?.enabled) return;
    const path = `/config/${configKey}`;
    if (draftContract.bindings.some((binding) => binding.target.node_id === selectedNode.id && binding.target.path === path)) {
      setInputsPanelOpen(true);
      return;
    }
    const key = uniqueWorkflowInputKey(configKey, draftContract.inputs);
    const currentValue = exposedConfigValue(selectedNode, configKey, field.default);
    const input: WorkflowInputDefinition = {
      key,
      label: field.title ?? configKey.replaceAll("_", " "),
      description: field.description,
      type: field["x-workflow-input"].type as WorkflowInputDefinition["type"],
      required: false,
      ...(currentValue !== undefined ? { default: currentValue } : {}),
      ...(field.enum ? { options: field.enum } : {}),
      validation: {
        ...(field.minimum !== undefined ? { minimum: field.minimum } : {}),
        ...(field.maximum !== undefined ? { maximum: field.maximum } : {}),
        ...(field.minLength !== undefined ? { min_length: field.minLength } : {}),
        ...(field.maxLength !== undefined ? { max_length: field.maxLength } : {}),
      },
    };
    setDraftContract((current) => ({
      ...current,
      inputs: [...current.inputs, input],
      bindings: [...current.bindings, { target: { node_id: selectedNode.id, path }, value: { kind: "input", key } }],
    }));
    setSaveState("Unsaved");
    notify(`${input.label}을 Workflow input으로 노출했습니다.`, "success");
  };
  const detailNode = nodeDetailId ? nodes.find((node) => node.id === nodeDetailId) : undefined;
  useEffect(() => {
    if (!detailNode || selectedNodeId === detailNode.id) return;
    selectNode(detailNode.id);
    setInspectorOpen(false);
  }, [detailNode, selectNode, selectedNodeId, setInspectorOpen]);
  const closeNodeDetail = useCallback(() => {
    setInspectorOpen(true);
    onCloseNodeDetail();
  }, [onCloseNodeDetail, setInspectorOpen]);
  const selectedInputError = selectedNode ? stepInputError(selectedNode, nodes, edges) : null;
  const approveCaptionLayout = async () => {
    if (!activeCanvasRunId || !selectedNode) return;
    try {
      const run = await frameflowApi.approveCanvasNode(activeCanvasRunId, selectedNode.id, {
        caption_x: selectedNode.data.captionX ?? 0.5,
        caption_y: selectedNode.data.captionY ?? 0.82,
        caption_align: selectedNode.data.captionAlign ?? "center",
        caption_font_size: selectedNode.data.captionFontSize ?? 54,
      });
      applyCanvasRunUpdate(run);
      notify("자막 레이아웃을 확정했습니다. 남은 Step을 계속 실행합니다.", "success");
    } catch (error) {
      notify(error instanceof Error ? error.message : "자막 레이아웃 승인에 실패했습니다.", "error");
    }
  };
  const showExperimentHistory = Boolean(selectedNode?.data.executable !== false && selectedDefinition?.execution.kind !== "human_gate");
  useEffect(() => {
    if (!selectedNodeId || !showExperimentHistory) return;
    let active = true;
    frameflowApi.listExperiments(canvasId, selectedNodeId)
      .then((items) => { if (active) { setExperimentHistory(items); setExperimentHistoryNodeId(selectedNodeId); setExperimentHistoryError(null); } })
      .catch((error) => { if (active) { setExperimentHistoryNodeId(selectedNodeId); setExperimentHistoryError(error instanceof Error ? error.message : "Experiment history failed"); } });
    return () => { active = false; };
  }, [canvasId, selectedNodeId, showExperimentHistory]);
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
  const drawingNode = drawingNodeId ? nodes.find((node) => node.id === drawingNodeId && node.data.key === "utility.drawing") : undefined;
  const paletteGroups = useMemo(() => {
    const query = paletteQuery.trim().toLowerCase();
    const groups = ["Quick", "References", "Image", "Video", "Audio", "Utilities"] as const;
    const templates = [...canvasElementTemplates, ...registryTemplates];
    return groups.map((group) => ({ group, items: templates.filter((template) => template.visible !== false && template.group === group && (!query || `${template.label} ${template.data.key} ${template.data.outputType ?? ""}`.toLowerCase().includes(query))) })).filter((section) => section.items.length);
  }, [paletteQuery, registryTemplates]);
  const pickerGroups = useMemo(() => {
    const query = pickerQuery.trim().toLowerCase();
    const groups = ["Quick", "References", "Image", "Video", "Audio", "Utilities"] as const;
    const templates = [...canvasElementTemplates, ...registryTemplates];
    return groups.map((group) => ({ group, items: templates.filter((template) => template.visible !== false && template.group === group && (!query || `${template.label} ${template.data.key} ${template.data.outputType ?? ""}`.toLowerCase().includes(query))) })).filter((section) => section.items.length);
  }, [pickerQuery, registryTemplates]);
  const cost = graphCost(nodes);
  const successfulCount = nodes.filter((node) => node.data.status === "SUCCEEDED").length;
  const nodeDetailOpen = Boolean(nodeDetailId && selectedNode?.id === nodeDetailId);
  const showInspector = Boolean(!nodeDetailId && inspectorOpen && selectedNode && !["utility.sticky", "utility.drawing"].includes(selectedNode.data.key));
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
    selectCharacter: selectStoredCharacter,
    beginSpaceHold,
    assetOptions,
    characterOptions,
  }), [assetOptions, beginSpaceHold, characterOptions, edges, importNodeAssetUrl, nodes, runStep, selectStoredAsset, selectStoredCharacter, updateNodeConfig, updateStickyColor, uploadNodeAsset]);

  return (
    <div className={`canvas-shell ${paletteOpen ? "" : "palette-hidden"} ${showInspector ? "with-inspector" : ""}`}>
      <div className="canvas-toolbar">
        <div className="workflow-switcher canvas-name-field"><span className="workflow-glyph"><Workflow size={16} /></span><span><small>{workflowDefinitionId ? `Workflow draft · r${canvasRevision}` : "Canvas"}</small><input value={canvasName} onChange={(event) => { setCanvasName(event.target.value); markUnsaved(); }} aria-label="Canvas name" /></span></div>
        <Button className="new-canvas-button" variant="secondary" type="button" onClick={() => { void saveNow().then((saved) => { if (saved) onBack(); }); }} disabled={graphRunning || saveState === "Saving"}><ArrowLeft size={15} /> Canvases</Button>
        <span className="canvas-divider" />
        <button className="tool-icon" type="button" onClick={undo} disabled={!history.length} aria-label="Undo"><Undo2 size={16} /></button>
        <button className="tool-icon" type="button" onClick={redo} disabled={!future.length} aria-label="Redo"><Redo2 size={16} /></button>
        <span className="canvas-divider" />
        <button className={`saved-indicator save-${saveState.toLowerCase()}`} type="button" onClick={() => void saveNow()} disabled={saveState === "Saving"}><Save size={13} /> {saveState}</button>
        <button className="tool-icon reset-canvas" type="button" onClick={clearCanvas} disabled={graphRunning || !nodes.length} aria-label="Clear canvas"><Trash2 size={15} /></button>
        <div className="canvas-toolbar-spacer" />
        {workflowDefinitionId && <Button variant="secondary" type="button" onClick={() => setInputsPanelOpen(true)}><Braces size={14} /> Inputs {draftContract.inputs.length}</Button>}
        <Button variant="secondary" className="canvas-validate-button" type="button" onClick={validateAndOpen}><CircleGauge size={15} /> Validate</Button>
        {workflowDefinitionId && <Button variant="secondary" type="button" onClick={() => void publishDraft()} disabled={publishing || graphRunning}><GitFork size={14} /> {publishing ? "Publishing…" : baseVersionId ? "Publish next" : "Publish v1"}</Button>}
        <div className="cost-estimate"><span><CircleDollarSign size={13} /> Est. ${cost.toFixed(2)}</span><small>{nodes.length} steps · {edges.length} connections</small></div>
        {graphRunning && <Button variant="secondary" className="run-stop" type="button" onClick={stopGraph}><CircleStop size={15} /> Stop</Button>}
        <Button className="run-button" type="button" onClick={validateAndOpen} disabled={graphRunning}>
          {graphRunning ? <><RefreshCw className="spin" size={15} /> Running {graphProgress}%</> : <><Play size={14} fill="currentColor" /> Run workflow</>}
        </Button>
      </div>

      {paletteOpen && <aside className="node-palette">
        <div className="palette-title"><div><span className="subtle-label">Node library</span><strong>Add a step</strong></div><span className="node-count">{[...canvasElementTemplates, ...registryTemplates].filter((item) => item.visible !== false).length}</span></div>
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
          onNodeDoubleClick={(event, node) => {
            if ((event.target as HTMLElement).closest("button, input, textarea, select, a, [contenteditable='true']")) return;
            event.preventDefault();
            selectNode(node.id);
            setInspectorOpen(false);
            onOpenNodeDetail(node.id);
          }}
          onNodeDragStart={() => { dragStartRef.current = cloneGraph(nodesRef.current, edgesRef.current); }}
          onNodeDragStop={() => { if (dragStartRef.current) pushHistory(dragStartRef.current); dragStartRef.current = null; markUnsaved(); }}
          onPaneClick={(event) => { selectNode(null); if (event.detail === 2) { setPickerInsertPosition(screenToFlowPosition({ x: event.clientX, y: event.clientY })); setPickerOpen(true); } }}
          deleteKeyCode={["Backspace", "Delete"]}
          multiSelectionKeyCode={["Meta", "Shift"]}
          selectionOnDrag={interactionMode === "select"}
          panOnDrag={interactionMode === "pan" || spacePanActive}
          zoomOnScroll={false}
          zoomOnPinch
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
          <div className="canvas-legend"><span><i className="port-format" /> Format</span><span><i className="port-media" /> Media</span><span><i className="port-data" /> Data</span><span>Double-click: Edit details</span></div>
        </ReactFlow></NodeActionsContext.Provider>
        {!nodes.length && <div className="canvas-empty-state"><span className="empty-spark"><Sparkles size={22} /></span><h2>Start with a blank canvas</h2><p>저장된 실제 Asset과 Prompt 노드를 추가해 Workflow를 구성하세요.</p><div><Button type="button" onClick={() => setPickerOpen(true)}><Plus size={15} /> Add first step</Button></div></div>}
      </div>

      {(showInspector || nodeDetailOpen) && selectedNode && (
        <NodeDetailSurface node={selectedNode} open={nodeDetailOpen} onClose={closeNodeDetail} onTextOutputSave={saveSelectedTextOutput}>
        <aside className={`node-inspector ${nodeDetailOpen ? "node-detail-inspector" : ""}`}>
          <div className="inspector-heading"><div><span className="subtle-label">Node inspector</span><strong>{selectedNode.data.label}</strong></div><Button variant="ghost" size="icon-sm" className="size-[25px] min-h-[25px]" type="button" onClick={nodeDetailOpen ? closeNodeDetail : () => setInspectorOpen(false)} aria-label="Close node inspector"><PanelRightClose size={16} /></Button></div>
          <div className="inspector-status"><CanvasNodeStatus data={selectedNode.data} /><span>{selectedNode.data.key}</span></div>
          <div className="inspector-tabs"><span className="active">Settings</span></div>
          <div className="inspector-content">
            {selectedNode.data.executable !== false && <Button className="step-run-button" type="button" onClick={() => void runStep(selectedNode.id)} disabled={selectedNode.data.status === "RUNNING" || graphRunning || !!selectedInputError}>
              {selectedNode.data.status === "RUNNING" ? <><RefreshCw className="spin" size={15} /> Running step…</> : <><Play size={14} fill="currentColor" /> Run this step</>}
            </Button>}
            <p className={`step-run-help ${selectedInputError ? "has-error" : ""}`}>{selectedNode.data.executable === false ? "입력 또는 Canvas 정리용 노드입니다." : selectedInputError ?? "이 Step만 실행합니다. 연결된 입력을 사용합니다."}</p>
            <NodeInspectorEditor
              node={selectedNode}
              definition={selectedDefinition}
              nodes={nodes}
              edges={edges}
              models={models}
              projectSkills={projectSkills}
              activeCanvasRunId={activeCanvasRunId}
              onChange={updateSelectedData}
              onApproveCaptionLayout={() => void approveCaptionLayout()}
              onOpenCandidate={() => { setCandidateNodeId(selectedNode.id); setSelectedCandidate(0); setCandidateOpen(true); }}
            />
            {workflowDefinitionId && selectedExposableFields.length > 0 && <div className="rounded-lg border border-[#d8dad3] bg-[#f7f7f3] p-2.5">
              <div className="mb-2 flex items-center justify-between"><span><small className="block text-[10px] uppercase tracking-[.08em] text-[#858980]">Workflow contract</small><strong className="text-xs text-[#3e413b]">Expose settings as inputs</strong></span><Button type="button" variant="ghost" size="sm" onClick={() => setInputsPanelOpen(true)}><Braces size={13} /> {draftContract.inputs.length}</Button></div>
              <div className="flex flex-wrap gap-1.5">{selectedExposableFields.map(([configKey, field]) => {
                const binding = draftContract.bindings.find((item) => item.target.node_id === selectedNode.id && item.target.path === `/config/${configKey}`);
                const inputKey = binding?.value.kind === "input" ? binding.value.key : undefined;
                return <button type="button" className={`rounded-md border px-2 py-1 text-[10px] ${binding ? "border-[#8178e8] bg-[#eeecff] text-[#554ca8]" : "border-[#d3d5ce] bg-white text-[#666a62]"}`} onClick={() => exposeWorkflowInput(configKey, field)} key={configKey}>{binding ? `${field.title ?? configKey} · ${inputKey}` : `+ ${field.title ?? configKey}`}</button>;
              })}</div>
            </div>}
            <label className="field-label"><span>Node name</span><Input value={selectedNode.data.label} onChange={(event) => updateSelectedData({ label: event.target.value })} /></label>
            <label className="field-label"><span>Description</span><Textarea value={selectedNode.data.description} onChange={(event) => updateSelectedData({ description: event.target.value })} /></label>
            {selectedNode.data.model && selectedNode.data.kind !== "generate" && !selectedDefinition && <label className="field-label"><span>Runtime engine</span><Input value={selectedNode.data.model} readOnly /><small>로컬 실행 엔진과 버전이 실행 이력에 고정됩니다.</small></label>}
            <div className="inspector-section-title"><span>Input contracts</span><Braces size={14} /></div>
            {(selectedNode.data.inputTypes?.length ? selectedNode.data.inputTypes : ["Source node"]).map((type, index) => {
              const handleId = type === "Source node" ? undefined : inputHandleId(type as PortType, index);
              const connectionCount = type === "Source node" ? 0 : edges.filter((edge) => edge.target === selectedNode.id && (edge.targetHandle === handleId || (!edge.targetHandle && selectedNode.data.inputTypes?.length === 1))).length;
              const connected = connectionCount > 0;
              const required = selectedNode.data.requiredInputTypes?.includes(type as PortType) ?? selectedNode.data.inputsRequired !== false;
              const optional = !required;
              const acceptsMany = selectedNode.data.multiInputTypes?.includes(type as PortType);
              return <div className="port-contract" key={`${type}-${index}`}><span className={`contract-dot type-${String(type).toLowerCase()}`} /><span><strong>{type}{acceptsMany ? " × N" : ""}</strong><small>{type === "Source node" ? "No input required" : connected ? `${connectionCount} connected` : optional ? "Optional input" : "Required · not connected"}</small></span>{type !== "Source node" && (connected ? <span className="contract-status"><CircleCheck size={15} /><button type="button" className="contract-disconnect" onClick={() => disconnectInput(selectedNode.id, type as PortType, index)} aria-label={`${type} 입력 연결 해제`} title={`${type} 입력 연결 해제`}><Unlink2 size={13} /> 해제</button></span> : optional ? <span className="optional-port">Optional</span> : <CircleAlert size={15} className="contract-warning" />)}</div>;
            })}
            <div className="inspector-section-title"><span>Runtime</span><CircleGauge size={14} /></div>
            <div className="runtime-grid"><div><small>Last duration</small><strong>{selectedNode.data.duration ?? "—"}</strong></div><div><small>Est. cost</small><strong>{selectedNode.data.cost ?? (selectedDefinition?.execution.kind === "provider" ? "Provider billed" : "$0.00")}</strong></div><div><small>Attempts</small><strong>{selectedNode.data.attemptCount ?? 0}</strong></div><div><small>Output</small><strong>{selectedNode.data.outputType ?? "—"}</strong></div></div>
            {showExperimentHistory && <div className="experiment-history">
              <div className="experiment-history-head"><span><ListRestart size={13} /> Experiment history</span><small>{visibleExperimentHistory.length} runs</small></div>
              {experimentHistoryNodeId === selectedNodeId && experimentHistoryError && <p className="experiment-history-state error">{experimentHistoryError}</p>}
              {experimentHistoryNodeId === selectedNodeId && !experimentHistoryError && !visibleExperimentHistory.length && <p className="experiment-history-state">이 설정으로 저장된 실행이 없습니다.</p>}
              {visibleExperimentHistory.map((experiment) => <article className={`experiment-run ${experiment.is_baseline ? "baseline" : ""}`} key={experiment.id}>
                <div><strong>{experiment.model_alias.replace("google.", "")}</strong><time>{new Date(experiment.created_at).toLocaleString("ko-KR", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" })}</time></div>
                <p>{experiment.prompt}</p>
                <div className="experiment-run-meta"><span>{experiment.cache_hit ? "Cache" : experiment.execution_mode}</span><span>{experiment.duration_ms}ms</span><span>${experiment.cost_usd.toFixed(2)}</span><code>{experiment.request_hash.slice(0, 7)}</code></div>
                <div className="experiment-run-actions">{experiment.is_baseline ? <span><BadgeCheck size={12} /> Baseline</span> : <button type="button" onClick={() => void markExperimentBaseline(experiment.id)}>Set baseline</button>}<button type="button" onClick={() => updateSelectedData({ status: "SUCCEEDED", output: experiment.output, outputEdited: false, preview: experiment.output.title, lastExperimentId: experiment.id, outputArtifactIds: experiment.output_artifact_ids })}>Show result</button></div>
              </article>)}
            </div>}
            {selectedNode.data.preview && <div className="step-output-preview"><span>Latest output</span><strong>{selectedNode.data.preview}</strong></div>}
          </div>
          <div className="inspector-edit-actions"><Button variant="secondary" type="button" onClick={duplicateSelected}><Copy size={14} /> Duplicate</Button><Button variant="danger" type="button" onClick={deleteSelected}><Trash2 size={14} /> Delete</Button></div>
          {selectedNode.data.executable !== false && <div className="inspector-actions"><Button variant="secondary" size="sm" className="min-w-0 px-1 text-[length:var(--text-2xs)]" type="button" onClick={() => void runStep(selectedNode.id)} disabled={!!selectedInputError}><ListRestart size={13} /> Retry</Button><Button variant="secondary" size="sm" className="min-w-0 px-1 text-[length:var(--text-2xs)]" type="button" disabled={!!selectedInputError} onClick={() => { updateSelectedData({ status: selectedNode.data.requiredInputTypes?.length || (selectedNode.data.inputTypes?.length && selectedNode.data.inputsRequired !== false) ? "BLOCKED" : "READY" }); window.setTimeout(() => void runStep(selectedNode.id), 0); }}><RefreshCw size={13} /> Regenerate</Button><Button variant="secondary" size="sm" className="min-w-0 px-1 text-[length:var(--text-2xs)]" type="button" onClick={duplicateSelected}><GitFork size={13} /> Fork</Button></div>}
        </aside>
        </NodeDetailSurface>
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
        key={drawingNode.id}
        document={drawingNode.data.drawing ?? { version: 1, width: 1280, height: 720, images: [], strokes: [] }}
        nodeName={drawingNode.data.label}
        previewUrl={drawingNode.data.output?.kind === "image" ? drawingNode.data.output.url : undefined}
        onAddImage={uploadDrawingSource}
        onClose={() => setDrawingNodeId(null)}
        onSave={(drawing, image) => saveDrawing(drawingNode.id, drawing, image)}
      />}
      <WorkflowInputsPanel
        open={inputsPanelOpen}
        contract={draftContract}
        onOpenChange={setInputsPanelOpen}
        onChange={(contract) => { setDraftContract(contract); setSaveState("Unsaved"); }}
      />
    </div>
  );
}
