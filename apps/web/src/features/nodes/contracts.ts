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
  return {
    id: `registry-${definition.type_key.replaceAll(".", "-")}-v${definition.contract_version}`,
    label: definition.display.label,
    group: definition.display.category,
    data: {
      key: definition.type_key,
      label: definition.display.label,
      description: definition.display.description,
      icon: definition.display.icon as IconName,
      kind: definition.execution.kind === "source" ? "input" : "logic",
      inputTypes,
      requiredInputTypes,
      multiInputTypes,
      outputType: output ? legacyPortType(output.type) : undefined,
      provider: definition.execution.provider as ProviderName,
      model: definition.execution.model_alias,
      cost: definition.display.cost_label,
      contractVersion: definition.contract_version,
      definitionDigest: definition.definition_digest,
      config,
    },
  };
}
