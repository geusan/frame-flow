"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { Background, BackgroundVariant, Controls, Handle, MiniMap, Position, ReactFlow, ReactFlowProvider, useEdgesState, useNodesState, type Edge, type Node, type NodeProps } from "@xyflow/react";
import { ArrowLeft, GitBranch, MessageSquarePlus, Pencil, Play, Save, Trash2 } from "lucide-react";

import { PageHeader } from "@/components/shared/page-header";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { frameflowApi, type WorkflowAnnotationRecord, type WorkflowVersionRecord } from "@/lib/api";

type FrozenNodeData = Record<string, unknown> & { label: string; typeKey: string; contractVersion: number; config: Record<string, unknown> };
type AnnotationNodeData = Record<string, unknown> & { annotation: WorkflowAnnotationRecord };
type VersionFlowNode = Node<FrozenNodeData, "frozen"> | Node<AnnotationNodeData, "annotation">;

const AnnotationActions = createContext<{
  update: (annotation: WorkflowAnnotationRecord, body: string) => void;
  remove: (annotation: WorkflowAnnotationRecord) => void;
}>({
  update: () => undefined,
  remove: () => undefined,
});

function FrozenNode({ data }: NodeProps<Node<FrozenNodeData, "frozen">>) {
  return <article className="min-w-56 rounded-xl border border-[#d8d9d3] bg-white p-3 shadow-[0_8px_24px_rgba(30,32,29,.08)]">
    <Handle type="target" position={Position.Left} id="target" className="typed-handle type-any" />
    <div className="mb-2 flex items-start justify-between gap-3"><span><small className="block text-[10px] uppercase tracking-[.08em] text-[#8c8f87]">{data.typeKey}</small><strong className="text-sm text-[#252722]">{data.label}</strong></span><b className="rounded-md bg-[#eef0e9] px-1.5 py-0.5 text-[10px] text-[#62665d]">@{data.contractVersion}</b></div>
    <div className="flex flex-wrap gap-1">{Object.entries(data.config).slice(0, 4).map(([key, value]) => <span className="rounded bg-[#f4f5f1] px-1.5 py-1 text-[10px] text-[#6f736a]" key={key}>{key}: {String(value)}</span>)}</div>
    <Handle type="source" position={Position.Right} id="source" className="typed-handle type-any" />
  </article>;
}

function AnnotationNode({ data }: NodeProps<Node<AnnotationNodeData, "annotation">>) {
  const actions = useContext(AnnotationActions);
  const [body, setBody] = useState(data.annotation.body);
  return <article className="nodrag min-w-52 rounded-lg border border-[#e0c96d] bg-[#fff4ac] p-2.5 shadow-[0_8px_20px_rgba(80,68,20,.12)]">
    <div className="mb-1.5 flex items-center justify-between"><small className="text-[10px] font-bold uppercase tracking-[.08em] text-[#89762d]">Editable memo</small><button type="button" onClick={() => actions.remove(data.annotation)} aria-label="Delete memo"><Trash2 size={12} /></button></div>
    <Textarea className="nowheel min-h-20 border-0 bg-transparent p-0 text-xs shadow-none focus-visible:ring-0" value={body} onChange={(event) => setBody(event.target.value)} onBlur={() => { if (body.trim() && body !== data.annotation.body) actions.update(data.annotation, body.trim()); }} />
    <small className="mt-1 flex items-center gap-1 text-[10px] text-[#8a7b42]"><Save size={10} /> blur to save · revision {data.annotation.revision}</small>
  </article>;
}

const versionNodeTypes = { frozen: FrozenNode, annotation: AnnotationNode };

function versionFlowState(record: WorkflowVersionRecord, annotations: WorkflowAnnotationRecord[]): { nodes: VersionFlowNode[]; edges: Edge[] } {
  const frozen: VersionFlowNode[] = record.graph.nodes.map((raw) => {
    const node = raw as { id: string; type_key: string; contract_version: number; config: Record<string, unknown>; ui?: { position?: { x?: number; y?: number }; label?: string } };
    return {
      id: node.id,
      type: "frozen",
      position: { x: Number(node.ui?.position?.x ?? 0), y: Number(node.ui?.position?.y ?? 0) },
      draggable: false,
      selectable: true,
      data: { label: node.ui?.label ?? node.type_key, typeKey: node.type_key, contractVersion: node.contract_version, config: node.config },
    };
  });
  const memoNodes: VersionFlowNode[] = annotations.map((annotation, index) => ({
    id: `annotation:${annotation.id}`,
    type: "annotation",
    position: { x: Number(annotation.position.x ?? 40 + index * 24), y: Number(annotation.position.y ?? 420 + index * 24) },
    draggable: true,
    data: { annotation },
  }));
  const edges: Edge[] = record.graph.edges.map((raw) => {
    const edge = raw as { id: string; source: string; target: string };
    return { id: edge.id, source: edge.source, target: edge.target, sourceHandle: "source", targetHandle: "target", type: "smoothstep", style: { stroke: "#999d93", strokeWidth: 1.4 } };
  });
  return { nodes: [...frozen, ...memoNodes], edges };
}

export function WorkflowVersionView({ workflowId, versionNumber, onBack, onEditDraft, onRun }: {
  workflowId: string;
  versionNumber: number;
  onBack: () => void;
  onEditDraft: (canvasId: string) => void;
  onRun: () => void;
}) {
  return <ReactFlowProvider><WorkflowVersionFlow workflowId={workflowId} versionNumber={versionNumber} onBack={onBack} onEditDraft={onEditDraft} onRun={onRun} /></ReactFlowProvider>;
}

