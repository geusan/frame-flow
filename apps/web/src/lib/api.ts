export const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export interface InspectResult {
  canonical_url: string;
  source_id: string;
  title: string;
  creator: string;
  duration_ms: number;
  width: number;
  height: number;
  has_subtitles: boolean;
  estimated_bytes: number;
  thumbnail_url?: string;
  duplicate_reference_id?: string;
}

export interface ReferenceRecord {
  id: string;
  created_at: string;
  title: string;
  creator: string;
  duration_ms: number;
  rights_basis: "owned" | "licensed" | "creative_commons" | "analysis_only" | "unknown";
  allow_generation_input: boolean;
  status: "analyzed" | "processing" | "ready";
  metadata: Record<string, unknown>;
  thumbnail_url?: string;
}

export interface FormatRecord {
  id: string;
  created_at: string;
  name: string;
  kind: string;
  parent_ids: string[];
  payload: { core: import("./types").FormatCore; extensions?: Record<string, unknown>; evidence?: import("./types").FormatProfile["evidence"] };
  lineage: Record<string, unknown>;
}

export interface RunRecord {
  id: string;
  created_at: string;
  name: string;
  status: string;
  progress: number;
  estimated_cost_usd: number;
  actual_cost_usd: number;
  budget_limit_usd: number;
  execution_plan: Record<string, unknown>;
  node_runs: Array<{ id: string; node_key: string; status: string; progress: number; cost_usd: number; output_artifact_ids: string[] }>;
}

export interface ModelRecord {
  logical_alias: string;
  exact_model_id: string;
  provider: string;
  modality: string;
  region: string;
  status: "active" | "disabled";
  configured: boolean;
  configuration: string;
  usage_count: number;
  recorded_cost_usd: number;
  last_used_at?: string;
}

export interface ProviderSettingField {
  key: string;
  label: string;
  env_var: string;
  value: string;
  secret: boolean;
  required: boolean;
  has_value: boolean;
  placeholder: string;
  help_text: string;
  auth_methods: string[];
}

export interface ProviderAuthMethod {
  key: string;
  label: string;
  description: string;
  kind: "api_key" | "oauth" | "setup_token" | "cloud";
  external: boolean;
  required_fields: string[];
}

export interface ProviderSetting {
  provider: "openai" | "google" | "claude" | "elevenlabs" | "seedance" | "kling" | "minimax" | "fal";
  label: string;
  description: string;
  enabled: boolean;
  configured: boolean;
  auth_method: string;
  auth_methods: ProviderAuthMethod[];
  source: "default" | "environment" | "database";
  created_at: string;
  updated_at: string;
  fields: ProviderSettingField[];
}

export interface WorkspaceSummary {
  service: string;
  environment: string;
  storage_provider: string;
  execution_backend: string;
  references: number;
  canvases: number;
  formats: number;
  runs: number;
  regular_runs: number;
  canvas_runs: number;
  active_runs: number;
  experiments: number;
  recorded_cost_usd: number;
  images: number;
  characters: number;
  videos: number;
  artifacts: number;
}

export interface ProjectSkillRecord {
  id: string;
  display_name: string;
  description: string;
  version: string;
}

export interface CharacterRecord {
  id: string;
  created_at: string;
  name: string;
  synopsis: string;
  model_alias: string;
  exact_model_id: string;
  cover_url?: string;
  image_count: number;
  images: Array<{ artifact_id: string; role: string; url: string }>;
}

export interface CanvasDocument {
  id: string;
  created_at: string;
  updated_at: string;
  name: string;
  nodes: Array<Record<string, unknown>>;
  edges: Array<Record<string, unknown>>;
  node_count: number;
  edge_count: number;
  active_run_id?: string;
  last_run?: { id: string; status: string; progress: number; created_at: string };
}

export interface WorkflowRunRecord {
  id: string;
  created_at: string;
  run_type: "generation" | "canvas";
  name: string;
  status: string;
  progress: number;
  cost_usd: number;
  estimated_cost_usd?: number;
  nodes_done: number;
  nodes_total: number;
  attempt_count: number;
  duration_ms?: number;
}

export interface CanvasNodeRunRecord {
  id: string;
  created_at: string;
  canvas_node_id: string;
  node_key: string;
  status: string;
  progress: number;
  attempt_count: number;
  provider_request_id?: string;
  provider_operation_id?: string;
  request_hash?: string;
  output_artifact_ids: string[];
  output: ExperimentOutput | Record<string, never>;
  duration_ms: number;
  cost_usd: number;
  error?: string;
}

