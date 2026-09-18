import type { ExperimentRun, NodeDefinitionRecord } from "@/lib/api";
import type { StudioFlowNode } from "@/lib/canvas-model";

export function canRestoreExperiment(node: StudioFlowNode, experiment: ExperimentRun, definition?: NodeDefinitionRecord): boolean {
  if (node.data.key !== experiment.node_key) return false;
  // A cleared stale result marks a replaced branch, not a missing UI snapshot.
  if (node.data.status === "STALE" && !node.data.lastExperimentId) return false;
  if (definition && definition.execution.executor !== "legacy-compatibility") {
    const revision = definition.execution.revision;
    if (experiment.execution_mode !== revision && !experiment.execution_mode.startsWith(`${revision}+`)) return false;
  }
  return true;
}
