import type { Edge, Node, XYPosition } from "@xyflow/react";
import type { NodeStatus, PortType } from "./types";

export type NodeKind = "input" | "logic" | "generate" | "compose" | "review";
export type ProviderName = "google" | "openai" | "xai" | "fal";
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
  frameCount?: number;
  sampleFps?: number;
  faceCoverage?: number;
  poseCoverage?: number;
  leftHandCoverage?: number;
  rightHandCoverage?: number;
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
  outputEdited?: boolean;
  lastExperimentId?: string;
  outputArtifactIds?: string[];
  lastRequestHash?: string;
  executionMode?: string;
  lastCostUsd?: number;
  runProgress?: number;
  skillId?: string;
  promptEdited?: boolean;
  resolution?: string;
  aspectRatio?: string;
  batchSize?: number;
  characterName?: string;
  shotCount?: number;
  durationSeconds?: number;
  loraUrl?: string;
  loraScale?: number;
  triggerWord?: string;
  contractVersion?: number;
  definitionDigest?: string;
  config?: Record<string, unknown>;
  executable?: boolean;
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
    characterName?: string;
    shotCount?: number;
    durationSeconds?: number;
    loraUrl?: string;
    loraScale?: number;
    triggerWord?: string;
    contractVersion?: number;
    definitionDigest?: string;
    config?: Record<string, unknown>;
    executable?: boolean;
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
    skillId?: string;
    stickyColor?: StickyColor;
    drawing?: DrawingDocument;
  };
}

