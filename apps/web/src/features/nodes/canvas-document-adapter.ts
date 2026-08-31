import type { Edge } from "@xyflow/react";

import type { StudioFlowNode } from "@/lib/canvas-model";
import type { CanvasDocumentV1, NodeDefinitionRecord } from "@/lib/api";

export const LEGACY_CONFIG_DATA_FIELDS: Record<string, keyof StudioFlowNode["data"]> = {
  resolution: "resolution",
  aspect_ratio: "aspectRatio",
  output_count: "batchSize",
  character_name: "characterName",
  shot_count: "shotCount",
  duration_seconds: "durationSeconds",
  lora_url: "loraUrl",
  lora_scale: "loraScale",
  trigger_word: "triggerWord",
  transition: "transition",
  target_duration_seconds: "targetDurationSeconds",
  source_language: "sourceLanguage",
  separate_music: "separateMusic",
  scene_threshold: "sceneThreshold",
  motion_sample_fps: "motionSampleFps",
  motion_max_width: "motionMaxWidth",
  motion_min_confidence: "motionMinConfidence",
  motion_face_blendshapes: "motionFaceBlendshapes",
  target_language: "targetLanguage",
  voice_name: "voiceName",
  caption_x: "captionX",
  caption_y: "captionY",
  caption_align: "captionAlign",
  caption_font_size: "captionFontSize",
  skill_id: "skillId",
};

const canvasElementKeys = new Set(["utility.sticky", "folder.group", "asset.upload", "utility.drawing"]);
const runtimeFields = new Set([
  "status", "preview", "attemptCount", "lastRunAt", "logs", "output", "outputEdited", "lastExperimentId",
  "outputArtifactIds", "lastRequestHash", "executionMode", "lastCostUsd", "runProgress", "promptEdited",
]);
const contractDerivedFields = new Set([
  "key", "label", "description", "icon", "kind", "inputTypes", "inputsRequired", "requiredInputTypes", "multiInputTypes",
  "outputType", "cost", "contractVersion", "definitionDigest", "config", "parameters", "model", "provider", "executable",
]);
const ephemeralReactFlowFields = new Set(["selected", "dragging", "measured", "width", "height", "positionAbsolute"]);
const qualifiedModelPrefixes = ["google.", "openai.", "fal.", "xai.", "chatgpt.", "claude.", "local.", "reference-analysis."];

function definitionForNode(node: StudioFlowNode, definitions: NodeDefinitionRecord[]): NodeDefinitionRecord | undefined {
  return definitions.find((definition) => definition.type_key === node.data.key && definition.contract_version === (node.data.contractVersion ?? 1));
}

function materializedConfig(node: StudioFlowNode, definition: NodeDefinitionRecord | undefined): Record<string, unknown> {
  const config = { ...(node.data.config ?? {}) };
  const preferLegacy = definition?.editor.kind === "legacy";
  for (const [configKey, dataKey] of Object.entries(LEGACY_CONFIG_DATA_FIELDS)) {
    const value = node.data[dataKey];
    if (value !== undefined && (preferLegacy || config[configKey] === undefined)) config[configKey] = value;
  }
  if (["prompt.input", "generation.brief"].includes(node.data.key) && (preferLegacy || config.text === undefined)) config.text = node.data.configText ?? "";
  if (node.data.key === "asset.select") {
    if (preferLegacy || config.artifact_id === undefined) config.artifact_id = node.data.configText || node.data.outputArtifactIds?.[0] || "";
    if (preferLegacy || config.artifact_type === undefined) config.artifact_type = node.data.outputType ?? "ReferenceAsset";
  }
  if (node.data.key === "character.select" && (preferLegacy || config.character_id === undefined)) config.character_id = node.data.configText || node.data.outputArtifactIds?.[0] || "";
  if (node.data.key === "format.profile" && (preferLegacy || config.format_id === undefined)) config.format_id = node.data.configText ?? "";
  if (definition) {
    for (const [key, field] of Object.entries(definition.config_schema.properties)) {
      if (config[key] === undefined && field.default !== undefined) config[key] = field.default;
    }
  }
  return config;
}

