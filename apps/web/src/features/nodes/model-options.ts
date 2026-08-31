import type { ModelRecord, NodeDefinitionRecord } from "@/lib/api";
import type { ProviderName } from "@/lib/canvas-model";

export interface NodeModelOption {
  value: string;
  label: string;
  provider: ProviderName;
  configured: boolean;
  configurationKnown: boolean;
}

const providerLabels: Record<string, string> = { google: "Google", openai: "OpenAI", xai: "xAI", fal: "fal.ai", chatgpt: "ChatGPT", claude: "Claude" };

export function providerForModelAlias(alias?: string): ProviderName | undefined {
  return alias?.split(".", 1)[0] || undefined;
}

export function modelOptionsForDefinition(definition: NodeDefinitionRecord | undefined, models: ModelRecord[], currentModelAlias?: string): NodeModelOption[] {
  if (!definition || definition.execution.kind !== "provider") return [];
  const families = definition.execution.model_families.length ? definition.execution.model_families : [definition.execution.model_alias];
  const compatible = models
    .filter((model) => families.some((family) => model.logical_alias.startsWith(family)))
    .map((model) => ({
      value: model.logical_alias,
      label: model.exact_model_id || model.logical_alias,
      provider: providerForModelAlias(model.logical_alias) ?? definition.execution.provider,
      configured: model.configured,
      configurationKnown: true,
    }));
  if (!compatible.some((model) => model.value === definition.execution.model_alias)) {
    compatible.unshift({
      value: definition.execution.model_alias,
      label: definition.execution.model_alias,
      provider: providerForModelAlias(definition.execution.model_alias) ?? definition.execution.provider,
      configured: false,
      configurationKnown: false,
    });
  }
  if (currentModelAlias && families.some((family) => currentModelAlias.startsWith(family)) && !compatible.some((model) => model.value === currentModelAlias)) {
    compatible.push({
      value: currentModelAlias,
      label: currentModelAlias,
      provider: providerForModelAlias(currentModelAlias) ?? definition.execution.provider,
      configured: false,
      configurationKnown: false,
    });
  }
  return compatible;
}

export function providerOptionsForDefinition(definition: NodeDefinitionRecord | undefined, models: ModelRecord[], currentModelAlias?: string): Array<{ value: ProviderName; label: string }> {
  const providers = new Set(modelOptionsForDefinition(definition, models, currentModelAlias).map((model) => model.provider));
  return [...providers].map((provider) => ({ value: provider, label: providerLabels[provider] ?? provider }));
}
