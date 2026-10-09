import type { Edge } from "@xyflow/react";
import type { NodeTemplate, StudioFlowNode } from "../../lib/canvas-model";

/** Read adapter only: loading never upgrades a contract or discards a Node/Edge. */
export function migrateStoredGraph<T extends { nodes: StudioFlowNode[]; edges: Edge[] }>(graph: T, templates: NodeTemplate[] = []): T {
  return {
    ...graph,
    nodes: graph.nodes.map((node) => {
      const version = node.data.contractVersion ?? 1;
      const template = templates.find((item) => item.data.key === node.data.key && (item.data.contractVersion ?? 1) === version);
      if (!template) return { ...node, type: "studio", data: { ...node.data, icon: node.data.icon ?? "brief", kind: node.data.kind ?? "logic", status: node.data.status ?? "BLOCKED", label: node.data.label ?? node.data.key, description: node.data.description ?? "Unavailable Node contract", executable: false } };
      return {
        ...node,
        type: "studio",
        data: {
          ...template.data,
          ...node.data,
          contractVersion: template.data.contractVersion ?? node.data.contractVersion,
          definitionDigest: node.data.definitionDigest ?? template.data.definitionDigest,
          config: { ...template.data.config, ...node.data.config },
          inputPorts: template.data.inputPorts,
          outputPorts: template.data.outputPorts,
          inputTypes: template.data.inputTypes,
          requiredInputTypes: template.data.requiredInputTypes,
          multiInputTypes: template.data.multiInputTypes,
          inputsRequired: template.data.inputsRequired,
          executable: template.data.executable,
          waitForInput: template.data.waitForInput,
        },
      };
    }),
    edges: graph.edges.map((edge) => ({ ...edge, type: !edge.type || edge.type === "smoothstep" ? "adaptive" : edge.type })),
  };
}
