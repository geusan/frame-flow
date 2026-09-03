import type { ReactNode } from "react";
import type { Edge } from "@xyflow/react";
import { ChevronRight, Play } from "lucide-react";

import { Button } from "@/components/ui/button";
import { NativeSelect } from "@/components/ui/native-select";
import { CaptionLayoutEditor } from "@/features/workflows/components/caption-layout-editor";
import type { RichCaptionDocument } from "@/features/workflows/rich-caption";
import { HolisticMotionPreview } from "@/features/workflows/components/holistic-motion-preview";
import { inputHandleId, type CanvasOutput, type StudioFlowNode } from "@/lib/canvas-model";
import { API_BASE, type ModelRecord, type NodeDefinitionRecord, type ProjectSkillRecord } from "@/lib/api";
import { maximizePlaybackVolume } from "@/lib/media";
import { modelOptionsForDefinition, providerForModelAlias, providerOptionsForDefinition } from "@/features/nodes/model-options";
import { FrameLayoutEditor, ImageMotionEditor, SubtitleRegionEditor } from "@/features/nodes/custom-editors/sro-video-editors";

export interface NodeCustomEditorProps {
  node: StudioFlowNode;
  definition: NodeDefinitionRecord;
  nodes: StudioFlowNode[];
  edges: Edge[];
  models: ModelRecord[];
  projectSkills: ProjectSkillRecord[];
  activeCanvasRunId: string | null;
  onChange: (patch: Partial<StudioFlowNode["data"]>) => void;
  onApproveCaptionLayout: () => void;
  onOpenCandidate: () => void;
}

function configValue<T>(node: StudioFlowNode, key: string, legacyValue: T | undefined, fallback: T): T {
  return (node.data.config?.[key] ?? legacyValue ?? fallback) as T;
}

function updateConfig(
  props: NodeCustomEditorProps,
  key: string,
  value: string | number | boolean,
  legacyPatch: Partial<StudioFlowNode["data"]> = {},
) {
  props.onChange({
    ...legacyPatch,
    config: { ...(props.node.data.config ?? {}), [key]: value },
  });
}

function promptOutputText(node: StudioFlowNode | undefined): string {
  if (!node) return "";
  if (node.data.output?.kind === "text" && node.data.output.text?.trim()) return node.data.output.text.trim();
  return node.data.configText?.trim() ?? "";
}

export function ConnectedPromptPreview({ node, definition, nodes, edges }: Pick<NodeCustomEditorProps, "node" | "definition" | "nodes" | "edges">) {
  const promptPort = definition.ports.inputs.find((port) => port.type === "prompt.text.v1");
  if (!promptPort) return null;
  const promptIndex = node.data.inputTypes?.indexOf("Prompt") ?? -1;
  const promptEdge = promptIndex < 0 ? undefined : edges.find((edge) => edge.target === node.id && edge.targetHandle === inputHandleId("Prompt", promptIndex));
  const prompt = promptOutputText(nodes.find((candidate) => candidate.id === promptEdge?.source));
  const acceptsImageWithoutPrompt = !promptPort.required && definition.ports.inputs.some((port) => port.type === "media.image.v1");
  return <div className={`connected-prompt-preview ${prompt || acceptsImageWithoutPrompt ? "connected" : "missing"}`}>
    <span>Connected prompt</span>
    <p>{prompt || (acceptsImageWithoutPrompt ? "Image-only mode · 연결된 기준 이미지를 canonical identity로 사용합니다." : "Prompt 노드를 연결하고 내용을 입력하세요.")}</p>
  </div>;
}