export const nodeTemplates: NodeTemplate[] = [
  { id: "prompt", label: "Prompt", group: "Quick", data: { key: "prompt.input", label: "Prompt", description: "직접 입력하거나 상위 Prompt를 받아 이미지 참조와 함께 편집", icon: "brief", kind: "input", inputTypes: ["Prompt", "Image"], requiredInputTypes: [], multiInputTypes: ["Image"], outputType: "Prompt", configText: "", executable: false } },
  { id: "drawing-canvas", label: "Drawing Canvas", group: "Quick", data: { key: "utility.drawing", label: "Drawing canvas", description: "이미지를 배치하고 펜으로 지시사항을 표시", icon: "drawing", kind: "input", outputType: "Image", executable: false, drawing: { version: 1, width: 1280, height: 720, images: [], strokes: [] } } },
  { id: "image", label: "Image Generator", group: "Quick", data: { key: "image.generate", label: "Image generator", description: "연결된 Prompt로 이미지를 생성", icon: "image", kind: "generate", inputTypes: ["Prompt"], requiredInputTypes: ["Prompt"], outputType: "Image", provider: "google", model: "image.fast", cost: "$0.21", resolution: "2K", aspectRatio: "9:16", batchSize: 1 } },
  { id: "lora-image", label: "LoRA Image Generator", group: "Quick", data: { key: "lora.image.generate", label: "LoRA image generator", description: "학습 완료 Character 또는 FLUX.2 LoRA로 캐릭터가 고정된 이미지를 생성", icon: "lora", kind: "generate", inputTypes: ["Prompt", "Character"], requiredInputTypes: ["Prompt"], outputType: "Image", provider: "fal", model: "fal.image.flux2-lora", cost: "$0.07", resolution: "2K", aspectRatio: "9:16", batchSize: 1, loraUrl: "", loraScale: 0.9, triggerWord: "" } },
  { id: "character", label: "Character Generator", group: "Quick", data: { key: "character.generate", label: "Character generator", description: "Prompt 또는 기준 이미지에서 동일 캐릭터의 여러 단일 장면을 생성", icon: "character", kind: "generate", inputTypes: ["Prompt", "Image"], requiredInputTypes: [], multiInputTypes: ["Image"], outputType: "Character", provider: "google", model: "image.fast", cost: "$0.40", resolution: "2K", aspectRatio: "9:16", characterName: "New character", shotCount: 6 } },
  { id: "video", label: "Video Generator", group: "Quick", data: { key: "video.generate", label: "Video generator", description: "Prompt·Character·LoRA Image·Reference Video로 비디오를 생성", icon: "video", kind: "generate", inputTypes: ["Prompt", "Character", "Image", "Video"], requiredInputTypes: ["Prompt"], outputType: "Video", provider: "google", model: "video.omni", cost: "$1.40", resolution: "1080p", aspectRatio: "9:16", durationSeconds: 6, batchSize: 1 } },
  { id: "voice", label: "Voiceover", group: "Quick", data: { key: "tts.generate", label: "Voiceover", description: "연결된 Prompt를 음성으로 생성", icon: "voice", kind: "generate", inputTypes: ["Prompt"], requiredInputTypes: ["Prompt"], outputType: "Audio", provider: "google", model: "tts.fast", cost: "$0.12", resolution: "24kHz", aspectRatio: "Audio", batchSize: 1 } },
  { id: "assistant", label: "LLM Assistant", group: "Quick", data: { key: "llm.assistant", label: "LLM assistant", description: "연결된 Prompt를 분석·변환", icon: "assistant", kind: "generate", inputTypes: ["Prompt"], requiredInputTypes: ["Prompt"], outputType: "Text", provider: "google", model: "text.3.1-pro-preview", cost: "$0.03", contractVersion: 2 } },
  { id: "skill-executor", label: "Skill Executor", group: "Quick", data: { key: "skill.execute", label: "Skill executor", description: "프로젝트 Skill로 입력을 실행 가능한 Prompt로 변환", icon: "skill", kind: "generate", inputTypes: ["Prompt"], requiredInputTypes: ["Prompt"], outputType: "Prompt", provider: "google", model: "text.3.1-pro-preview", cost: "$0.03", skillId: "nottalggak-prompt-machine", contractVersion: 2 } },
  { id: "folder", label: "Folders", group: "Advanced", visible: false, data: { key: "folder.group", label: "Folder", description: "Canvas 노드를 시각적으로 정리", icon: "folder", kind: "input", configText: "New folder", executable: false } },

  { id: "upload", label: "Upload", group: "References", data: { key: "asset.upload", label: "Upload", description: "로컬 이미지·영상·오디오 업로드", icon: "upload", kind: "input", outputType: "ReferenceAsset", executable: false } },
  { id: "assets", label: "Assets", group: "References", data: { key: "asset.select", label: "Assets", description: "저장된 이미지·비디오·오디오를 Popover에서 선택", icon: "assets", kind: "input", outputType: "ReferenceAsset", configText: "", executable: false } },
  { id: "character-select", label: "Character", group: "References", data: { key: "character.select", label: "Character", description: "Characters 보관함에서 재사용할 캐릭터 묶음을 선택", icon: "character", kind: "input", outputType: "Character", configText: "", executable: false } },
  { id: "reference-analyzer", label: "Video Reference Analyzer", group: "References", data: { key: "reference.decompose", label: "Video reference analyzer", description: "STT·음악·컷·액션·화면 자막·효과음을 하나의 타임라인으로 분석", icon: "reference", kind: "logic", inputTypes: ["Video"], requiredInputTypes: ["Video"], outputType: "ReferenceAnalysis", model: "reference-analysis.pipeline.v1", cost: "$0.03", sourceLanguage: "auto", separateMusic: true, sceneThreshold: 0.28 } },
  { id: "motion-extractor", label: "Motion Extractor", group: "References", data: { key: "motion.extract", label: "Holistic motion extractor", description: "MediaPipe Holistic로 얼굴·포즈·양손 모션을 MotionTrack으로 추출", icon: "motion", kind: "logic", inputTypes: ["Video"], requiredInputTypes: ["Video"], outputType: "MotionTrack", model: "local.mediapipe.holistic", cost: "$0.00", motionSampleFps: 12, motionMaxWidth: 640, motionMinConfidence: 0.5, motionFaceBlendshapes: true } },

  { id: "image-category", label: "Image Generator", group: "Image", data: { key: "image.generate", label: "Image generator", description: "연결된 Prompt로 이미지를 생성", icon: "image", kind: "generate", inputTypes: ["Prompt"], requiredInputTypes: ["Prompt"], outputType: "Image", provider: "google", model: "image.fast", cost: "$0.21", resolution: "2K", aspectRatio: "9:16", batchSize: 1 } },
  { id: "lora-image-category", label: "LoRA Image Generator", group: "Image", data: { key: "lora.image.generate", label: "LoRA image generator", description: "학습 완료 Character 또는 FLUX.2 LoRA로 캐릭터가 고정된 이미지를 생성", icon: "lora", kind: "generate", inputTypes: ["Prompt", "Character"], requiredInputTypes: ["Prompt"], outputType: "Image", provider: "fal", model: "fal.image.flux2-lora", cost: "$0.07", resolution: "2K", aspectRatio: "9:16", batchSize: 1, loraUrl: "", loraScale: 0.9, triggerWord: "" } },
  { id: "character-category", label: "Character Generator", group: "Image", data: { key: "character.generate", label: "Character generator", description: "Prompt 또는 기준 이미지에서 동일 캐릭터의 여러 단일 장면을 생성", icon: "character", kind: "generate", inputTypes: ["Prompt", "Image"], requiredInputTypes: [], multiInputTypes: ["Image"], outputType: "Character", provider: "google", model: "image.fast", cost: "$0.40", resolution: "2K", aspectRatio: "9:16", characterName: "New character", shotCount: 6 } },
  { id: "video-category", label: "Video Generator", group: "Video", data: { key: "video.generate", label: "Video generator", description: "Prompt·Character·LoRA Image·Reference Video로 비디오를 생성", icon: "video", kind: "generate", inputTypes: ["Prompt", "Character", "Image", "Video"], requiredInputTypes: ["Prompt"], outputType: "Video", provider: "google", model: "video.omni", cost: "$1.40", resolution: "1080p", aspectRatio: "9:16", durationSeconds: 6, batchSize: 1 } },
  { id: "video-editor", label: "Video Editor", group: "Video", data: { key: "video.edit", label: "Video editor", description: "여러 Video를 연결 순서대로 합성하고 트랜지션·길이를 적용", icon: "timeline", kind: "compose", inputTypes: ["Video"], requiredInputTypes: ["Video"], multiInputTypes: ["Video"], outputType: "Video", model: "local.ffmpeg", cost: "$0.00", resolution: "1080p", aspectRatio: "9:16", transition: "hard_cut", targetDurationSeconds: 30 } },

  { id: "voice-category", label: "Voiceover", group: "Audio", data: { key: "tts.generate", label: "Voiceover", description: "연결된 Prompt를 음성으로 생성", icon: "voice", kind: "generate", inputTypes: ["Prompt"], requiredInputTypes: ["Prompt"], outputType: "Audio", provider: "google", model: "tts.fast", cost: "$0.12", resolution: "24kHz", aspectRatio: "Audio", batchSize: 1 } },
  { id: "audio-assets", label: "Audio Assets", group: "Audio", data: { key: "asset.select", label: "Audio assets", description: "Reference stem을 포함한 저장된 오디오를 선택", icon: "assets", kind: "input", outputType: "Audio", configText: "", executable: false } },
  { id: "change-voice", label: "Replace Audio", group: "Audio", data: { key: "video.change_voice", label: "Replace video audio", description: "Video의 기존 오디오를 연결된 Audio로 실제 교체", icon: "changeVoice", kind: "compose", inputTypes: ["Video", "Audio"], requiredInputTypes: ["Video", "Audio"], outputType: "Video", model: "local.ffmpeg", cost: "$0.00" } },
  { id: "translate", label: "Translate Video", group: "Audio", data: { key: "video.translate", label: "Translate video", description: "Chirp 3 음성인식·Gemini 번역·Gemini TTS로 영상 현지화", icon: "translate", kind: "compose", inputTypes: ["Video"], requiredInputTypes: ["Video"], outputType: "Video", model: "google.localization.pipeline", cost: "$0.35", sourceLanguage: "auto", targetLanguage: "ko-KR", voiceName: "Kore" } },

  { id: "text", label: "Text", group: "Utilities", visible: false, data: { key: "utility.text", label: "Text", description: "Legacy text note", icon: "text", kind: "input", outputType: "Text", configText: "", executable: false } },
  { id: "sticky", label: "Sticky Note", group: "Utilities", data: { key: "utility.sticky", label: "Sticky note", description: "실행과 무관한 Canvas 메모", icon: "sticky", kind: "input", configText: "", stickyColor: "yellow", executable: false } },

  { id: "brief", label: "Generation brief", group: "Advanced", visible: false, data: { key: "generation.brief", label: "Generation brief", description: "주제, 메시지, 시청자와 목표 길이", icon: "brief", kind: "input", outputType: "Text", configText: "", executable: false } },
  { id: "format", label: "Format profile", group: "Advanced", visible: false, data: { key: "format.profile", label: "Format profile", description: "생성에 사용할 FormatCoreV1", icon: "format", kind: "input", outputType: "FormatProfile", preview: "Select a format", executable: false } },
  { id: "resolve", label: "Resolve spec", group: "Advanced", visible: false, data: { key: "generation.resolve", label: "Resolve specification", description: "Brief와 Format을 실행 명세로 해석", icon: "resolve", kind: "logic", inputTypes: ["Text", "FormatProfile"], outputType: "GenerationSpec", model: "local.policy", cost: "$0.00" } },
  { id: "script", label: "Generate script", group: "Advanced", visible: false, data: { key: "script.generate", label: "Script generator", description: "연결된 Prompt로 내레이션 대본 생성", icon: "script", kind: "generate", inputTypes: ["Prompt", "GenerationSpec"], requiredInputTypes: ["Prompt"], outputType: "Script", provider: "google", model: "text.3.1-pro-preview", cost: "$0.06", contractVersion: 2 } },
  { id: "fit-script", label: "Fit duration", group: "Advanced", visible: false, data: { key: "script.fit_duration", label: "Fit script duration", description: "목표 길이에 맞춰 발화 시간을 보정", icon: "script", kind: "logic", inputTypes: ["Script"], outputType: "Script", model: "local.script-fit", cost: "$0.00" } },
  { id: "shot-plan", label: "Shot planner", group: "Advanced", visible: false, data: { key: "shot.plan", label: "Plan shots", description: "4·6·8초 단위의 Shot Plan", icon: "shot", kind: "logic", inputTypes: ["Script"], outputType: "ShotPlan", model: "local.shot-plan", cost: "$0.00" } },
  { id: "candidate", label: "Candidate select", group: "Advanced", visible: false, data: { key: "candidate.select", label: "Choose candidate", description: "연결된 실제 Video 후보 중 하나를 선택", icon: "select", kind: "review", inputTypes: ["Video"], requiredInputTypes: ["Video"], multiInputTypes: ["Video"], outputType: "Video" } },
  { id: "subtitle", label: "Speech subtitles", group: "Audio", data: { key: "subtitle.align", label: "Speech subtitles", description: "TTS Audio를 인식해 타임스탬프가 포함된 SRT 자막 생성", icon: "subtitle", kind: "compose", inputTypes: ["Audio"], requiredInputTypes: ["Audio"], outputType: "Subtitle", model: "google.stt.default", cost: "$0.00", sourceLanguage: "auto" } },
  { id: "timeline", label: "Caption layout", group: "Video", data: { key: "timeline.compose", label: "Caption layout", description: "영상 위에서 자막을 드래그하고 위치·정렬을 저장", icon: "timeline", kind: "compose", inputTypes: ["Video", "Subtitle"], requiredInputTypes: ["Video", "Subtitle"], outputType: "Timeline", model: "local.timeline", captionX: 0.5, captionY: 0.82, captionAlign: "center", captionFontSize: 54, waitForInput: true } },
  { id: "render", label: "Render captions", group: "Video", data: { key: "video.render", label: "Render captioned video", description: "설정한 위치의 자막을 영상에 렌더", icon: "render", kind: "compose", inputTypes: ["Timeline"], requiredInputTypes: ["Timeline"], outputType: "Video", model: "local.ffmpeg", cost: "$0.00" } },
  { id: "qc", label: "Quality control", group: "Advanced", visible: false, data: { key: "media.qc", label: "Quality control", description: "ffprobe 기반 Codec·Pixel Format·Audio·Duration 검사", icon: "qc", kind: "review", inputTypes: ["Video"], outputType: "QCReport", model: "local.ffprobe", cost: "$0.00" } },
];

