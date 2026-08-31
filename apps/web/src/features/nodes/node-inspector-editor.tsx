import type { Edge } from "@xyflow/react";

import { GenericNodeInspector } from "@/features/nodes/generic-inspector";
import {
  ConnectedPromptPreview,
  ProviderModelFields,
  renderCustomEditor,
} from "@/features/nodes/custom-editors/registry";
import type { StudioFlowNode } from "@/lib/canvas-model";
import type { ModelRecord, NodeDefinitionRecord, ProjectSkillRecord } from "@/lib/api";

interface NodeInspectorEditorProps {
  node: StudioFlowNode;
  definition?: NodeDefinitionRecord;
  nodes: StudioFlowNode[];
  edges: Edge[];
  models: ModelRecord[];
  projectSkills: ProjectSkillRecord[];
  activeCanvasRunId: string | null;
  onChange: (patch: Partial<StudioFlowNode["data"]>) => void;
  onApproveCaptionLayout: () => void;
  onOpenCandidate: () => void;
}

function ReadOnlyEditorFallback({ node, definition }: { node: StudioFlowNode; definition?: NodeDefinitionRecord }) {
  return <div className="generic-node-settings">
    <div className="editor-input-count connected">
      <span>Contract</span>
      <strong>{definition ? `${definition.type_key}@${definition.contract_version}` : `${node.data.key}@${node.data.contractVersion ?? 1}`}</strong>
      <small>{definition ? `${definition.execution.provider} · ${definition.execution.model_alias}` : "Definition unavailable"}</small>
    </div>
    <p className="step-run-help">이 계약에 등록된 Custom Editor가 없어 저장된 설정을 읽기 전용으로 표시합니다.</p>
    <pre className="max-h-40 overflow-auto rounded-md border border-[#d8dad3] bg-[#f7f7f3] p-2 text-[10px] text-[#5d6158]">{JSON.stringify(node.data.config ?? {}, null, 2)}</pre>
  </div>;
}

export function NodeInspectorEditor(props: NodeInspectorEditorProps) {
  const { node, definition, nodes, edges, models, onChange } = props;
  if (!definition) return <ReadOnlyEditorFallback node={node} />;

  if (definition.editor.kind === "generic") {
    return <>
      <GenericNodeInspector
        definition={definition}
        value={node.data.config ?? {}}
        hiddenFields={definition.execution.kind === "provider" ? ["model_alias"] : []}
        onChange={(config) => onChange({
          config,
          ...(typeof config.model_alias === "string" ? { model: config.model_alias } : {}),
          status: node.data.output || node.data.outputArtifactIds?.length ? "STALE" : node.data.status,
        })}
      />
      {definition.execution.kind === "provider" && <div className="generator-settings">
        <ConnectedPromptPreview node={node} definition={definition} nodes={nodes} edges={edges} />
        <ProviderModelFields node={node} definition={definition} models={models} onChange={onChange} />
      </div>}
    </>;
  }

  const customEditor = renderCustomEditor(definition, { ...props, definition });
  return customEditor ?? <ReadOnlyEditorFallback node={node} definition={definition} />;
}