export function ProviderModelFields({ node, definition, models, onChange }: Pick<NodeCustomEditorProps, "node" | "definition" | "models" | "onChange">) {
  const compatibleModels = modelOptionsForDefinition(definition, models, node.data.model);
  if (!compatibleModels.length) return null;
  const providers = providerOptionsForDefinition(definition, models, node.data.model);
  const modelProvider = compatibleModels.find((option) => option.value === node.data.model)?.provider;
  const inferredProvider = modelProvider ?? node.data.provider ?? providerForModelAlias(node.data.model) ?? providers[0]?.value ?? definition.execution.provider;
  const provider = providers.some((option) => option.value === inferredProvider) ? inferredProvider : providers[0]?.value ?? inferredProvider;
  const providerModels = compatibleModels.filter((option) => option.provider === provider);
  const model = providerModels.some((option) => option.value === node.data.model) ? node.data.model ?? "" : providerModels[0]?.value ?? "";
  const updateModel = (nextProvider: string, nextModel: string | undefined) => {
    if (!nextModel) return;
    const configPatch = definition.config_schema.properties.model_alias
      ? { config: { ...(node.data.config ?? {}), model_alias: nextModel } }
      : {};
    onChange({ provider: nextProvider, model: nextModel, ...configPatch });
  };

  return <div className="generator-setting-grid provider-model-selectors">
    <label><span>Provider</span><NativeSelect value={provider} onChange={(event) => { const nextProvider = event.target.value; updateModel(nextProvider, compatibleModels.find((option) => option.provider === nextProvider)?.value); }}>{providers.map((option) => <option value={option.value} key={option.value}>{option.label}</option>)}</NativeSelect></label>
    <label><span>Model</span><NativeSelect value={model} onChange={(event) => updateModel(provider, event.target.value)}>{providerModels.map((option) => <option value={option.value} key={option.value}>{option.label}{option.configurationKnown && !option.configured ? " · setup needed" : ""}</option>)}</NativeSelect></label>
  </div>;
}

function ProviderGenerationEditor(props: NodeCustomEditorProps) {
  const { node, definition, projectSkills } = props;
  const properties = definition.config_schema.properties;
  const selectedSkill = node.data.skillId ? projectSkills.find((skill) => skill.id === node.data.skillId) : undefined;
  const resolutionField = properties.resolution;
  const aspectRatioField = properties.aspect_ratio;
  const durationField = properties.duration_seconds;
  const shotCountField = properties.shot_count;

  return <div className="generator-settings">
    <ConnectedPromptPreview {...props} />
    {properties.skill_id && <label className="field-label"><span>Project skill</span><NativeSelect value={configValue(node, "skill_id", node.data.skillId, "")} onChange={(event) => updateConfig(props, "skill_id", event.target.value, { skillId: event.target.value })}>
      {!projectSkills.length && <option value={node.data.skillId ?? "nottalggak-prompt-machine"}>{node.data.skillId ?? "nottalggak-prompt-machine"}</option>}
      {projectSkills.map((skill) => <option value={skill.id} key={skill.id}>{skill.display_name}</option>)}
    </NativeSelect><small>{selectedSkill?.description ?? "API에서 프로젝트 Skill 레지스트리를 불러옵니다."}</small></label>}
    {properties.character_name && shotCountField && <div className="generator-setting-grid">
      <label><span>Character name</span><input value={configValue(node, "character_name", node.data.characterName, "New character")} onChange={(event) => updateConfig(props, "character_name", event.target.value, { characterName: event.target.value })} /></label>
      <label><span>Generated views</span><NativeSelect value={String(configValue(node, "shot_count", node.data.shotCount, 6))} onChange={(event) => updateConfig(props, "shot_count", Number(event.target.value), { shotCount: Number(event.target.value) })}>{(shotCountField.enum ?? [4, 6, 8]).map((value) => <option value={String(value)} key={String(value)}>{value} views</option>)}</NativeSelect></label>
    </div>}
    {properties.lora_url && <div className="lora-generator-settings">
      <label className="field-label"><span>LoRA weights <em>optional with Character input</em></span><input value={configValue(node, "lora_url", node.data.loraUrl, "")} placeholder="https://…/character_lora.safetensors or HF repo ID" onChange={(event) => updateConfig(props, "lora_url", event.target.value, { loraUrl: event.target.value })} /><small>학습 완료 Character를 연결하면 저장된 weights와 trigger word를 자동 사용합니다.</small></label>
      <div className="generator-setting-grid">
        <label><span>Trigger word</span><input value={configValue(node, "trigger_word", node.data.triggerWord, "")} placeholder="mori_catgirl_v1" onChange={(event) => updateConfig(props, "trigger_word", event.target.value, { triggerWord: event.target.value })} /></label>
        <label><span>LoRA scale</span><input type="number" min="0" max="2" step="0.05" value={configValue(node, "lora_scale", node.data.loraScale, 0.9)} onChange={(event) => updateConfig(props, "lora_scale", Number(event.target.value), { loraScale: Number(event.target.value) })} /></label>
      </div>
    </div>}
    <ProviderModelFields {...props} />
    {resolutionField && aspectRatioField && <div className="generator-setting-grid">
      <label><span>Resolution</span><NativeSelect value={configValue(node, "resolution", node.data.resolution, String(resolutionField.default ?? "1080p"))} onChange={(event) => updateConfig(props, "resolution", event.target.value, { resolution: event.target.value })}>{(resolutionField.enum ?? [String(resolutionField.default ?? "1080p")]).map((value) => <option value={String(value)} key={String(value)}>{String(value)}</option>)}</NativeSelect></label>
      <label><span>Aspect ratio</span><NativeSelect value={configValue(node, "aspect_ratio", node.data.aspectRatio, String(aspectRatioField.default ?? "9:16"))} onChange={(event) => updateConfig(props, "aspect_ratio", event.target.value, { aspectRatio: event.target.value })}>{(aspectRatioField.enum ?? [String(aspectRatioField.default ?? "9:16")]).map((value) => <option value={String(value)} key={String(value)}>{String(value)}</option>)}</NativeSelect></label>
    </div>}
    {durationField && <label className="field-label"><span>Shot duration</span><NativeSelect value={String(configValue(node, "duration_seconds", node.data.durationSeconds, Number(durationField.default ?? 6)))} onChange={(event) => updateConfig(props, "duration_seconds", Number(event.target.value), { durationSeconds: Number(event.target.value) })}>{(durationField.enum ?? [4, 6, 8]).map((value) => <option value={String(value)} key={String(value)}>{value} seconds</option>)}</NativeSelect><small>Manifest가 허용한 영상 길이만 선택할 수 있습니다.</small></label>}
    {properties.output_count && <div className="batch-setting single-output-setting"><span><small>Output count</small><strong>Canvas Step은 단일 결과를 출력합니다.</strong></span><b>1</b></div>}
  </div>;
}