export const inputHandleId = (type: PortType, index: number) => `input-${type}-${index}`;

export function createNodeFromTemplate(templateId: string, position: XYPosition, sequence: number, templates: NodeTemplate[] = nodeTemplates): StudioFlowNode | null {
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
    if (node.data.key === "lora.image.generate" && !node.data.loraUrl?.trim()) {
      const characterIndex = allInputs.indexOf("Character");
      const hasCharacter = edges.some((edge) => edge.target === node.id && edge.targetHandle === inputHandleId("Character", characterIndex));
      if (!hasCharacter) errors.push(`${node.data.label}: LoRA weights URL 또는 학습 완료 Character 입력이 필요합니다.`);
    }
    if (node.data.key === "character.generate") {
      const hasCharacterSource = edges.some((edge) => edge.target === node.id && ["Prompt", "Image"].some((type) => {
        const index = allInputs.indexOf(type as PortType);
        return edge.targetHandle === inputHandleId(type as PortType, index);
      }));
      if (!hasCharacterSource) errors.push(`${node.data.label}: Prompt 또는 Image 입력이 필요합니다.`);
    }
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
  if (node.data.key === "lora.image.generate" && !node.data.loraUrl?.trim()) {
    const characterIndex = allInputs.indexOf("Character");
    const characterEdge = edges.find((edge) => edge.target === node.id && edge.targetHandle === inputHandleId("Character", characterIndex));
    const characterSource = nodes.find((candidate) => candidate.id === characterEdge?.source);
    if (!characterSource) return "LoRA weights URL 또는 학습 완료 Character를 연결하세요.";
    if (characterSource.data.status !== "SUCCEEDED") return "연결된 Character Step을 먼저 준비하세요.";
  }
  if (node.data.key === "character.generate") {
    const candidateEdges = edges.filter((edge) => edge.target === node.id && ["Prompt", "Image"].some((type) => {
      const index = allInputs.indexOf(type as PortType);
      return edge.targetHandle === inputHandleId(type as PortType, index);
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
    if (node.data.key === "utility.drawing") {
      return { ...node, data: { ...node.data, status: node.data.output ? "SUCCEEDED" : "READY" } };
    }
    if (["prompt.input", "asset.select", "character.select", "utility.sticky"].includes(node.data.key)) {
      return { ...node, data: { ...node.data, status: node.data.configText?.trim() ? "SUCCEEDED" : "READY" } };
    }
    if (node.data.status === "STALE" && (node.data.output || node.data.outputArtifactIds?.length)) return node;
    if (["RUNNING", "SUCCEEDED", "WAITING_INPUT", "FAILED"].includes(node.data.status)) return node;
    const ready = !stepInputError(node, nodes, edges);
    return { ...node, data: { ...node.data, status: ready ? "READY" : "BLOCKED" } };
  });
}

export function graphCost(nodes: StudioFlowNode[]): number {
  return nodes.reduce((sum, node) => sum + Number(node.data.cost?.replace("$", "") || 0), 0);
}
