const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

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

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { "content-type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(body.detail ?? `API request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}

export const frameflowApi = {
  health: () => request<{ status: string; service: string }>("/health"),
  inspectReferences: (urls: string[]) => request<InspectResult[]>("/references/inspect", { method: "POST", body: JSON.stringify({ urls }) }),
  createExperiment: (payload: CreateExperimentInput) => request<ExperimentRun>("/experiments", { method: "POST", body: JSON.stringify(payload) }),
  listExperiments: (canvasId: string, nodeId: string, limit = 20) => {
    const query = new URLSearchParams({ canvas_id: canvasId, node_id: nodeId, limit: String(limit) });
    return request<ExperimentRun[]>(`/experiments?${query}`);
  },
  setExperimentBaseline: (experimentId: string) => request<ExperimentRun>(`/experiments/${experimentId}/baseline`, { method: "POST" }),
};