function VideoEditor(props: NodeCustomEditorProps) {
  const { node, nodes, edges, definition } = props;
  const videoInputCount = edges.filter((edge) => edge.target === node.id && nodes.find((candidate) => candidate.id === edge.source)?.data.outputType === "Video").length;
  const aspectRatioField = definition.config_schema.properties.aspect_ratio;
  return <div className="video-editor-settings">
    <div className={`editor-input-count ${videoInputCount ? "connected" : "missing"}`}><span>Connected videos</span><strong>{videoInputCount}</strong><small>{videoInputCount ? "여러 입력은 연결 순서대로 편집됩니다." : "Video 출력들을 왼쪽 입력 포트에 연결하세요."}</small></div>
    <label className="field-label"><span>Transition</span><NativeSelect value={configValue(node, "transition", node.data.transition, "hard_cut")} onChange={(event) => updateConfig(props, "transition", event.target.value, { transition: event.target.value })}><option value="hard_cut">Hard cut</option><option value="crossfade">Crossfade</option><option value="dip_to_black">Dip to black</option></NativeSelect></label>
    <div className="generator-setting-grid">
      <label><span>Output ratio</span><NativeSelect value={configValue(node, "aspect_ratio", node.data.aspectRatio, "9:16")} onChange={(event) => updateConfig(props, "aspect_ratio", event.target.value, { aspectRatio: event.target.value })}>{(aspectRatioField?.enum ?? ["9:16", "16:9", "1:1"]).map((value) => <option value={String(value)} key={String(value)}>{value}</option>)}</NativeSelect></label>
      <label><span>Target length</span><NativeSelect value={String(configValue(node, "target_duration_seconds", node.data.targetDurationSeconds, 30))} onChange={(event) => updateConfig(props, "target_duration_seconds", Number(event.target.value), { targetDurationSeconds: Number(event.target.value) })}><option value="15">15s</option><option value="30">30s</option><option value="45">45s</option><option value="60">60s</option></NativeSelect></label>
    </div>
  </div>;
}

