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
import { frameflowApi } from "@/lib/api";
import type { StudioView } from "@/lib/types";
import { GenerationCanvas } from "./views/generation-canvas";
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
  canvas: { eyebrow: "Generation canvas", title: "Shorts Production" },
  assets: { eyebrow: "Workspace media", title: "Asset Library" },
  references: { eyebrow: "Reference intelligence", title: "Reference Library" },
  formats: { eyebrow: "Reusable format system", title: "Format Lab" },
  runs: { eyebrow: "Execution & recovery", title: "Runs" },
  models: { eyebrow: "Provider abstraction", title: "Model Registry" },
};

export function StudioShell() {
  const view = useStudioStore((state) => state.view);
  const setView = useStudioStore((state) => state.setView);
  const [apiStatus, setApiStatus] = useState<{ connected: boolean; googleConfigured: boolean; openaiConfigured: boolean } | null>(null);

  useEffect(() => {
    let active = true;
    frameflowApi.health().then((health) => active && setApiStatus({ connected: true, googleConfigured: health.google_configured, openaiConfigured: health.openai_configured })).catch(() => active && setApiStatus({ connected: false, googleConfigured: false, openaiConfigured: false }));
    return () => { active = false; };
  }, []);

  return (
    <div className="studio-shell">
      <aside className="sidebar">
        <div className="brand-mark" aria-label="Frameflow home">
          <span className="brand-glyph"><Sparkles size={17} strokeWidth={2.4} /></span>
          <span className="brand-name">frameflow</span>
        </div>

        <div className="workspace-switcher">
          <span className="workspace-avatar">OS</span>
          <span className="workspace-copy">
            <strong>Ocho Studio</strong>
            <small>Production workspace</small>
          </span>
        </div>

        <nav className="main-nav" aria-label="Main navigation">
          <span className="nav-label">Workspace</span>
          {navigation.map(({ id, label, icon: Icon }) => (
            <button
              type="button"
              key={id}
              className={`nav-item ${view === id ? "active" : ""}`}
              onClick={() => setView(id)}
            >
              <Icon size={17} strokeWidth={1.9} />
              <span>{label}</span>
              {id === "runs" && <span className="nav-count">3</span>}
            </button>
          ))}
        </nav>

        <div className="sidebar-bottom">
          <button type="button" className="nav-item" onClick={() => window.open("http://localhost:8000/docs", "_blank", "noopener,noreferrer")}><CircleHelp size={17} /><span>API docs</span></button>
          <div className="user-chip">
            <span className="user-avatar">GK</span>
            <span><strong>Geusan Kim</strong><small>Owner</small></span>
          </div>
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
          {view === "canvas" && <GenerationCanvas />}
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
