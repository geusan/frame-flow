"use client";

import { useCallback, useEffect, useState } from "react";
import { Clock3, GitBranch, Plus, RefreshCw, Trash2, Workflow } from "lucide-react";

import { ConfirmAction } from "@/components/shared/confirm-action";
import { PageHeader } from "@/components/shared/page-header";
import { Button } from "@/components/ui/button";
import { frameflowApi, type CanvasDocument } from "@/lib/api";

const LEGACY_STORAGE_KEY = "frameflow.canvas.v2";

function notifyWorkspaceChanged(): void {
  window.dispatchEvent(new Event("frameflow:workspace-changed"));
}

function isLegacyMockCanvas(nodes: Array<Record<string, unknown>>): boolean {
  return nodes.some((node) => node.id === "brief" && String((node.data as Record<string, unknown> | undefined)?.description ?? "").includes("로마 도로"))
    || nodes.some((node) => node.id === "format" && String((node.data as Record<string, unknown> | undefined)?.label ?? "") === "Contrarian History");
}

export function CanvasLibrary({ onOpen }: { onOpen: (canvasId: string) => void }) {
  const [canvases, setCanvases] = useState<CanvasDocument[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadCanvases = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setCanvases(await frameflowApi.listCanvases());
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Canvas loading failed");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let active = true;
    const loadAndMigrate = async () => {
      try {
        let records = await frameflowApi.listCanvases();
        const raw = window.localStorage.getItem(LEGACY_STORAGE_KEY);
        if (raw) {
          const graph = JSON.parse(raw) as { id?: string; name?: string; nodes?: Array<Record<string, unknown>>; edges?: Array<Record<string, unknown>>; activeRunId?: string };
          const nodes = Array.isArray(graph.nodes) ? graph.nodes : [];
          const edges = Array.isArray(graph.edges) ? graph.edges : [];
          const shouldImport = !isLegacyMockCanvas(nodes) && (nodes.length > 0 || edges.length > 0 || (graph.name && graph.name !== "Untitled canvas"));
          const canvasId = graph.id || `canvas_${Date.now().toString(36)}`;
          if (shouldImport && !records.some((record) => record.id === canvasId)) {
            await frameflowApi.saveCanvas(canvasId, { name: graph.name || "Imported canvas", nodes, edges, active_run_id: graph.activeRunId });
            records = await frameflowApi.listCanvases();
          }
          window.localStorage.removeItem(LEGACY_STORAGE_KEY);
        }
        if (active) { setCanvases(records); notifyWorkspaceChanged(); }
      } catch (loadError) {
        if (active) setError(loadError instanceof Error ? loadError.message : "Canvas loading failed");
      } finally {
        if (active) setLoading(false);
      }
    };
    void loadAndMigrate();
    return () => { active = false; };
  }, []);

  const createCanvas = async () => {
    setCreating(true);
    setError(null);
    try {
      const canvas = await frameflowApi.createCanvas();
      setCanvases((current) => [canvas, ...current]);
      notifyWorkspaceChanged();
      onOpen(canvas.id);
    } catch (createError) {
      setError(createError instanceof Error ? createError.message : "Canvas creation failed");
    } finally {
      setCreating(false);
    }
  };

  const deleteCanvas = async (canvas: CanvasDocument) => {
    try {
      await frameflowApi.deleteCanvas(canvas.id);
      setCanvases((current) => current.filter((item) => item.id !== canvas.id));
      notifyWorkspaceChanged();
    } catch (deleteError) {
      setError(deleteError instanceof Error ? deleteError.message : "Canvas deletion failed");
    }
  };

  return <div className="view-page canvas-library-page">
    <PageHeader title="Canvases" description="DB에 저장된 실제 Canvas 문서를 열거나 새 Workflow를 만듭니다." actions={<><Button type="button" variant="secondary" onClick={() => void loadCanvases()} disabled={loading}><RefreshCw size={14} className={loading ? "spin" : ""} /> Refresh</Button><Button type="button" onClick={() => void createCanvas()} disabled={creating}><Plus size={14} /> {creating ? "Creating…" : "New canvas"}</Button></>} />
    {error && <p className="experiment-history-state error">{error}</p>}
    {!error && loading && <p className="experiment-history-state">Loading persisted canvases…</p>}
    {!error && !loading && !canvases.length && <div className="canvas-library-empty"><span><Workflow size={24} /></span><strong>No saved canvases</strong><p>새 Canvas를 만들면 그래프가 PostgreSQL에 자동 저장됩니다.</p><Button type="button" onClick={() => void createCanvas()}><Plus size={14} /> Create first canvas</Button></div>}
    <div className="canvas-document-grid">{canvases.map((canvas) => <article className="canvas-document-card" key={canvas.id}>
      <button type="button" className="canvas-document-open" onClick={() => onOpen(canvas.id)}>
        <span className="canvas-document-icon"><Workflow size={18} /></span>
        <span className="canvas-document-copy"><strong>{canvas.name}</strong><small>{canvas.id}</small></span>
        <span className="canvas-document-count"><b>{canvas.node_count}</b><small>nodes</small></span>
      </button>
      <div className="canvas-document-meta"><span><GitBranch size={12} /> {canvas.edge_count} connections</span><span><Clock3 size={12} /> {new Date(canvas.updated_at).toLocaleString("ko-KR")}</span></div>
      <div className="canvas-document-footer"><span>{canvas.last_run ? <><i className={`run-dot status-${canvas.last_run.status.toLowerCase()}`} /> Last run · {canvas.last_run.status} · {canvas.last_run.progress}%</> : "No runs yet"}</span><ConfirmAction trigger={<button type="button" aria-label={`Delete ${canvas.name}`}><Trash2 size={13} /></button>} title={`Delete “${canvas.name}”?`} description="Canvas runs and artifacts remain immutable, but this canvas document will be removed." confirmLabel="Delete canvas" onConfirm={() => deleteCanvas(canvas)} /></div>
    </article>)}</div>
  </div>;
}