function CaptionLayoutCustomEditor(props: NodeCustomEditorProps) {
  const { node, nodes, edges, activeCanvasRunId } = props;
  const connected = nodes.filter((candidate) => edges.some((edge) => edge.source === candidate.id && edge.target === node.id));
  const video = connected.find((candidate) => candidate.data.outputType === "Video");
  const subtitle = connected.find((candidate) => candidate.data.outputType === "Subtitle");
  return <div className="caption-layout-settings">
    <div className={`editor-input-count ${video?.data.output?.url ? "connected" : "missing"}`}><span>Caption canvas</span><strong>{video?.data.output?.url ? "✓" : "—"}</strong><small>{video?.data.output?.url ? "영상 위 자막을 드래그해 위치를 조정하세요." : "Video와 Subtitle 출력을 연결하면 편집할 수 있습니다."}</small></div>
    <CaptionLayoutEditor
      videoUrl={video?.data.output?.kind === "video" ? video.data.output.url : undefined}
      videoMimeType={video?.data.output?.mimeType}
      subtitleText={subtitle?.data.output?.text}
      richText={props.definition.contract_version >= 2}
      captionDocument={configValue<RichCaptionDocument | undefined>(node, "caption_document", undefined, undefined)}
      value={{
        x: configValue(node, "caption_x", node.data.captionX, 0.5),
        y: configValue(node, "caption_y", node.data.captionY, 0.82),
        align: configValue(node, "caption_align", node.data.captionAlign, "center"),
        fontSize: configValue(node, "caption_font_size", node.data.captionFontSize, 54),
      }}
      onChange={(layout) => props.onChange({
        captionX: layout.x,
        captionY: layout.y,
        captionAlign: layout.align,
        captionFontSize: layout.fontSize,
        config: { ...(node.data.config ?? {}), caption_x: layout.x, caption_y: layout.y, caption_align: layout.align, caption_font_size: layout.fontSize },
      })}
      onCaptionDocumentChange={(captionDocument) => props.onChange({
        config: { ...(node.data.config ?? {}), caption_document: captionDocument },
      })}
    />
    {node.data.status === "WAITING_INPUT" && activeCanvasRunId && <Button className="caption-workflow-continue" type="button" onClick={props.onApproveCaptionLayout}><Play size={14} fill="currentColor" /> 위치 확정하고 워크플로우 계속</Button>}
  </div>;
}

function SubtitleDesignCustomEditor(props: NodeCustomEditorProps) {
  const { node, nodes, edges, activeCanvasRunId } = props;
  const subtitle = nodes.find((candidate) => edges.some((edge) => edge.source === candidate.id && edge.target === node.id) && candidate.data.outputType === "Subtitle");
  const captionDocument = configValue<RichCaptionDocument | undefined>(node, "caption_document", undefined, undefined);
  return <div className="caption-layout-settings subtitle-design-settings">
    <div className={`editor-input-count ${subtitle?.data.output?.text ? "connected" : "missing"}`}>
      <span>Single responsibility</span><strong>Rich text</strong>
      <small>{subtitle?.data.output?.text ? "타임코드는 유지하고 자막 내용과 글자별 Style만 편집합니다." : "Timed Subtitle 출력을 연결하면 TipTap 문서를 만들 수 있습니다."}</small>
    </div>
    <CaptionLayoutEditor
      subtitleText={subtitle?.data.output?.text}
      richText
      layoutControls={false}
      captionDocument={captionDocument}
      value={{ x: 0.5, y: 0.82, align: "center", fontSize: Number(captionDocument?.default_style.font_size ?? 54) }}
      onChange={() => undefined}
      onCaptionDocumentChange={(document) => props.onChange({
        config: { ...(node.data.config ?? {}), caption_document: document },
      })}
    />
    {node.data.status === "WAITING_INPUT" && activeCanvasRunId && <Button className="caption-workflow-continue" type="button" onClick={props.onApproveCaptionLayout}><Play size={14} fill="currentColor" /> 자막 문서 확정하고 계속</Button>}
  </div>;
}

