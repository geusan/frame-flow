import type { Edge } from "@xyflow/react";

import { inputHandleId, isConnectionCompatible as legacyConnectionCompatible, type StudioFlowNode } from "@/lib/canvas-model";
import type { PortType } from "@/lib/types";
import type { NodeDefinitionRecord, NodePortTypeRegistryRecord } from "@/lib/api";

type ConnectionCandidate = Pick<Edge, "source" | "target" | "sourceHandle" | "targetHandle">;

export interface ResolvedTargetPort {
  typeId: string;
  multiple: boolean;
}

function definitionForNode(node: StudioFlowNode, definitions: NodeDefinitionRecord[]): NodeDefinitionRecord | undefined {
  return definitions.find((definition) => definition.type_key === node.data.key && definition.contract_version === (node.data.contractVersion ?? 1));
}

function canonicalTypeForLegacy(legacyType: string | undefined, registry: NodePortTypeRegistryRecord): string | undefined {
  if (!legacyType) return undefined;
  return registry.types.find((type) => type.legacy_type === legacyType)?.id;
}

function sourcePortType(
  connection: ConnectionCandidate,
  source: StudioFlowNode,
  definition: NodeDefinitionRecord,
  registry: NodePortTypeRegistryRecord,
): string | undefined {
  const output = connection.sourceHandle && connection.sourceHandle !== "output"
    ? definition.ports.outputs.find((port) => connection.sourceHandle === port.key || connection.sourceHandle === `output-${port.key}`)
    : definition.ports.outputs[0];
  if (!output) return undefined;
  // asset.select@1 exposes a fixed artifact_type in Config while retaining its
  // legacy data.reference_asset.v1 output contract. Resolve that explicit Draft
  // type until separate typed Asset source contracts replace the adapter.
  if (output.type === "data.reference_asset.v1") {
    return canonicalTypeForLegacy(String(source.data.outputType ?? source.data.config?.artifact_type ?? "ReferenceAsset"), registry) ?? output.type;
  }
  return output.type;
}

export function targetPortContract(
  connection: Pick<ConnectionCandidate, "target" | "targetHandle">,
  nodes: StudioFlowNode[],
  definitions: NodeDefinitionRecord[],
  registry: NodePortTypeRegistryRecord,
): ResolvedTargetPort | undefined {
  const target = nodes.find((node) => node.id === connection.target);
  if (!target) return undefined;
  const definition = definitionForNode(target, definitions);
  if (!definition) return undefined;
  const inputs = definition.ports.inputs;
  const index = connection.targetHandle
    ? inputs.findIndex((port, portIndex) => {
      const legacyType = target.data.inputTypes?.[portIndex] ?? registry.types.find((type) => type.id === port.type)?.legacy_type;
      return connection.targetHandle === port.key
        || connection.targetHandle === `input-${port.key}`
        || (legacyType ? connection.targetHandle === inputHandleId(legacyType as PortType, portIndex) : false);
    })
    : inputs.length === 1 ? 0 : -1;
  const port = index >= 0 ? inputs[index] : undefined;
  return port ? { typeId: port.type, multiple: port.multiple } : undefined;
}

export function portTypesCompatible(sourceType: string, targetType: string, registry: NodePortTypeRegistryRecord): boolean {
  const source = registry.types.find((type) => type.id === sourceType);
  const target = registry.types.find((type) => type.id === targetType);
  if (!source || !target) return false;
  return sourceType === targetType || source.compatible_with.includes(targetType);
}

export function nodeConnectionCompatible(
  connection: ConnectionCandidate,
  nodes: StudioFlowNode[],
  definitions: NodeDefinitionRecord[],
  registry: NodePortTypeRegistryRecord,
): boolean {
  if (connection.source === connection.target) return false;
  const source = nodes.find((node) => node.id === connection.source);
  const target = nodes.find((node) => node.id === connection.target);
  if (!source || !target) return false;
  const sourceDefinition = definitionForNode(source, definitions);
  const targetDefinition = definitionForNode(target, definitions);
  if (!sourceDefinition || !targetDefinition || !registry.types.length) return legacyConnectionCompatible(connection, nodes);
  const sourceType = sourcePortType(connection, source, sourceDefinition, registry);
  const targetPort = targetPortContract(connection, nodes, definitions, registry);
  return Boolean(sourceType && targetPort && portTypesCompatible(sourceType, targetPort.typeId, registry));
}
