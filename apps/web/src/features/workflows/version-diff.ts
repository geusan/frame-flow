import type { WorkflowVersionRecord } from "@/lib/api";

export interface VersionChange { path: string; before: unknown; after: unknown }

/** Compare persisted versions only; Registry defaults and mutable notes are excluded. */
export function workflowVersionDiff(before: WorkflowVersionRecord, after: WorkflowVersionRecord): VersionChange[] {
  const changes: VersionChange[] = [];
  const keyed = (items: Array<Record<string, unknown>>, key: string) => Object.fromEntries(items.map((item) => [String(item[key]), item]));
  const shape = (version: WorkflowVersionRecord) => ({
    nodes: keyed(version.graph.nodes, "id"), edges: keyed(version.graph.edges, "id"),
    inputs: keyed(version.input_schema.inputs as unknown as Array<Record<string, unknown>>, "key"),
    bindings: version.bindings.bindings,
    outputs: keyed(version.output_schema.outputs as unknown as Array<Record<string, unknown>>, "key"),
  });
  const walk = (a: unknown, b: unknown, path: string) => {
    if (Object.is(a, b)) return;
    if (a && b && typeof a === "object" && typeof b === "object" && !Array.isArray(a) && !Array.isArray(b)) {
      for (const key of [...new Set([...Object.keys(a), ...Object.keys(b)])].sort()) walk((a as Record<string, unknown>)[key], (b as Record<string, unknown>)[key], path ? `${path}.${key}` : key);
    } else if (JSON.stringify(a) !== JSON.stringify(b)) changes.push({ path, before: a, after: b });
  };
  walk(shape(before), shape(after), "");
  return changes;
}