function executionSnapshot(node: StudioFlowNode, definition: NodeDefinitionRecord | undefined): { model_alias: string; provider: string } {
  const provider = node.data.provider ?? definition?.execution.provider ?? "local";
  const selected = node.data.model ?? definition?.execution.model_alias ?? "local.unknown";
  const modelAlias = qualifiedModelPrefixes.some((prefix) => selected.startsWith(prefix))
    ? selected
    : ["google", "openai", "fal", "xai", "chatgpt", "claude"].includes(provider) ? `${provider}.${selected}` : selected;
  return { model_alias: modelAlias, provider };
}

function runtimeData(node: StudioFlowNode): Record<string, unknown> {
  return Object.fromEntries(Object.entries(node.data).flatMap(([key, value]) => {
    if (!runtimeFields.has(key) || value === undefined) return [];
    if (key === "output" && typeof value === "object" && value && "url" in value && String(value.url).startsWith("blob:")) return [];
    return [[key, value]];
  }));
}

function reactFlowData(node: StudioFlowNode): Record<string, unknown> {
  const raw = node as unknown as Record<string, unknown>;
  return Object.fromEntries(Object.entries(raw).filter(([key]) => !["id", "data", "position"].includes(key) && !ephemeralReactFlowFields.has(key)));
}

function legacyEditorData(node: StudioFlowNode): Record<string, unknown> {
  const configDataKeys = new Set(Object.values(LEGACY_CONFIG_DATA_FIELDS));
  const sourceConfigKeys = new Set(["prompt.input", "generation.brief", "asset.select", "character.select", "format.profile"]);
  return Object.fromEntries(Object.entries(node.data).filter(([key, value]) => (
    value !== undefined
    && !runtimeFields.has(key)
    && !contractDerivedFields.has(key)
    && !configDataKeys.has(key as keyof StudioFlowNode["data"])
    && !(key === "configText" && sourceConfigKeys.has(node.data.key))
  )));
}

export function serializeCanvasDocument(nodes: StudioFlowNode[], edges: Edge[], definitions: NodeDefinitionRecord[]): CanvasDocumentV1 {
  const graphNodes: Array<Record<string, unknown>> = [];
  const elements: Array<Record<string, unknown>> = [];
  const runtimeNodes: Record<string, Record<string, unknown>> = {};

  nodes.forEach((node, order) => {
    const runtime = runtimeData(node);
    if (Object.keys(runtime).length) runtimeNodes[node.id] = runtime;
    const ui = { order, position: node.position, label: node.data.label, description: node.data.description, react_flow: reactFlowData(node) };
    if (canvasElementKeys.has(node.data.key)) {
      elements.push({
        id: node.id,
        element_type: node.data.key,
        ui,
        editor: { data: Object.fromEntries(Object.entries(node.data).filter(([key, value]) => value !== undefined && !runtimeFields.has(key) && !["key", "label", "description"].includes(key))) },
      });
      return;
    }
    const definition = definitionForNode(node, definitions);
    graphNodes.push({
      id: node.id,
      type_key: node.data.key,
      contract_version: node.data.contractVersion ?? 1,
      definition_digest: definition?.definition_digest ?? node.data.definitionDigest ?? null,
      config: materializedConfig(node, definition),
      execution: executionSnapshot(node, definition),
      ui,
      editor: { legacy_data: legacyEditorData(node) },
      ...(!definition ? { unknown: true } : {}),
    });
  });

  return {
    schema_version: "canvas.document.v1",
    graph: {
      schema_version: "canvas.graph.v1",
      nodes: graphNodes,
      elements,
      edges: edges.map((edge) => ({
        id: edge.id,
        source: edge.source,
        target: edge.target,
        source_port: edge.sourceHandle ?? null,
        target_port: edge.targetHandle ?? null,
        ui: Object.fromEntries(Object.entries(edge).filter(([key]) => !["id", "source", "target", "sourceHandle", "targetHandle", "selected"].includes(key))),
      })),
    },
    runtime: { schema_version: "canvas.runtime.v1", nodes: runtimeNodes },
  };
}
