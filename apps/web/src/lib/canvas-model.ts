import type { Edge, Node, XYPosition } from "@xyflow/react";
import type { NodeStatus, PortType } from "./types";

export type NodeKind = "input" | "logic" | "generate" | "compose" | "review";
export type ProviderName = "google" | "openai";
export type IconName = "brief" | "format" | "reference" | "resolve" | "script" | "shot" | "image" | "video" | "voice" | "select" | "subtitle" | "timeline" | "render" | "qc" | "upload" | "assets" | "folder" | "assistant" | "text" | "sticky" | "changeVoice" | "translate";

export interface CanvasOutput {
  kind: "image" | "video" | "audio" | "text" | "json";
  title: string;
  url?: string;
  text?: string;
  mimeType?: string;
}

export interface StudioNodeData extends Record<string, unknown> {
  key: string;
  label: string;
  description: string;
  icon: IconName;
  kind: NodeKind;
  status: NodeStatus;
  inputTypes?: PortType[];
  inputsRequired?: boolean;
  requiredInputTypes?: PortType[];
  multiInputTypes?: PortType[];
  outputType?: PortType;
  model?: string;
  provider?: ProviderName;
  cost?: string;
  duration?: string;
  preview?: string;
  fanout?: string;
  attemptCount?: number;
  lastRunAt?: string;
  logs?: string[];
  configText?: string;
  output?: CanvasOutput;
  lastExperimentId?: string;
  outputArtifactIds?: string[];
  lastRequestHash?: string;
  executionMode?: string;
  lastCostUsd?: number;
  resolution?: string;
  aspectRatio?: string;
  batchSize?: number;
  executable?: boolean;
  transition?: string;
  targetDurationSeconds?: number;
  frameTimestampMs?: number;
  sourceLanguage?: string;
  targetLanguage?: string;
  voiceName?: string;
}

export type StudioFlowNode = Node<StudioNodeData, "studio">;

export interface NodeTemplate {
  id: string;
  label: string;
  group: "Quick" | "References" | "Image" | "Video" | "Audio" | "Utilities" | "Advanced";
  visible?: boolean;
  data: {
    key: string;
    label: string;
    description: string;
    icon: IconName;
    kind: NodeKind;
    inputTypes?: PortType[];
    inputsRequired?: boolean;
    requiredInputTypes?: PortType[];
    multiInputTypes?: PortType[];
    outputType?: PortType;
    model?: string;
    provider?: ProviderName;
    cost?: string;
    duration?: string;
    preview?: string;
    fanout?: string;
    configText?: string;
    resolution?: string;
    aspectRatio?: string;
    batchSize?: number;
    executable?: boolean;
    transition?: string;
    targetDurationSeconds?: number;
    frameTimestampMs?: number;
    sourceLanguage?: string;
    targetLanguage?: string;
    voiceName?: string;
  };
}

