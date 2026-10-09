import type { Edge, Node, XYPosition } from "@xyflow/react";
import type { NodeStatus, PortType } from "./types";

export type NodeKind = "input" | "logic" | "generate" | "compose" | "review";
export type ProviderName = string;
export type StickyColor = "yellow" | "pink" | "blue" | "green" | "lavender" | "gray";
export type CaptionAlignment = "left" | "center" | "right";
export type IconName = "brief" | "format" | "reference" | "motion" | "resolve" | "script" | "shot" | "character" | "lora" | "image" | "video" | "voice" | "select" | "subtitle" | "timeline" | "render" | "qc" | "upload" | "assets" | "folder" | "assistant" | "skill" | "text" | "sticky" | "drawing" | "changeVoice" | "translate";

export interface DrawingPoint {
  x: number;
  y: number;
}

export interface DrawingStroke {
  id: string;
  color: string;
  width: number;
  points: DrawingPoint[];
}

export interface DrawingImage {
  id: string;
  name: string;
  src: string;
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface DrawingDocument {
  version: 1;
  width: number;
  height: number;
  images: DrawingImage[];
  strokes: DrawingStroke[];
}

export interface CanvasOutput {
  kind: "image" | "video" | "audio" | "text" | "json";
  title: string;
  url?: string;
  text?: string;
  mimeType?: string;
  characterId?: string;
  imageCount?: number;
  images?: { url: string; title: string; artifactId: string }[];
  frameCount?: number;
  sampleFps?: number;
  faceCoverage?: number;
  poseCoverage?: number;
  leftHandCoverage?: number;
  rightHandCoverage?: number;
}

export interface StudioNodeContractData {
  key: string;
  label: string;
  description: string;
  icon: IconName;
  kind: NodeKind;
  inputPorts?: Array<{ key: string; type: string; label: string; required?: boolean; multiple?: boolean }>;
  outputPorts?: Array<{ key: string; type: string; label: string; legacyType: PortType }>;
  inputTypes?: PortType[];
  inputsRequired?: boolean;
  requiredInputTypes?: PortType[];
  multiInputTypes?: PortType[];
  outputType?: PortType;
  model?: string;
  provider?: ProviderName;
  cost?: string;
  contractVersion?: number;
  definitionDigest?: string;
  config?: Record<string, unknown>;
  executable?: boolean;
}

export interface StudioNodeRuntimeData {
  status: NodeStatus;
  output?: CanvasOutput;
  outputEdited?: boolean;
  outputArtifactIds?: string[];
  attemptCount?: number;
  lastRunAt?: string;
  logs?: string[];
  lastExperimentId?: string;
  lastRequestHash?: string;
  executionMode?: string;
  lastCostUsd?: number;
  runProgress?: number;
  promptEdited?: boolean;
}

/** Fields read only by the pre-canonical Canvas compatibility adapter. */
export interface LegacyStudioNodeFields {
  duration?: string;
  preview?: string;
  fanout?: string;
  configText?: string;
  skillId?: string;
  resolution?: string;
  aspectRatio?: string;
  batchSize?: number;
  characterName?: string;
  shotCount?: number;
  durationSeconds?: number;
  loraUrl?: string;
  loraScale?: number;
  triggerWord?: string;
  transition?: string;
  targetDurationSeconds?: number;
  sourceLanguage?: string;
  separateMusic?: boolean;
  sceneThreshold?: number;
  motionSampleFps?: number;
  motionMaxWidth?: number;
  motionMinConfidence?: number;
  motionFaceBlendshapes?: boolean;
  targetLanguage?: string;
  voiceName?: string;
  captionX?: number;
  captionY?: number;
  captionAlign?: CaptionAlignment;
  captionFontSize?: number;
  waitForInput?: boolean;
  stickyColor?: StickyColor;
  drawing?: DrawingDocument;
}

export type StudioNodeData = Record<string, unknown>
  & StudioNodeContractData
  & StudioNodeRuntimeData
  & LegacyStudioNodeFields;

export type StudioFlowNode = Node<StudioNodeData, "studio">;

export interface NodeTemplate {
  id: string;
  label: string;
  group: "Quick" | "References" | "Image" | "Video" | "Audio" | "Utilities" | "Advanced";
  visible?: boolean;
  data: StudioNodeContractData & LegacyStudioNodeFields;
}

/** Canvas-only authoring tools; production Nodes come exclusively from the Registry. */
export const canvasElementTemplates: NodeTemplate[] = [
  { id: "drawing-canvas", label: "Drawing Canvas", group: "Quick", data: { key: "utility.drawing", label: "Drawing canvas", description: "이미지를 배치하고 펜으로 지시사항을 표시", icon: "drawing", kind: "input", outputType: "Image", executable: false, drawing: { version: 1, width: 1280, height: 720, images: [], strokes: [] } } },
  { id: "folder", label: "Folders", group: "Advanced", visible: false, data: { key: "folder.group", label: "Folder", description: "Canvas 노드를 시각적으로 정리", icon: "folder", kind: "input", configText: "New folder", executable: false } },
  { id: "upload", label: "Upload", group: "References", data: { key: "asset.upload", label: "Upload", description: "로컬 이미지·영상·오디오 업로드", icon: "upload", kind: "input", outputType: "ReferenceAsset", executable: false } },
  { id: "sticky", label: "Sticky Note", group: "Utilities", data: { key: "utility.sticky", label: "Sticky note", description: "실행과 무관한 Canvas 메모", icon: "sticky", kind: "input", configText: "", stickyColor: "yellow", executable: false } },
];

export const inputHandleId = (type: PortType, index: number) => `input-${type}-${index}`;

export function createNodeFromTemplate(templateId: string, position: XYPosition, sequence: number, templates: NodeTemplate[]): StudioFlowNode | null {
  const template = templates.find((item) => item.id === templateId);
  if (!template) return null;
  return {
    id: `${template.id}-${Date.now()}-${sequence}`,
    type: "studio",
    position,
    data: {
      ...template.data,
      status: template.data.requiredInputTypes?.length || (template.data.inputTypes?.length && template.data.inputsRequired !== false) ? "BLOCKED" : "READY",
      attemptCount: 0,
      logs: [],
    },
  };
}

function targetType(edge: Pick<Edge, "targetHandle">, target: StudioFlowNode): PortType | undefined {
  const types = target.data.inputTypes ?? [];
  if (edge.targetHandle) {
    return types.find((type, index) => edge.targetHandle === inputHandleId(type, index));
  }
  return types.length === 1 ? types[0] : undefined;
}

export function inputPortMatches(node: StudioFlowNode, handle: string | null | undefined, index: number): boolean {
  if (index < 0) return false;
  if (!handle) return node.data.inputTypes?.length === 1;
  const key = node.data.inputPorts?.[index]?.key;
  return handle === inputHandleId(node.data.inputTypes![index], index) || Boolean(key && (handle === key || handle === `input-${key}`));
}

export type ConnectionCompatibilityValidator = (connection: Pick<Edge, "source" | "target" | "sourceHandle" | "targetHandle">, nodes: StudioFlowNode[]) => boolean;

export function isConnectionCompatible(connection: Pick<Edge, "source" | "target" | "sourceHandle" | "targetHandle">, nodes: StudioFlowNode[]): boolean {
  if (connection.source === connection.target) return false;
  const source = nodes.find((node) => node.id === connection.source);
  const target = nodes.find((node) => node.id === connection.target);
  if (!source || !target || !source.data.outputType) return false;
  const input = targetType(connection, target);
  return input === "Any" || source.data.outputType === input;
}

export function validateGraph(nodes: StudioFlowNode[], edges: Edge[], connectionCompatible: ConnectionCompatibilityValidator = isConnectionCompatible): string[] {
  const errors: string[] = [];
  if (!nodes.length) return ["그래프에 노드가 없습니다."];
  for (const edge of edges) {
    if (!connectionCompatible(edge, nodes)) errors.push(`호환되지 않는 연결: ${edge.source} → ${edge.target}`);
  }
  for (const node of nodes) {
    const allInputs = node.data.inputTypes ?? [];
    if (node.data.key === "lora.image.generate" && !node.data.loraUrl?.trim()) {
      const characterIndex = allInputs.indexOf("Character");
      const hasCharacter = edges.some((edge) => edge.target === node.id && inputPortMatches(node, edge.targetHandle, characterIndex));
      if (!hasCharacter) errors.push(`${node.data.label}: LoRA weights URL 또는 학습 완료 Character 입력이 필요합니다.`);
    }
    if (node.data.key === "character.generate") {
      const hasCharacterSource = edges.some((edge) => edge.target === node.id && ["Prompt", "Image"].some((type) => {
        const index = allInputs.indexOf(type as PortType);
        return inputPortMatches(node, edge.targetHandle, index);
      }));
      if (!hasCharacterSource) errors.push(`${node.data.label}: Prompt 또는 Image 입력이 필요합니다.`);
    }
    const requiredInputs = node.data.requiredInputTypes ?? (node.data.inputsRequired === false ? [] : allInputs);
    for (const type of requiredInputs) {
      const index = allInputs.indexOf(type);
      const connected = edges.some((edge) => edge.target === node.id && inputPortMatches(node, edge.targetHandle, index));
      if (!connected) errors.push(`${node.data.label}: ${type} 입력이 필요합니다.`);
      const inputEdge = edges.find((edge) => edge.target === node.id && inputPortMatches(node, edge.targetHandle, index));
      const source = nodes.find((candidate) => candidate.id === inputEdge?.source);
      if (type === "Prompt" && source?.data.key === "prompt.input" && !source.data.configText?.trim()) errors.push(`${node.data.label}: 연결된 Prompt가 비어 있습니다.`);
    }
  }
  if (topologicalOrder(nodes, edges).length !== nodes.length) errors.push("그래프에 순환 연결이 있습니다.");
  return [...new Set(errors)];
}

export function topologicalOrder(nodes: StudioFlowNode[], edges: Edge[]): string[] {
  const ids = new Set(nodes.map((node) => node.id));
  const indegree = new Map([...ids].map((id) => [id, 0]));
  const outgoing = new Map([...ids].map((id) => [id, [] as string[]]));
  for (const edge of edges) {
    if (!ids.has(edge.source) || !ids.has(edge.target)) continue;
    indegree.set(edge.target, (indegree.get(edge.target) ?? 0) + 1);
    outgoing.get(edge.source)?.push(edge.target);
  }
  const queue = [...ids].filter((id) => indegree.get(id) === 0);
  const order: string[] = [];
  while (queue.length) {
    const id = queue.shift()!;
    order.push(id);
    for (const target of outgoing.get(id) ?? []) {
      const next = (indegree.get(target) ?? 1) - 1;
      indegree.set(target, next);
      if (next === 0) queue.push(target);
    }
  }
  return order;
}

export function stepInputError(node: StudioFlowNode, nodes: StudioFlowNode[], edges: Edge[]): string | null {
  const allInputs = node.data.inputTypes ?? [];
  if (node.data.key === "lora.image.generate" && !node.data.loraUrl?.trim()) {
    const characterIndex = allInputs.indexOf("Character");
    const characterEdge = edges.find((edge) => edge.target === node.id && inputPortMatches(node, edge.targetHandle, characterIndex));
    const characterSource = nodes.find((candidate) => candidate.id === characterEdge?.source);
    if (!characterSource) return "LoRA weights URL 또는 학습 완료 Character를 연결하세요.";
    if (characterSource.data.status !== "SUCCEEDED") return "연결된 Character Step을 먼저 준비하세요.";
  }
  if (node.data.key === "character.generate") {
    const candidateEdges = edges.filter((edge) => edge.target === node.id && ["Prompt", "Image"].some((type) => {
      const index = allInputs.indexOf(type as PortType);
      return inputPortMatches(node, edge.targetHandle, index);
    }));
    if (!candidateEdges.length) return "Prompt 또는 기준 Image를 연결하세요.";
    const hasUsableSource = candidateEdges.some((edge) => {
      const source = nodes.find((candidate) => candidate.id === edge.source);
      if (!source || source.data.status !== "SUCCEEDED") return false;
      return source.data.outputType !== "Prompt" || Boolean(source.data.output?.text?.trim() || source.data.configText?.trim());
    });
    if (!hasUsableSource) return "연결된 Prompt 또는 Image Step을 먼저 준비하세요.";
  }
  const requiredInputs = node.data.requiredInputTypes ?? (node.data.inputsRequired === false ? [] : allInputs);
  for (const type of requiredInputs) {
    const index = allInputs.indexOf(type);
    const matchingEdges = edges.filter((candidate) => candidate.target === node.id && inputPortMatches(node, candidate.targetHandle, index));
    if (!matchingEdges.length) return `${type} 입력을 먼저 연결하세요.`;
    for (const edge of matchingEdges) {
      const source = nodes.find((candidate) => candidate.id === edge.source);
      if (source?.data.key === "prompt.input" && !source.data.configText?.trim()) return "연결된 Prompt에 내용을 입력하세요.";
      if (!source || source.data.status !== "SUCCEEDED") return `${source?.data.label ?? type} Step을 먼저 실행하세요.`;
    }
  }
  return null;
}

export function refreshReadyStatuses(nodes: StudioFlowNode[], edges: Edge[]): StudioFlowNode[] {
  return nodes.map((node) => {
    if (node.data.key === "utility.drawing") {
      return { ...node, data: { ...node.data, status: node.data.output ? "SUCCEEDED" : "READY" } };
    }
    if (["prompt.input", "asset.select", "character.select", "utility.sticky"].includes(node.data.key)) {
      return { ...node, data: { ...node.data, status: node.data.configText?.trim() ? "SUCCEEDED" : "READY" } };
    }
    if (node.data.status === "STALE") return node;
    if (["RUNNING", "SUCCEEDED", "WAITING_INPUT", "FAILED"].includes(node.data.status)) return node;
    const ready = !stepInputError(node, nodes, edges);
    return { ...node, data: { ...node.data, status: ready ? "READY" : "BLOCKED" } };
  });
}

export function graphCost(nodes: StudioFlowNode[]): number {
  return nodes.reduce((sum, node) => {
    const usd = node.data.cost?.match(/^\$(\d+(?:\.\d+)?)/)?.[1];
    return sum + (usd ? Number(usd) : 0);
  }, 0);
}
