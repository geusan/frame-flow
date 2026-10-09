import type { NodeDefinitionRecord, WorkflowBindingDefinition, WorkflowDraftContract, WorkflowInputDefinition } from "../../lib/api";
import type { StudioFlowNode } from "../../lib/canvas-model";

export const templateKeys = (template: string): string[] => [...new Set([...template.matchAll(/\{\{([a-z][a-z0-9_]{0,63})\}\}/g)].map((match) => match[1]))];

export function renameWorkflowInput(contract: WorkflowDraftContract, index: number, patch: Partial<WorkflowInputDefinition>): WorkflowDraftContract {
  const previous = contract.inputs[index].key;
  const next = patch.key ?? previous;
  return {
    ...contract,
    inputs: contract.inputs.map((input, i) => i === index ? { ...input, ...patch } : input),
    bindings: contract.bindings.map((binding) => {
      if (previous === next) return binding;
      if (binding.value.kind === "input") return binding.value.key === previous ? { ...binding, value: { kind: "input", key: next } } : binding;
      return { ...binding, value: { ...binding.value, template: binding.value.template.replaceAll(`{{${previous}}}`, `{{${next}}}`), input_keys: binding.value.input_keys.map((key) => key === previous ? next : key) } };
    }),
  };
}

export function bindingValue(kind: "input" | "template", value: string): WorkflowBindingDefinition["value"] {
  return kind === "input" ? { kind, key: value } : { kind, template: value, input_keys: templateKeys(value) };
}

export function workflowTargets(nodes: StudioFlowNode[], definitions: NodeDefinitionRecord[]) {
  return nodes.flatMap((node) => {
    const definition = definitions.find((item) => item.type_key === node.data.key && item.contract_version === (node.data.contractVersion ?? 1));
    return definition ? Object.entries(definition.config_schema.properties).filter(([, field]) => field["x-workflow-input"]?.enabled).map(([key, field]) => ({
      nodeId: node.id, path: `/config/${key}`, label: `${node.data.label} · ${field.title ?? key}`, field,
    })) : [];
  });
}

export function workflowOutputOptions(nodes: StudioFlowNode[], definitions: NodeDefinitionRecord[]) {
  return nodes.flatMap((node) => {
    const definition = definitions.find((item) => item.type_key === node.data.key && item.contract_version === (node.data.contractVersion ?? 1));
    return definition ? definition.ports.outputs.map((port) => ({ nodeId: node.id, portKey: port.key, portType: port.type, label: `${node.data.label} · ${port.label}` })) : [];
  });
}

/** Used only for the Publish preview; the server compiler is authoritative. */
export function outputReachability(outputs: WorkflowDraftContract["outputs"], edges: Array<{ source: string; target: string }>): Set<string> {
  const reachable = new Set(outputs.map((output) => output.node_id));
  const incoming = new Map<string, string[]>();
  for (const edge of edges) incoming.set(edge.target, [...(incoming.get(edge.target) ?? []), edge.source]);
  const queue = [...reachable];
  for (let index = 0; index < queue.length; index++) for (const source of incoming.get(queue[index]) ?? []) {
    if (!reachable.has(source)) { reachable.add(source); queue.push(source); }
  }
  return reachable;
}