export const nodeTemplates: NodeTemplate[] = [
  { id: "prompt", label: "Prompt", group: "Quick", data: { key: "prompt.input", label: "Prompt", description: "다음 Step으로 전달할 Prompt", icon: "brief", kind: "input", outputType: "Prompt", configText: "", executable: false } },
  { id: "image", label: "Image Generator", group: "Quick", data: { key: "image.generate", label: "Image generator", description: "Prompt 필수 · Asset은 선택", icon: "image", kind: "generate", inputTypes: ["Prompt", "ReferenceAsset"], requiredInputTypes: ["Prompt"], outputType: "Image", provider: "google", model: "image.fast", cost: "$0.21", resolution: "2K", aspectRatio: "9:16", batchSize: 1 } },
  { id: "video", label: "Video Generator", group: "Quick", data: { key: "video.generate", label: "Video generator", description: "Prompt 필수 · 여러 이미지는 선택", icon: "video", kind: "generate", inputTypes: ["Prompt", "Image", "ReferenceAsset"], requiredInputTypes: ["Prompt"], multiInputTypes: ["Image"], outputType: "Video", provider: "google", model: "video.fast", cost: "$1.40", resolution: "1080p", aspectRatio: "9:16", batchSize: 1 } },
  { id: "voice", label: "Voiceover", group: "Quick", data: { key: "tts.generate", label: "Voiceover", description: "연결된 Prompt를 음성으로 생성", icon: "voice", kind: "generate", inputTypes: ["Prompt"], requiredInputTypes: ["Prompt"], outputType: "Audio", provider: "google", model: "tts.fast", cost: "$0.12", resolution: "24kHz", aspectRatio: "Audio", batchSize: 1 } },
  { id: "assistant", label: "LLM Assistant", group: "Quick", data: { key: "llm.assistant", label: "LLM assistant", description: "연결된 Prompt를 분석·변환", icon: "assistant", kind: "generate", inputTypes: ["Prompt"], requiredInputTypes: ["Prompt"], outputType: "Text", provider: "google", model: "text.quality", cost: "$0.03" } },
  { id: "folder", label: "Folders", group: "Advanced", visible: false, data: { key: "folder.group", label: "Folder", description: "Canvas 노드를 시각적으로 정리", icon: "folder", kind: "input", configText: "New folder", executable: false } },

  { id: "upload", label: "Asset", group: "References", data: { key: "asset.upload", label: "Asset", description: "로컬 이미지·영상·오디오 업로드", icon: "upload", kind: "input", outputType: "ReferenceAsset", executable: false } },
  { id: "assets", label: "Assets", group: "References", data: { key: "asset.select", label: "Assets", description: "저장된 이미지·비디오를 Popover에서 선택", icon: "assets", kind: "input", outputType: "ReferenceAsset", configText: "", executable: false } },

  { id: "image-category", label: "Image Generator", group: "Image", data: { key: "image.generate", label: "Image generator", description: "Prompt 필수 · Asset은 선택", icon: "image", kind: "generate", inputTypes: ["Prompt", "ReferenceAsset"], requiredInputTypes: ["Prompt"], outputType: "Image", provider: "google", model: "image.fast", cost: "$0.21", resolution: "2K", aspectRatio: "9:16", batchSize: 1 } },
  { id: "video-category", label: "Video Generator", group: "Video", data: { key: "video.generate", label: "Video generator", description: "Prompt 필수 · 여러 이미지는 선택", icon: "video", kind: "generate", inputTypes: ["Prompt", "Image", "ReferenceAsset"], requiredInputTypes: ["Prompt"], multiInputTypes: ["Image"], outputType: "Video", provider: "google", model: "video.fast", cost: "$1.40", resolution: "1080p", aspectRatio: "9:16", batchSize: 1 } },
  { id: "video-editor", label: "Video Editor", group: "Video", data: { key: "video.edit", label: "Video editor", description: "여러 Video를 연결 순서대로 합성하고 트랜지션·길이를 적용", icon: "timeline", kind: "compose", inputTypes: ["Video"], requiredInputTypes: ["Video"], multiInputTypes: ["Video"], outputType: "Video", model: "local.ffmpeg", cost: "$0.00", resolution: "1080p", aspectRatio: "9:16", transition: "hard_cut", targetDurationSeconds: 30 } },
  { id: "frame-extract", label: "Frame Extract", group: "Video", data: { key: "video.frame_extract", label: "Frame extract", description: "Video의 지정 타임스탬프를 Image Artifact로 캡처", icon: "image", kind: "compose", inputTypes: ["Video"], requiredInputTypes: ["Video"], outputType: "Image", model: "local.ffmpeg", cost: "$0.00", frameTimestampMs: 0 } },

  { id: "voice-category", label: "Voiceover", group: "Audio", data: { key: "tts.generate", label: "Voiceover", description: "연결된 Prompt를 음성으로 생성", icon: "voice", kind: "generate", inputTypes: ["Prompt"], requiredInputTypes: ["Prompt"], outputType: "Audio", provider: "google", model: "tts.fast", cost: "$0.12", resolution: "24kHz", aspectRatio: "Audio", batchSize: 1 } },
  { id: "change-voice", label: "Replace Audio", group: "Audio", data: { key: "video.change_voice", label: "Replace video audio", description: "Video의 기존 오디오를 연결된 Audio로 실제 교체", icon: "changeVoice", kind: "compose", inputTypes: ["Video", "Audio"], requiredInputTypes: ["Video", "Audio"], outputType: "Video", model: "local.ffmpeg", cost: "$0.00" } },
  { id: "translate", label: "Translate Video", group: "Audio", data: { key: "video.translate", label: "Translate video", description: "Chirp 3 음성인식·Gemini 번역·Gemini TTS로 영상 현지화", icon: "translate", kind: "compose", inputTypes: ["Video"], requiredInputTypes: ["Video"], outputType: "Video", model: "google.localization.pipeline", cost: "$0.35", sourceLanguage: "auto", targetLanguage: "ko-KR", voiceName: "Kore" } },

  { id: "text", label: "Text", group: "Utilities", data: { key: "utility.text", label: "Text", description: "Canvas 메모 또는 텍스트 전달", icon: "text", kind: "input", outputType: "Text", configText: "", executable: false } },
  { id: "sticky", label: "Sticky Note", group: "Utilities", data: { key: "utility.sticky", label: "Sticky note", description: "실행과 무관한 Canvas 메모", icon: "sticky", kind: "input", configText: "", executable: false } },

  { id: "brief", label: "Generation brief", group: "Advanced", visible: false, data: { key: "generation.brief", label: "Generation brief", description: "주제, 메시지, 시청자와 목표 길이", icon: "brief", kind: "input", outputType: "Text", configText: "", executable: false } },
  { id: "format", label: "Format profile", group: "Advanced", visible: false, data: { key: "format.profile", label: "Format profile", description: "생성에 사용할 FormatCoreV1", icon: "format", kind: "input", outputType: "FormatProfile", preview: "Select a format", executable: false } },
  { id: "resolve", label: "Resolve spec", group: "Advanced", visible: false, data: { key: "generation.resolve", label: "Resolve specification", description: "Brief와 Format을 실행 명세로 해석", icon: "resolve", kind: "logic", inputTypes: ["Text", "FormatProfile"], outputType: "GenerationSpec", model: "local.policy", cost: "$0.00" } },
  { id: "script", label: "Generate script", group: "Advanced", visible: false, data: { key: "script.generate", label: "Script generator", description: "연결된 Prompt로 내레이션 대본 생성", icon: "script", kind: "generate", inputTypes: ["Prompt", "GenerationSpec"], requiredInputTypes: ["Prompt"], outputType: "Script", provider: "google", model: "text.quality", cost: "$0.06" } },
  { id: "fit-script", label: "Fit duration", group: "Advanced", visible: false, data: { key: "script.fit_duration", label: "Fit script duration", description: "목표 길이에 맞춰 발화 시간을 보정", icon: "script", kind: "logic", inputTypes: ["Script"], outputType: "Script", model: "local.script-fit", cost: "$0.00" } },
  { id: "shot-plan", label: "Shot planner", group: "Advanced", visible: false, data: { key: "shot.plan", label: "Plan shots", description: "4·6·8초 단위의 Shot Plan", icon: "shot", kind: "logic", inputTypes: ["Script"], outputType: "ShotPlan", model: "local.shot-plan", cost: "$0.00" } },
  { id: "candidate", label: "Candidate select", group: "Advanced", visible: false, data: { key: "candidate.select", label: "Choose candidate", description: "연결된 실제 Video 후보 중 하나를 선택", icon: "select", kind: "review", inputTypes: ["Video"], requiredInputTypes: ["Video"], multiInputTypes: ["Video"], outputType: "Video" } },
  { id: "subtitle", label: "Speech subtitles", group: "Advanced", visible: false, data: { key: "subtitle.align", label: "Speech subtitles", description: "Chirp 3 음성인식 타임스탬프로 SRT 자막 생성", icon: "subtitle", kind: "compose", inputTypes: ["Audio"], requiredInputTypes: ["Audio"], outputType: "Subtitle", model: "google.stt.default", cost: "$0.00", sourceLanguage: "auto" } },
  { id: "timeline", label: "Compose timeline", group: "Advanced", visible: false, data: { key: "timeline.compose", label: "Compose timeline", description: "입력 Artifact를 참조하는 Timeline JSON", icon: "timeline", kind: "compose", inputTypes: ["Video", "Subtitle"], outputType: "Timeline", model: "local.timeline" } },
  { id: "render", label: "Render video", group: "Advanced", visible: false, data: { key: "video.render", label: "Render final MP4", description: "FFmpeg H.264 · AAC render", icon: "render", kind: "compose", inputTypes: ["Timeline"], outputType: "Video", model: "local.ffmpeg", cost: "$0.00" } },
  { id: "qc", label: "Quality control", group: "Advanced", visible: false, data: { key: "media.qc", label: "Quality control", description: "ffprobe 기반 Codec·Pixel Format·Audio·Duration 검사", icon: "qc", kind: "review", inputTypes: ["Video"], outputType: "QCReport", model: "local.ffprobe", cost: "$0.00" } },
];

