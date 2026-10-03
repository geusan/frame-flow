import type { ArtifactListItem, CanvasRunRecord, CharacterRecord, NodeDefinitionRecord, WorkflowInputDefinition, WorkflowRunRecord, WorkflowVersionRecord } from "../../lib/api";

export const TERMINAL_RUN_STATUSES = new Set(["SUCCEEDED", "FAILED", "CANCELED"]);
export const isActiveRun = (status: string) => !TERMINAL_RUN_STATUSES.has(status);
export const runStatusLabel = (status: string) => ({ READY: "대기 중", QUEUED: "대기 중", CLAIMED: "작업 준비", SUBMITTED: "처리 요청됨", RUNNING: "실행 중", WAITING_INPUT: "검토 필요", RETRY_WAIT: "재시도 대기", SUCCEEDED: "완료", FAILED: "실패", CANCELED: "취소됨", BLOCKED: "선행 작업 대기", STALE: "입력 변경됨" }[status] ?? status);

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

export function httpImageUrl(text: string): string | null {
  try {
    const url = new URL(text.trim());
    return ["http:", "https:"].includes(url.protocol) && !url.username && !url.password ? url.href : null;
  } catch { return null; }
}

export function missingWorkflowInputs(definitions: WorkflowInputDefinition[], values: Record<string, unknown>): string[] {
  return definitions.filter((item) => item.required && (values[item.key] == null || (typeof values[item.key] === "string" && !String(values[item.key]).trim()))).map((item) => item.label);
}

export function uploadedAsset(artifact: { artifact_id: string; type: ArtifactListItem["type"]; content_type: string; size_bytes: number; filename: string; url: string }): ArtifactListItem {
  return { id: artifact.artifact_id, created_at: new Date().toISOString(), type: artifact.type, content_type: artifact.content_type, size_bytes: artifact.size_bytes, filename: artifact.filename, source: "canvas_upload", duration_ms: 0, url: artifact.url };
}

export function workflowPresentation(version: WorkflowVersionRecord, definitions: NodeDefinitionRecord[], assets: ArtifactListItem[], characters: CharacterRecord[]) {
  const bound = new Set(version.bindings.bindings.map((binding) => {
    const target = record(binding.target);
    return `${target.node_id}:${target.path}`;
  }));
  const functions: Array<{ id: string; label: string; description: string }> = [];
  const references: Array<{ id: string; artifactId: string; label: string; url?: string; characterName?: string }> = [];
  for (const node of version.graph.nodes) {
    const definition = definitions.find((item) => item.type_key === node.type_key && item.contract_version === node.contract_version && item.definition_digest === node.definition_digest);
    const ui = record(node.ui);
    if (definition?.execution.kind !== "source") functions.push({ id: String(node.id), label: String(ui.label || definition?.display.label || node.type_key), description: String(ui.description || definition?.display.description || "") });
    for (const [field, schema] of Object.entries(definition?.config_schema.properties ?? {})) {
      if (!["artifact", "character"].includes(schema["x-workflow-input"]?.type ?? "") || bound.has(`${node.id}:/config/${field}`)) continue;
      const artifactId = record(node.config)[field];
      if (typeof artifactId !== "string" || !artifactId) continue;
      const asset = assets.find((item) => item.id === artifactId);
      const character = characters.find((item) => item.id === artifactId || item.images.some((image) => image.artifact_id === artifactId));
      const image = character?.images.find((item) => item.artifact_id === artifactId);
      references.push({ id: `${node.id}:${field}`, artifactId, label: String(ui.label || schema.title || "고정 참조"), url: asset?.type === "Image" ? asset.url : image?.url ?? (character?.id === artifactId ? character.cover_url : undefined), characterName: character?.name });
    }
  }
  return { functions, references };
}

export function summaryFromRun(run: CanvasRunRecord): WorkflowRunRecord {
  return { id: run.id, created_at: run.created_at, run_type: "workflow", name: run.name, status: run.status, progress: run.progress, workflow_definition_id: run.workflow_definition_id, workflow_version_id: run.workflow_version_id, nodes_done: run.node_runs.filter((node) => node.status === "SUCCEEDED").length, nodes_total: run.node_runs.length, cost_usd: run.node_runs.reduce((sum, node) => sum + node.cost_usd, 0), cost_summary: run.cost_summary, attempt_count: run.node_runs.reduce((sum, node) => sum + node.attempt_count, 0) };
}

export function workflowRunOutputs(run: CanvasRunRecord | undefined, version: WorkflowVersionRecord | undefined) {
  if (!run || !version || run.workflow_version_id !== version.id) return [];
  return version.output_schema.outputs.map((output) => ({
    key: String(output.key), label: String(output.label || output.key), primary: output.primary === true,
    node: run.node_runs.find((node) => node.canvas_node_id === output.node_id),
  })).sort((a, b) => Number(b.primary) - Number(a.primary));
}

export function workflowRunInputs(run: CanvasRunRecord, version: WorkflowVersionRecord | undefined, assets: ArtifactListItem[]) {
  const definitions = version && version.id === run.workflow_version_id ? version.input_schema.inputs : [];
  return Object.entries(run.inputs).map(([key, value]) => {
    const definition = definitions.find((item) => item.key === key);
    const asset = assets.find((item) => item.id === value);
    const allowed = definition?.validation?.artifact_types;
    const artifactId = typeof value === "string" && value && (definition?.type === "artifact" || asset) ? value : undefined;
    return {
      key, value, label: definition?.label ?? key, artifactId, filename: asset?.filename,
      artifactType: asset?.type ?? (Array.isArray(allowed) && allowed.length === 1 ? String(allowed[0]) : undefined),
    };
  });
}

export function rerunRequest(run: CanvasRunRecord, workflowId: string, versions: WorkflowVersionRecord[]) {
  const version = versions.find((item) => item.id === run.workflow_version_id);
  if (run.workflow_definition_id !== workflowId || !version) throw new Error("실행 당시의 워크플로우 버전을 찾을 수 없습니다.");
  return { version: version.version_number, inputs: structuredClone(run.inputs) };
}