const languageOptions = [
  ["auto", "Auto detect"], ["ko-KR", "Korean"], ["en-US", "English"], ["ja-JP", "Japanese"], ["zh-CN", "Chinese"], ["es-ES", "Spanish"],
] as const;

function VideoTranslateEditor(props: NodeCustomEditorProps) {
  const { node } = props;
  return <div className="video-editor-settings">
    <div className="editor-input-count connected"><span>Live pipeline</span><strong>3</strong><small>Chirp 3 STT → Gemini translation → Gemini TTS</small></div>
    <div className="generator-setting-grid">
      <label><span>Source language</span><NativeSelect value={configValue(node, "source_language", node.data.sourceLanguage, "auto")} onChange={(event) => updateConfig(props, "source_language", event.target.value, { sourceLanguage: event.target.value })}>{languageOptions.map(([value, label]) => <option value={value} key={value}>{label}</option>)}</NativeSelect></label>
      <label><span>Target language</span><NativeSelect value={configValue(node, "target_language", node.data.targetLanguage, "ko-KR")} onChange={(event) => updateConfig(props, "target_language", event.target.value, { targetLanguage: event.target.value })}>{languageOptions.filter(([value]) => value !== "auto").map(([value, label]) => <option value={value} key={value}>{label}</option>)}</NativeSelect></label>
    </div>
    <label className="field-label"><span>Gemini voice</span><NativeSelect value={configValue(node, "voice_name", node.data.voiceName, "Kore")} onChange={(event) => updateConfig(props, "voice_name", event.target.value, { voiceName: event.target.value })}><option value="Kore">Kore</option><option value="Aoede">Aoede</option><option value="Charon">Charon</option><option value="Puck">Puck</option></NativeSelect><small>Google Cloud ADC와 Speech-to-Text·Vertex AI 권한이 필요합니다.</small></label>
  </div>;
}

interface ReferenceAnalysisManifest {
  schema_version: "reference.decomposition.v1";
  source: { duration_ms: number; has_audio: boolean };
  speech: { language_code?: string; text: string; segments: Array<{ start_ms: number; end_ms: number; text: string }> };
  audio: { music_intervals: Array<{ start_ms: number; end_ms: number; label: string }>; sound_effects: Array<{ start_ms: number; end_ms: number; label: string }>; separation: { status: string } };
  visual: { shots: Array<{ index: number; start_ms: number; end_ms: number; transition_in: string }>; actions: Array<{ start_ms: number; end_ms: number; label: string }>; text_tracks: Array<{ start_ms: number; end_ms: number; text: string; kind: string; movement: string }> };
  artifacts: Record<string, string>;
  quality: { completeness: "complete" | "partial"; warnings: string[] };
}

function referenceAnalysisFromOutput(output?: CanvasOutput): ReferenceAnalysisManifest | null {
  if (output?.kind !== "json" || !output.text) return null;
  try {
    const parsed = JSON.parse(output.text) as Partial<ReferenceAnalysisManifest>;
    return parsed.schema_version === "reference.decomposition.v1" ? parsed as ReferenceAnalysisManifest : null;
  } catch {
    return null;
  }
}

function analysisTime(milliseconds: number): string {
  const totalSeconds = Math.max(0, Math.floor(milliseconds / 1000));
  return `${Math.floor(totalSeconds / 60)}:${(totalSeconds % 60).toString().padStart(2, "0")}`;
}