export const inputHandleId = (type: PortType, index: number) => `input-${type}-${index}`;

export function createNodeFromTemplate(templateId: string, position: XYPosition, sequence: number): StudioFlowNode | null {
  const template = nodeTemplates.find((item) => item.id === templateId);
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

export function isConnectionCompatible(connection: Pick<Edge, "source" | "target" | "targetHandle">, nodes: StudioFlowNode[]): boolean {
  if (connection.source === connection.target) return false;
  const source = nodes.find((node) => node.id === connection.source);
  const target = nodes.find((node) => node.id === connection.target);
  if (!source || !target || !source.data.outputType) return false;
  const input = targetType(connection, target);
  return input === "Any" || source.data.outputType === input;
}

export function validateGraph(nodes: StudioFlowNode[], edges: Edge[]): string[] {
  const errors: string[] = [];
  if (!nodes.length) return ["그래프에 노드가 없습니다."];
  for (const edge of edges) {
    if (!isConnectionCompatible(edge, nodes)) errors.push(`호환되지 않는 연결: ${edge.source} → ${edge.target}`);
  }
  for (const node of nodes) {
    const allInputs = node.data.inputTypes ?? [];
    const requiredInputs = node.data.requiredInputTypes ?? (node.data.inputsRequired === false ? [] : allInputs);
    for (const type of requiredInputs) {
      const index = allInputs.indexOf(type);
      const connected = edges.some((edge) => edge.target === node.id && (edge.targetHandle === inputHandleId(type, index) || (!edge.targetHandle && node.data.inputTypes?.length === 1)));
      if (!connected) errors.push(`${node.data.label}: ${type} 입력이 필요합니다.`);
      const inputEdge = edges.find((edge) => edge.target === node.id && (edge.targetHandle === inputHandleId(type, index) || (!edge.targetHandle && node.data.inputTypes?.length === 1)));
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
  const requiredInputs = node.data.requiredInputTypes ?? (node.data.inputsRequired === false ? [] : allInputs);
  for (const type of requiredInputs) {
    const index = allInputs.indexOf(type);
    const matchingEdges = edges.filter((candidate) => candidate.target === node.id && (candidate.targetHandle === inputHandleId(type, index) || (!candidate.targetHandle && node.data.inputTypes?.length === 1)));
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
    if (["prompt.input", "asset.select", "utility.text"].includes(node.data.key)) {
      return { ...node, data: { ...node.data, status: node.data.configText?.trim() ? "SUCCEEDED" : "READY" } };
    }
    if (["RUNNING", "SUCCEEDED", "WAITING_INPUT", "FAILED"].includes(node.data.status)) return node;
    const ready = !stepInputError(node, nodes, edges);
    return { ...node, data: { ...node.data, status: ready ? "READY" : "BLOCKED" } };
  });
}

export function graphCost(nodes: StudioFlowNode[]): number {
  return nodes.reduce((sum, node) => sum + Number(node.data.cost?.replace("$", "") || 0), 0);
}