export interface CanvasRunRecord {
  id: string;
  created_at: string;
  canvas_id: string;
  name: string;
  status: string;
  progress: number;
  graph: Record<string, unknown>;
  node_runs: CanvasNodeRunRecord[];
}

export interface ExperimentOutput {
  kind: "image" | "video" | "audio" | "text" | "json";
  title: string;
  url?: string;
  text?: string;
  mimeType?: string;
}

export interface ExperimentRun {
  id: string;
  created_at: string;
  canvas_id: string;
  node_id: string;
  node_key: string;
  status: string;
  execution_mode: string;
  prompt: string;
  model_alias: string;
  exact_model_id: string;
  parameters: Record<string, unknown>;
  inputs: Array<Record<string, unknown>>;
  request_hash: string;
  provider_request_id?: string;
  output_artifact_ids: string[];
  output: ExperimentOutput;
  duration_ms: number;
  cost_usd: number;
  cache_hit: boolean;
  cached_from_id?: string;
  is_baseline: boolean;
  error?: string;
}

export interface CreateExperimentInput {
  canvas_id: string;
  node_id: string;
  node_key: string;
  prompt: string;
  model_alias: string;
  parameters: Record<string, unknown>;
  inputs: Array<Record<string, unknown>>;
}

export interface UploadedArtifact {
  artifact_id: string;
  type: "Image" | "Video" | "Audio" | "Text";
  content_type: string;
  size_bytes: number;
  filename: string;
  source_url?: string;
  downloader_provider?: string;
  url: string;
}

export interface ArtifactListItem {
  id: string;
  created_at: string;
  type: "Image" | "Video" | "Audio" | "Text" | "FinalVideo" | "ReferenceAnalysis" | "ReferenceAudioMix" | "ReferenceTranscript" | "ReferenceSubtitle" | "ReferenceVocals" | "ReferenceAccompaniment";
  content_type: string;
  size_bytes: number;
  filename: string;
  source: string;
  duration_ms: number;
  url: string;
}

export interface ArtifactDetail {
  id: string;
  created_at: string;
  type: ArtifactListItem["type"];
  schema_id?: string;
  uri: string;
  sha256: string;
  producer_node_run_id?: string;
  input_artifact_ids: string[];
  metadata: Record<string, unknown> & {
    filename?: string;
    source?: string;
    output?: { title?: string; text?: string; kind?: string };
    storage?: { content_type?: string; size_bytes?: number };
  };
}

export interface ImageEditDocument {
  version: "image-edit.v1";
  aspect_ratio: "original" | "1:1" | "4:5" | "9:16" | "16:9";
  transform: {
    rotation: number;
    zoom: number;
    offset_x: number;
    offset_y: number;
    flip_horizontal: boolean;
    flip_vertical: boolean;
  };
  adjustments: {
    brightness: number;
    contrast: number;
    saturation: number;
    blur: number;
    grayscale: number;
    sepia: number;
  };
  lighting: {
    enabled: boolean;
    x: number;
    y: number;
    intensity: number;
    radius: number;
    softness: number;
    color: string;
  };
}

export interface CapturedFrameArtifact extends ArtifactListItem {
  source_artifact_id: string;
  timestamp_ms: number;
}

export interface SceneSearchCandidate {
  index: number;
  timestamp_ms: number;
  score: number;
  reason: string;
  thumbnail_data_url: string;
}

export interface SceneSearchResult {
  search_id: string;
  source_artifact_id: string;
  prompt: string;
  provider: string;
  model_alias: string;
  exact_model_id: string;
  provider_request_id: string;
  source_duration_ms: number;
  candidates: SceneSearchCandidate[];
}

export interface SceneCaptureContext {
  search_id: string;
  search_prompt: string;
  search_score: number;
  search_reason: string;
  search_provider: "google" | "openai";
  search_model_alias: string;
  search_model: string;
  provider_request_id: string;
}

export interface ArtifactLineageNode extends ArtifactListItem {
  schema_id?: string;
  sha256: string;
  producer_node_run_id?: string;
  input_artifact_ids: string[];
  metadata: Record<string, unknown>;
  derivation: {
    operation: string;
    title: string;
    description: string;
    prompt?: string;
    model_alias?: string;
    exact_model_id?: string;
    parameters: Record<string, unknown>;
    request_hash?: string;
    execution_mode?: string;
  };
  is_root: boolean;
}

