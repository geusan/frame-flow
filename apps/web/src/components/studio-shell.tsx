"use client";

import { useEffect, useState } from "react";

import {
  Boxes,
  CircleHelp,
  FileStack,
  FolderOpen,
  GalleryVerticalEnd,
  Play,
  Sparkles,
  Workflow,
} from "lucide-react";
import { useStudioStore } from "@/lib/store";
import { API_BASE, frameflowApi, type WorkspaceSummary } from "@/lib/api";
import type { StudioView } from "@/lib/types";
import { GenerationCanvas } from "./views/generation-canvas";
import { CanvasLibrary } from "./views/canvas-library";
import { AssetLibrary } from "./views/asset-library";
import { ReferenceLibrary } from "./views/reference-library";
import { FormatLab } from "./views/format-lab";
import { RunsView } from "./views/runs-view";
import { ModelRegistry } from "./views/model-registry";

const navigation: Array<{ id: StudioView; label: string; icon: typeof Workflow }> = [
  { id: "canvas", label: "Canvas", icon: Workflow },
  { id: "assets", label: "Assets", icon: FolderOpen },
  { id: "references", label: "References", icon: GalleryVerticalEnd },
  { id: "formats", label: "Format Lab", icon: FileStack },
  { id: "runs", label: "Runs", icon: Play },
  { id: "models", label: "Models", icon: Boxes },
];

const titles: Record<StudioView, { eyebrow: string; title: string }> = {
  canvas: { eyebrow: "Workspace canvases", title: "Canvases" },
  "canvas-editor": { eyebrow: "Canvas editor", title: "Workflow Canvas" },
  assets: { eyebrow: "Workspace media", title: "Asset Library" },
  references: { eyebrow: "Reference intelligence", title: "Reference Library" },
  formats: { eyebrow: "Reusable format system", title: "Format Lab" },
  runs: { eyebrow: "Execution & recovery", title: "Runs" },
  models: { eyebrow: "Provider abstraction", title: "Model Registry" },
};

export function StudioShell() {
  const view = useStudioStore((state) => state.view);
  const setView = useStudioStore((state) => state.setView);
  const selectedCanvasId = useStudioStore((state) => state.selectedCanvasId);
  const openCanvas = useStudioStore((state) => state.openCanvas);
  const [apiStatus, setApiStatus] = useState<{ connected: boolean; googleConfigured: boolean; openaiConfigured: boolean } | null>(null);
  const [workspace, setWorkspace] = useState<WorkspaceSummary | null>(null);

  useEffect(() => {
    let active = true;
    Promise.all([frameflowApi.health(), frameflowApi.workspaceSummary()])
      .then(([health, summary]) => { if (active) { setApiStatus({ connected: true, googleConfigured: health.google_configured, openaiConfigured: health.openai_configured }); setWorkspace(summary); } })
      .catch(() => { if (active) setApiStatus({ connected: false, googleConfigured: false, openaiConfigured: false }); });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    let active = true;
    frameflowApi.workspaceSummary().then((summary) => { if (active) setWorkspace(summary); }).catch(() => undefined);
    return () => { active = false; };
  }, [view]);

  useEffect(() => {
    const refreshWorkspace = () => { void frameflowApi.workspaceSummary().then(setWorkspace).catch(() => undefined); };
    window.addEventListener("frameflow:workspace-changed", refreshWorkspace);
    return () => window.removeEventListener("frameflow:workspace-changed", refreshWorkspace);
  }, []);

  return (
    <div className="studio-shell">
      <aside className="sidebar">
        <div className="brand-mark" aria-label="Frameflow home">
          <span className="brand-glyph"><Sparkles size={17} strokeWidth={2.4} /></span>
          <span className="brand-name">frameflow</span>
        </div>

        <div className="workspace-switcher">
          <span className="workspace-avatar">FF</span>
          <span className="workspace-copy">
            <strong>{workspace?.service ?? "Connecting…"}</strong>
            <small>{workspace ? `${workspace.environment} · ${workspace.storage_provider} · ${workspace.execution_backend}` : "Loading workspace state"}</small>
          </span>
        </div>

        <nav className="main-nav" aria-label="Main navigation">
          <span className="nav-label">Workspace</span>
          {navigation.map(({ id, label, icon: Icon }) => (
            <button
              type="button"
              key={id}
              className={`nav-item ${view === id || (id === "canvas" && view === "canvas-editor") ? "active" : ""}`}
              onClick={() => setView(id)}
            >
              <Icon size={17} strokeWidth={1.9} />
              <span>{label}</span>
              {workspace && id === "canvas" && <span className="nav-count">{workspace.canvases}</span>}
              {workspace && id === "assets" && <span className="nav-count">{workspace.images + workspace.videos}</span>}
              {workspace && id === "references" && <span className="nav-count">{workspace.references}</span>}
              {workspace && id === "formats" && <span className="nav-count">{workspace.formats}</span>}
              {workspace && id === "runs" && <span className="nav-count">{workspace.runs}</span>}
            </button>
          ))}
        </nav>

        <div className="sidebar-bottom">
          <button type="button" className="nav-item" onClick={() => window.open(`${API_BASE}/docs`, "_blank", "noopener,noreferrer")}><CircleHelp size={17} /><span>API docs</span></button>
        </div>
      </aside>

      <main className="main-stage">
        <header className="topbar">
          <div className="page-identity">
            <span className="page-eyebrow">{titles[view].eyebrow}</span>
            <h1>{titles[view].title}</h1>
          </div>
          <div className="topbar-actions">
            <span className={`api-indicator ${apiStatus?.connected ? "connected" : apiStatus?.connected === false ? "offline" : "checking"}`}><i />{apiStatus?.connected ? apiStatus.googleConfigured && apiStatus.openaiConfigured ? "API · Google + OpenAI ready" : apiStatus.googleConfigured ? "API · Google ready" : apiStatus.openaiConfigured ? "API · OpenAI ready" : "API · Provider setup required" : apiStatus?.connected === false ? "API offline" : "Checking"}</span>
          </div>
        </header>

        <section className="view-container">
          {view === "canvas" && <CanvasLibrary onOpen={openCanvas} />}
          {view === "canvas-editor" && selectedCanvasId && <GenerationCanvas canvasId={selectedCanvasId} onBack={() => setView("canvas")} key={selectedCanvasId} />}
          {view === "canvas-editor" && !selectedCanvasId && <CanvasLibrary onOpen={openCanvas} />}
          {view === "assets" && <AssetLibrary />}
          {view === "references" && <ReferenceLibrary />}
          {view === "formats" && <FormatLab />}
          {view === "runs" && <RunsView />}
          {view === "models" && <ModelRegistry />}
        </section>
      </main>
    </div>
  );
}