function ReferenceAnalysisResult({ analysis }: { analysis: ReferenceAnalysisManifest }) {
  const lanes = [
    { label: "Speech", events: analysis.speech.segments.map((event) => ({ ...event, label: event.text })) },
    { label: "Shots", events: analysis.visual.shots.map((event) => ({ ...event, label: `Shot ${event.index + 1} · ${event.transition_in}` })) },
    { label: "Actions", events: analysis.visual.actions },
    { label: "Captions", events: analysis.visual.text_tracks.map((event) => ({ ...event, label: event.text })) },
    { label: "Music", events: analysis.audio.music_intervals },
    { label: "SFX", events: analysis.audio.sound_effects },
  ];
  const stems = [["audio_mix", "Original mix"], ["vocals", "Vocals"], ["accompaniment", "Accompaniment"]] as const;
  return <div className="reference-analysis-inspector">
    <div className="reference-analysis-result-head"><span><small>Analysis result</small><strong>{analysis.quality.completeness === "complete" ? "Complete" : "Partial"}</strong></span><b>{analysisTime(analysis.source.duration_ms)}</b></div>
    <div className="reference-analysis-counts"><span><b>{analysis.speech.segments.length}</b><small>Speech</small></span><span><b>{analysis.visual.shots.length}</b><small>Shots</small></span><span><b>{analysis.visual.actions.length}</b><small>Actions</small></span><span><b>{analysis.visual.text_tracks.length}</b><small>Text</small></span><span><b>{analysis.audio.music_intervals.length}</b><small>Music</small></span><span><b>{analysis.audio.sound_effects.length}</b><small>SFX</small></span></div>
    <div className="reference-analysis-timeline">{lanes.map((lane) => <div className="reference-analysis-lane" key={lane.label}><strong>{lane.label}</strong><span>{lane.events.length ? lane.events.slice(0, 4).map((event, index) => <i key={`${event.start_ms}-${index}`} title={event.label}>{analysisTime(event.start_ms)} {event.label}</i>) : <em>None</em>}</span></div>)}</div>
    {stems.some(([key]) => analysis.artifacts[key]) && <div className="reference-analysis-stems"><strong>Audio stems</strong>{stems.map(([key, label]) => analysis.artifacts[key] && <label key={key}><span>{label}</span><audio controls preload="none" src={`${API_BASE}/artifacts/${analysis.artifacts[key]}/content`} onPlay={(event) => maximizePlaybackVolume(event.currentTarget)} /></label>)}</div>}
    {!!analysis.quality.warnings.length && <div className="reference-analysis-warnings">{analysis.quality.warnings.map((warning) => <p key={warning}>{warning}</p>)}</div>}
  </div>;
}

function ReferenceAnalysisEditor(props: NodeCustomEditorProps) {
  const { node } = props;
  const analysis = referenceAnalysisFromOutput(node.data.output);
  return <div className="reference-analysis-settings">
    <div className="editor-input-count connected"><span>Composite analysis</span><strong>6</strong><small>STT · music · shots · actions · on-screen text · SFX</small></div>
    <div className="generator-setting-grid">
      <label><span>Speech language</span><NativeSelect value={configValue(node, "source_language", node.data.sourceLanguage, "auto")} onChange={(event) => updateConfig(props, "source_language", event.target.value, { sourceLanguage: event.target.value })}>{languageOptions.map(([value, label]) => <option value={value} key={value}>{label}</option>)}</NativeSelect></label>
      <label><span>Scene sensitivity</span><NativeSelect value={String(configValue(node, "scene_threshold", node.data.sceneThreshold, 0.28))} onChange={(event) => updateConfig(props, "scene_threshold", Number(event.target.value), { sceneThreshold: Number(event.target.value) })}><option value="0.18">High</option><option value="0.28">Balanced</option><option value="0.4">Low</option></NativeSelect></label>
    </div>
    <label className="reference-analysis-toggle"><input type="checkbox" checked={configValue(node, "separate_music", node.data.separateMusic, true)} onChange={(event) => updateConfig(props, "separate_music", event.target.checked, { separateMusic: event.target.checked })} /><span><strong>Create music stems</strong><small>Demucs가 있으면 vocals와 accompaniment WAV를 생성합니다.</small></span></label>
    {analysis && <ReferenceAnalysisResult analysis={analysis} />}
  </div>;
}

