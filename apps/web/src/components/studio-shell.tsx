"use client";

import { useEffect, useState } from "react";

import {
  Boxes,
  ChevronsUpDown,
  CircleHelp,
  FileStack,
  GalleryVerticalEnd,
  LayoutDashboard,
  PanelLeftClose,
  Play,
  Search,
  Settings,
  Sparkles,
  Workflow,
} from "lucide-react";
import { useStudioStore } from "@/lib/store";
import { frameflowApi } from "@/lib/api";
import type { StudioView } from "@/lib/types";
import { GenerationCanvas } from "./views/generation-canvas";
import { ReferenceLibrary } from "./views/reference-library";
import { FormatLab } from "./views/format-lab";
import { RunsView } from "./views/runs-view";
import { ModelRegistry } from "./views/model-registry";

const navigation: Array<{ id: StudioView; label: string; icon: typeof Workflow }> = [
  { id: "canvas", label: "Canvas", icon: Workflow },
  { id: "references", label: "References", icon: GalleryVerticalEnd },
  { id: "formats", label: "Format Lab", icon: FileStack },
  { id: "runs", label: "Runs", icon: Play },
  { id: "models", label: "Models", icon: Boxes },
];

const titles: Record<StudioView, { eyebrow: string; title: string }> = {
  canvas: { eyebrow: "Generation canvas", title: "Shorts Production" },
  references: { eyebrow: "Reference intelligence", title: "Reference Library" },
  formats: { eyebrow: "Reusable format system", title: "Format Lab" },
  runs: { eyebrow: "Execution & recovery", title: "Runs" },
  models: { eyebrow: "Provider abstraction", title: "Model Registry" },
};

export function StudioShell() {
  const view = useStudioStore((state) => state.view);
  const setView = useStudioStore((state) => state.setView);
  const [apiConnected, setApiConnected] = useState<boolean | null>(null);

  useEffect(() => {
    let active = true;
    frameflowApi.health().then(() => active && setApiConnected(true)).catch(() => active && setApiConnected(false));
    return () => { active = false; };
  }, []);

  return (
    <div className="studio-shell">
      <aside className="sidebar">
        <div className="brand-mark" aria-label="Frameflow home">
          <span className="brand-glyph"><Sparkles size={17} strokeWidth={2.4} /></span>
          <span className="brand-name">frameflow</span>
        </div>

        <button className="workspace-switcher" type="button">
          <span className="workspace-avatar">OS</span>
          <span className="workspace-copy">
            <strong>Ocho Studio</strong>
            <small>Production workspace</small>
          </span>
          <ChevronsUpDown size={14} />
        </button>

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
          <button type="button" className="nav-item"><CircleHelp size={17} /><span>Help & docs</span></button>
          <button type="button" className="nav-item"><Settings size={17} /><span>Settings</span></button>
          <button type="button" className="user-chip">
            <span className="user-avatar">GK</span>
            <span><strong>Geusan Kim</strong><small>Owner</small></span>
            <ChevronsUpDown size={14} />
          </button>
        </div>
      </aside>

      <main className="main-stage">
        <header className="topbar">
          <div className="page-identity">
            <span className="page-eyebrow">{titles[view].eyebrow}</span>
            <h1>{titles[view].title}</h1>
          </div>
          <div className="topbar-actions">
            <span className={`api-indicator ${apiConnected ? "connected" : apiConnected === false ? "offline" : "checking"}`}><i />{apiConnected ? "API connected" : apiConnected === false ? "Demo mode" : "Checking"}</span>
            <button className="icon-button" type="button" aria-label="Search"><Search size={17} /></button>
            <span className="kbd-hint"><span>⌘</span> K</span>
            <div className="topbar-separator" />
            <button className="icon-button" type="button" aria-label="Collapse sidebar"><PanelLeftClose size={17} /></button>
            <button className="ghost-button" type="button"><LayoutDashboard size={15} /> Overview</button>
          </div>
        </header>

        <section className="view-container">
          {view === "canvas" && <GenerationCanvas />}
          {view === "references" && <ReferenceLibrary />}
          {view === "formats" && <FormatLab />}
          {view === "runs" && <RunsView />}
          {view === "models" && <ModelRegistry />}
        </section>
      </main>
    </div>
  );
}