export interface ArtifactLineageEdge {
  id: string;
  created_at: string;
  parent_artifact_id: string;
  child_artifact_id: string;
  role: string;
  ordinal: number;
  operation_id?: string;
  metadata: Record<string, unknown>;
}

export interface ArtifactLineageGraph {
  root_artifact_id: string;
  direction: "ancestors" | "descendants" | "both";
  depth: number;
  nodes: ArtifactLineageNode[];
  edges: ArtifactLineageEdge[];
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const hasFormBody = typeof FormData !== "undefined" && init?.body instanceof FormData;
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { ...(hasFormBody ? {} : { "content-type": "application/json" }), ...init?.headers },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(body.detail ?? `API request failed (${response.status})`);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const frameflowApi = {
  health: () => request<{ status: string; service: string; google_configured: boolean; openai_configured: boolean; generation_provider_mode: string; video_downloader_provider: string; storage_provider: string; execution_backend: string }>("/health"),
  listSkills: () => request<ProjectSkillRecord[]>("/skills"),
  workspaceSummary: () => request<WorkspaceSummary>("/workspace/summary"),
  listCharacters: () => request<CharacterRecord[]>("/characters"),
  listCanvases: () => request<CanvasDocument[]>("/canvases"),
  createCanvas: (name = "Untitled canvas") => request<CanvasDocument>("/canvases", { method: "POST", body: JSON.stringify({ name, nodes: [], edges: [] }) }),
  getCanvas: (canvasId: string) => request<CanvasDocument>(`/canvases/${canvasId}`),
  saveCanvas: (canvasId: string, payload: { name: string; nodes: Array<Record<string, unknown>>; edges: Array<Record<string, unknown>>; active_run_id?: string }) => request<CanvasDocument>(`/canvases/${canvasId}`, { method: "PUT", body: JSON.stringify(payload) }),
  deleteCanvas: (canvasId: string) => request<void>(`/canvases/${canvasId}`, { method: "DELETE" }),
  inspectReferences: (urls: string[]) => request<InspectResult[]>("/references/inspect", { method: "POST", body: JSON.stringify({ urls }) }),
  listReferences: () => request<ReferenceRecord[]>("/references"),
  importReference: (metadata: InspectResult, rightsBasis: ReferenceRecord["rights_basis"] = "analysis_only") => request<{ reference_id: string; deduplicated: boolean; artifact_ids: string[] }>("/references/import", { method: "POST", body: JSON.stringify({ metadata, rights_basis: rightsBasis, allow_generation_input: ["owned", "licensed", "creative_commons"].includes(rightsBasis), allow_direct_asset_use: ["owned", "licensed"].includes(rightsBasis) }) }),
  createReferenceSet: (name: string, referenceIds: string[]) => request<{ id: string; name: string; reference_ids: string[] }>("/reference-sets", { method: "POST", body: JSON.stringify({ name, reference_ids: referenceIds }) }),
  extractFormat: (referenceSetId: string, name: string) => request<{ id: string; name: string; artifact_id: string }>("/format-runs", { method: "POST", body: JSON.stringify({ reference_set_id: referenceSetId, name }) }),
  listFormats: () => request<FormatRecord[]>("/formats"),
  createFormatVariants: (formatId: string, count = 1) => request<Array<{ id: string; name: string }>>(`/formats/${formatId}/variants`, { method: "POST", body: JSON.stringify({ count, distance: "medium", variation_axes: ["visual_motion"] }) }),
  listRuns: () => request<RunRecord[]>("/runs"),
  listWorkflowRuns: () => request<WorkflowRunRecord[]>("/workflow-runs"),
  listModels: () => request<ModelRecord[]>("/models"),
  listProviderSettings: () => request<ProviderSetting[]>("/settings/providers"),
  updateProviderSettings: (provider: ProviderSetting["provider"], payload: { enabled: boolean; auth_method?: string; values: Record<string, string>; clear_fields?: string[] }) => request<ProviderSetting>(`/settings/providers/${provider}`, { method: "PUT", body: JSON.stringify(payload) }),
  createExperiment: (payload: CreateExperimentInput) => request<ExperimentRun>("/experiments", { method: "POST", body: JSON.stringify(payload) }),
  listExperiments: (canvasId: string, nodeId?: string, limit = 20) => {
    const query = new URLSearchParams({ canvas_id: canvasId, limit: String(limit) });
    if (nodeId) query.set("node_id", nodeId);
    return request<ExperimentRun[]>(`/experiments?${query}`);
  },
  setExperimentBaseline: (experimentId: string) => request<ExperimentRun>(`/experiments/${experimentId}/baseline`, { method: "POST" }),
  uploadArtifact: (file: File) => {
    const body = new FormData();
    body.append("file", file, file.name);
    return request<UploadedArtifact>("/artifacts/upload", { method: "POST", body });
  },
  importArtifactUrl: (url: string) => request<UploadedArtifact>("/artifacts/import-url", { method: "POST", body: JSON.stringify({ url }) }),
  listArtifacts: (types: ArtifactListItem["type"][] = ["Image", "Video", "FinalVideo"], limit = 500, offset = 0) => {
    const query = new URLSearchParams({ types: types.join(","), limit: String(limit), offset: String(offset) });
    return request<ArtifactListItem[]>(`/artifacts?${query}`);
  },
  listAllArtifacts: async (types: ArtifactListItem["type"][] = ["Image", "Video", "FinalVideo"]) => {
    const assets: ArtifactListItem[] = [];
    const pageSize = 500;
    while (true) {
      const query = new URLSearchParams({ types: types.join(","), limit: String(pageSize), offset: String(assets.length) });
      const page = await request<ArtifactListItem[]>(`/artifacts?${query}`);
      assets.push(...page);
      if (page.length < pageSize) return assets;
    }
  },
  getArtifact: (artifactId: string) => request<ArtifactDetail>(`/artifacts/${artifactId}`),
  saveManualImageEdit: (artifactId: string, image: Blob, document: ImageEditDocument) => {
    const body = new FormData();
    body.append("file", new File([image], `edited-${artifactId}.png`, { type: "image/png" }));
    body.append("edit_document", JSON.stringify(document));
    return request<ArtifactListItem>(`/artifacts/${artifactId}/image-edits`, { method: "POST", body });
  },
  captureVideoFrame: (artifactId: string, timestampMs: number, context?: SceneCaptureContext) => request<CapturedFrameArtifact>(`/artifacts/${artifactId}/capture-frame`, { method: "POST", body: JSON.stringify({ timestamp_ms: timestampMs, ...context }) }),
  searchVideoScenes: (artifactId: string, prompt: string, provider: "google" | "openai", modelAlias: string, candidateCount = 4, sampleCount = 12) => request<SceneSearchResult>(`/artifacts/${artifactId}/scene-search`, { method: "POST", body: JSON.stringify({ prompt, provider, model_alias: modelAlias, candidate_count: candidateCount, sample_count: sampleCount }) }),
  getArtifactLineage: (artifactId: string, direction: ArtifactLineageGraph["direction"] = "both", depth = 8) => {
    const query = new URLSearchParams({ direction, depth: String(depth) });
    return request<ArtifactLineageGraph>(`/artifacts/${artifactId}/lineage?${query}`);
  },
  createCanvasRun: (payload: { canvas_id: string; name: string; nodes: Array<Record<string, unknown>>; edges: Array<Record<string, unknown>> }) => request<CanvasRunRecord>("/canvas-runs", { method: "POST", body: JSON.stringify(payload) }),
  getCanvasRun: (runId: string) => request<CanvasRunRecord>(`/canvas-runs/${runId}`),
  cancelCanvasRun: (runId: string) => request<CanvasRunRecord>(`/canvas-runs/${runId}/cancel`, { method: "POST" }),
  selectCanvasCandidate: (runId: string, canvasNodeId: string, artifactId: string) => request<CanvasRunRecord>(`/canvas-runs/${runId}/nodes/${canvasNodeId}/select`, { method: "POST", body: JSON.stringify({ artifact_id: artifactId }) }),
  approveCanvasNode: (runId: string, canvasNodeId: string, parameters: Record<string, unknown>) => request<CanvasRunRecord>(`/canvas-runs/${runId}/nodes/${canvasNodeId}/approve`, { method: "POST", body: JSON.stringify({ parameters }) }),
  canvasRunEventsUrl: (runId: string) => `${API_BASE}/canvas-runs/${runId}/events`,
};