function WorkflowVersionFlow({ workflowId, versionNumber, onBack, onEditDraft, onRun }: {
  workflowId: string;
  versionNumber: number;
  onBack: () => void;
  onEditDraft: (canvasId: string) => void;
  onRun: () => void;
}) {
  const [version, setVersion] = useState<WorkflowVersionRecord | null>(null);
  const [nodes, setNodes, onNodesChange] = useNodesState<VersionFlowNode>([]);
  const [edges, setEdges] = useEdgesState<Edge>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    Promise.all([
      frameflowApi.getWorkflowVersion(workflowId, versionNumber),
      frameflowApi.listWorkflowVersionAnnotations(workflowId, versionNumber),
    ]).then(([record, annotations]) => {
      if (!active) return;
      const flow = versionFlowState(record, annotations);
      setVersion(record);
      setNodes(flow.nodes);
      setEdges(flow.edges);
    }).catch((loadError) => { if (active) setError(loadError instanceof Error ? loadError.message : "Workflow Version loading failed"); });
    return () => { active = false; };
  }, [setEdges, setNodes, versionNumber, workflowId]);

  const updateAnnotation = useCallback((annotation: WorkflowAnnotationRecord, body: string) => {
    void frameflowApi.updateWorkflowAnnotation(annotation.id, { expected_revision: annotation.revision, body })
      .then((updated) => setNodes((current) => current.map((node) => node.id === `annotation:${annotation.id}` ? { ...node, data: { annotation: updated } } as VersionFlowNode : node)))
      .catch((updateError) => setError(updateError instanceof Error ? updateError.message : "Memo update failed"));
  }, [setNodes]);
  const removeAnnotation = useCallback((annotation: WorkflowAnnotationRecord) => {
    void frameflowApi.deleteWorkflowAnnotation(annotation.id)
      .then(() => setNodes((current) => current.filter((node) => node.id !== `annotation:${annotation.id}`)))
      .catch((deleteError) => setError(deleteError instanceof Error ? deleteError.message : "Memo deletion failed"));
  }, [setNodes]);
  const actions = useMemo(() => ({ update: updateAnnotation, remove: removeAnnotation }), [removeAnnotation, updateAnnotation]);

  const addMemo = async () => {
    try {
      const annotation = await frameflowApi.createWorkflowVersionAnnotation(workflowId, versionNumber, { body: "New memo", position: { x: 60, y: 420 }, color: "yellow" });
      setNodes((current) => [...current, { id: `annotation:${annotation.id}`, type: "annotation", position: { x: 60, y: 420 }, draggable: true, data: { annotation } }]);
    } catch (createError) {
      setError(createError instanceof Error ? createError.message : "Memo creation failed");
    }
  };

  return <div className="view-page flex h-[calc(100vh-106px)] min-h-[620px] flex-col gap-3">
    <PageHeader title={version ? `Workflow v${version.version_number}` : "Workflow Version"} description={version ? `Frozen graph · ${version.content_hash.slice(0, 16)} · memos remain editable` : "Loading immutable graph…"} actions={<>
      <Button type="button" variant="secondary" onClick={onBack}><ArrowLeft size={14} /> Workflow</Button>
      {version && <Button type="button" variant="secondary" onClick={() => onEditDraft(version.source_canvas_id)}><Pencil size={14} /> Edit as draft</Button>}
      <Button type="button" variant="secondary" onClick={() => void addMemo()}><MessageSquarePlus size={14} /> Add memo</Button>
      <Button type="button" onClick={onRun}><Play size={14} fill="currentColor" /> Run</Button>
    </>} />
    {error && <p className="experiment-history-state error">{error}</p>}
    <AnnotationActions.Provider value={actions}><div className="min-h-0 flex-1 overflow-hidden rounded-xl border border-[#d9dad4] bg-[#f7f7f3]">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={versionNodeTypes}
        onNodesChange={onNodesChange}
        onNodeDragStop={(_, node) => {
          if (node.type !== "annotation") return;
          const annotation = (node.data as AnnotationNodeData).annotation;
          void frameflowApi.updateWorkflowAnnotation(annotation.id, { expected_revision: annotation.revision, position: node.position }).then((updated) => setNodes((current) => current.map((item) => item.id === node.id ? { ...item, data: { annotation: updated } } as VersionFlowNode : item))).catch((dragError) => setError(dragError instanceof Error ? dragError.message : "Memo move failed"));
        }}
        nodesConnectable={false}
        elementsSelectable
        fitView
        fitViewOptions={{ padding: 0.18 }}
        minZoom={0.25}
        maxZoom={1.5}
        proOptions={{ hideAttribution: true }}
      >
        <Background variant={BackgroundVariant.Dots} gap={18} size={1} color="#c9cbc4" />
        <Controls showInteractive={false} />
        <MiniMap nodeColor={(node) => node.type === "annotation" ? "#efd86f" : "#7a75d2"} maskColor="rgba(246,246,243,.72)" />
        <div className="absolute bottom-4 left-4 z-10 flex items-center gap-2 rounded-lg border border-[#d8d9d3] bg-white/90 px-2.5 py-2 text-[11px] text-[#6b6f66]"><GitBranch size={13} /> Frozen graph · yellow memos are editable</div>
      </ReactFlow>
    </div></AnnotationActions.Provider>
  </div>;
}