function MotionExtractorEditor(props: NodeCustomEditorProps) {
  const { node, nodes, edges } = props;
  const video = nodes.find((candidate) => candidate.data.outputType === "Video" && edges.some((edge) => edge.source === candidate.id && edge.target === node.id));
  const sampleFps = configValue(node, "motion_sample_fps", node.data.motionSampleFps, 12);
  const minConfidence = configValue(node, "motion_min_confidence", node.data.motionMinConfidence, 0.5);
  return <div className="motion-extractor-settings">
    <div className="generator-setting-grid">
      <label><span>Sample rate</span><NativeSelect value={String(sampleFps)} onChange={(event) => updateConfig(props, "motion_sample_fps", Number(event.target.value), { motionSampleFps: Number(event.target.value) })}><option value="6">6 fps</option><option value="12">12 fps</option><option value="24">24 fps</option></NativeSelect></label>
      <label><span>Confidence</span><NativeSelect value={String(minConfidence)} onChange={(event) => updateConfig(props, "motion_min_confidence", Number(event.target.value), { motionMinConfidence: Number(event.target.value) })}><option value="0.35">Sensitive</option><option value="0.5">Balanced</option><option value="0.65">Strict</option></NativeSelect></label>
    </div>
    <label className="reference-analysis-toggle"><input type="checkbox" checked={configValue(node, "motion_face_blendshapes", node.data.motionFaceBlendshapes, true)} onChange={(event) => updateConfig(props, "motion_face_blendshapes", event.target.checked, { motionFaceBlendshapes: event.target.checked })} /><span><strong>Face blendshapes</strong><small>눈 깜빡임·입·표정 계수를 MotionTrack에 포함합니다.</small></span></label>
    <HolisticMotionPreview videoUrl={video?.data.output?.url} sampleFps={Math.min(12, sampleFps)} minConfidence={minConfidence} />
  </div>;
}

function CandidateEditor({ onOpenCandidate }: NodeCustomEditorProps) {
  return <button className="candidate-preview-button" type="button" onClick={onOpenCandidate}><span className="candidate-stack"><i /><i /><i /></span><span><strong>Open candidate grid</strong><small>Compare connected video outputs</small></span><ChevronRight size={16} /></button>;
}

const customEditorRegistry: Record<string, (props: NodeCustomEditorProps) => ReactNode> = {
  "caption-document": (props) => <CaptionLayoutCustomEditor {...props} />,
  "provider-generation": (props) => <ProviderGenerationEditor {...props} />,
  "video-edit": (props) => <VideoEditor {...props} />,
  "caption-layout": (props) => <CaptionLayoutCustomEditor {...props} />,
  "video-translate": (props) => <VideoTranslateEditor {...props} />,
  "reference-analysis": (props) => <ReferenceAnalysisEditor {...props} />,
  "motion-extractor": (props) => <MotionExtractorEditor {...props} />,
  "candidate-selection": (props) => <CandidateEditor {...props} />,
  "frame-layout": (props) => <FrameLayoutEditor {...props} />,
  "image-motion": (props) => <ImageMotionEditor {...props} />,
  "subtitle-layout": (props) => <SubtitleRegionEditor {...props} />,
  "subtitle-design": (props) => <SubtitleDesignCustomEditor {...props} />,
};

// Existing immutable contracts declare editor.kind=legacy. This exact-version
// adapter preserves their digests while new contracts can declare a custom ref
// directly in the Manifest.
const legacyEditorRefAdapter: Record<string, string> = {
  "image.generate@1": "provider-generation",
  "lora.image.generate@1": "provider-generation",
  "character.generate@1": "provider-generation",
  "video.generate@1": "provider-generation",
  "tts.generate@1": "provider-generation",
  "llm.assistant@1": "provider-generation",
  "llm.assistant@2": "provider-generation",
  "skill.execute@1": "provider-generation",
  "skill.execute@2": "provider-generation",
  "script.generate@1": "provider-generation",
  "script.generate@2": "provider-generation",
  "video.edit@1": "video-edit",
  "timeline.compose@1": "caption-layout",
  "video.translate@1": "video-translate",
  "reference.decompose@1": "reference-analysis",
  "motion.extract@1": "motion-extractor",
  "candidate.select@1": "candidate-selection",
};

export function renderCustomEditor(definition: NodeDefinitionRecord, props: NodeCustomEditorProps): ReactNode | undefined {
  const ref = definition.editor.kind === "custom"
    ? definition.editor.ref
    : legacyEditorRefAdapter[`${definition.type_key}@${definition.contract_version}`];
  return ref ? customEditorRegistry[ref]?.(props) : undefined;
}
