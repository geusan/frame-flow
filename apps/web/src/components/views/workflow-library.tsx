"use client";

import { useCallback, useEffect, useState } from "react";
import { Archive, Clock3, GitBranch, Pencil, Play, Plus, RefreshCw, Workflow } from "lucide-react";

import { PageHeader } from "@/components/shared/page-header";
import { Button } from "@/components/ui/button";
import { frameflowApi, type WorkflowDefinitionRecord } from "@/lib/api";

export function WorkflowLibrary({ onOpen, onEditDraft }: {
  onOpen: (workflowId: string) => void;
  onEditDraft: (canvasId: string) => void;
}) {
  const [workflows, setWorkflows] = useState<WorkflowDefinitionRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setWorkflows(await frameflowApi.listWorkflows());
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Workflow loading failed");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let active = true;
    frameflowApi.listWorkflows()
      .then((items) => { if (active) setWorkflows(items); })
      .catch((loadError) => { if (active) setError(loadError instanceof Error ? loadError.message : "Workflow loading failed"); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  const create = async () => {
    setCreating(true);
    setError(null);
    try {
      const workflow = await frameflowApi.createWorkflow({ name: "Untitled workflow" });
      setWorkflows((current) => [workflow, ...current]);
      window.dispatchEvent(new Event("frameflow:workspace-changed"));
      onEditDraft(workflow.draft_canvas_id);
    } catch (createError) {
      setError(createError instanceof Error ? createError.message : "Workflow creation failed");
    } finally {
      setCreating(false);
    }
  };

  return <div className="view-page canvas-library-page">
    <PageHeader title="Workflows" description="Canvas Draft를 불변 Version으로 게시하고 입력값을 바꿔 반복 실행합니다." actions={<>
      <Button type="button" variant="secondary" onClick={() => void load()} disabled={loading}><RefreshCw size={14} className={loading ? "spin" : ""} /> Refresh</Button>
      <Button type="button" onClick={() => void create()} disabled={creating}><Plus size={14} /> {creating ? "Creating…" : "New workflow"}</Button>
    </>} />
    {error && <p className="experiment-history-state error">{error}</p>}
    {!error && loading && <p className="experiment-history-state">Loading workflows…</p>}
    {!error && !loading && !workflows.length && <div className="canvas-library-empty"><span><Workflow size={24} /></span><strong>No managed workflows</strong><p>새 Workflow는 편집 가능한 Draft Canvas와 함께 만들어집니다.</p><Button type="button" onClick={() => void create()}><Plus size={14} /> Create first workflow</Button></div>}
    <div className="canvas-document-grid">{workflows.map((workflow) => <article className="canvas-document-card" key={workflow.id}>
      <button type="button" className="canvas-document-open" onClick={() => onOpen(workflow.id)}>
        <span className="canvas-document-icon"><Workflow size={18} /></span>
        <span className="canvas-document-copy"><strong>{workflow.name}</strong><small>{workflow.description || workflow.id}</small></span>
        <span className="canvas-document-count"><b>{workflow.current_version_number ? `v${workflow.current_version_number}` : "Draft"}</b><small>{workflow.version_count} versions</small></span>
      </button>
      <div className="canvas-document-meta"><span><GitBranch size={12} /> {workflow.current_version_id ? "Published" : "Not published"}</span><span><Clock3 size={12} /> {new Date(workflow.updated_at).toLocaleString("ko-KR")}</span></div>
      <div className="canvas-document-footer"><span>{workflow.status === "ARCHIVED" ? <><Archive size={12} /> Archived</> : workflow.current_version_id ? <><Play size={12} /> Ready to run</> : "Draft only"}</span><Button type="button" variant="ghost" size="sm" onClick={() => onEditDraft(workflow.draft_canvas_id)}><Pencil size={13} /> Edit draft</Button></div>
    </article>)}</div>
  </div>;
}
