import type { NodeDefinitionRecord } from "@/lib/api";
import type { IconName, NodeTemplate, ProviderName } from "@/lib/canvas-model";
import type { PortType } from "@/lib/types";

const legacyPortTypes: Record<string, PortType> = {
  "prompt.text.v1": "Prompt",
  "media.image.v1": "Image",
  "media.video.v1": "Video",
  "media.audio.v1": "Audio",
  "artifact.character.v1": "Character",
  "artifact.character_lora.v1": "Character",
  "data.text.v1": "Text",
  "data.json.v1": "Any",
  "data.motion_track.v1": "MotionTrack",
  "data.reference_analysis.v1": "ReferenceAnalysis",
  "data.reference_asset.v1": "ReferenceAsset",
  "data.subtitle.v1": "Subtitle",
  "data.timeline.v1": "Timeline",
};

export function legacyPortType(typeId: string): PortType {
  const type = legacyPortTypes[typeId];
  if (!type) throw new Error(`Unsupported registry port type: ${typeId}`);
  return type;
}

export function nodeTemplateFromDefinition(definition: NodeDefinitionRecord): NodeTemplate {
  const config = Object.fromEntries(Object.entries(definition.config_schema.properties).flatMap(([key, field]) => field.default === undefined ? [] : [[key, field.default]]));
  const inputTypes = definition.ports.inputs.map((port) => legacyPortType(port.type));
  const requiredInputTypes = definition.ports.inputs.filter((port) => port.required).map((port) => legacyPortType(port.type));
  const multiInputTypes = definition.ports.inputs.filter((port) => port.multiple).map((port) => legacyPortType(port.type));
  const output = definition.ports.outputs[0];
  const legacyConfig = {
    resolution: config.resolution,
    aspectRatio: config.aspect_ratio,
    batchSize: config.output_count,
    characterName: config.character_name,
    shotCount: config.shot_count,
    durationSeconds: config.duration_seconds,
    loraUrl: config.lora_url,
    loraScale: config.lora_scale,
    triggerWord: config.trigger_word,
    transition: config.transition,
    targetDurationSeconds: config.target_duration_seconds,
    sourceLanguage: config.source_language,
    separateMusic: config.separate_music,
    sceneThreshold: config.scene_threshold,
    targetLanguage: config.target_language,
    voiceName: config.voice_name,
    skillId: config.skill_id,
    configText: config.text ?? config.artifact_id ?? config.character_id,
  } as Partial<NodeTemplate["data"]>;
  const modelProvider = definition.execution.model_alias.split(".", 1)[0];
  return {
    id: `registry-${definition.type_key.replaceAll(".", "-")}-v${definition.contract_version}`,
    label: definition.display.label,
    group: definition.display.category,
    data: {
      key: definition.type_key,
      label: definition.display.label,
      description: definition.display.description,
      icon: definition.display.icon as IconName,
      kind: definition.execution.kind === "source" ? "input" : definition.execution.kind === "provider" ? "generate" : definition.execution.kind === "human_gate" ? "review" : "logic",
      inputTypes,
      requiredInputTypes,
      multiInputTypes,
      outputType: output ? legacyPortType(output.type) : undefined,
      provider: (["google", "openai", "xai", "fal"].includes(modelProvider) ? modelProvider : definition.execution.provider === "multi" ? "google" : definition.execution.provider) as ProviderName,
      model: definition.execution.model_alias,
      cost: definition.display.cost_label,
      contractVersion: definition.contract_version,
      definitionDigest: definition.definition_digest,
      config,
      executable: definition.execution.kind !== "source",
      ...legacyConfig,
    },
  };
}

export function latestNodeTemplates(definitions: NodeDefinitionRecord[]): NodeTemplate[] {
  const latest = new Map<string, NodeDefinitionRecord>();
  for (const definition of definitions) {
    const current = latest.get(definition.type_key);
    if (!current || definition.contract_version > current.contract_version) latest.set(definition.type_key, definition);
  }
  return [...latest.values()].sort((a, b) => a.display.category.localeCompare(b.display.category) || a.display.label.localeCompare(b.display.label)).map(nodeTemplateFromDefinition);
}
