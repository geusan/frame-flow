"use client";
import { useStudioRuntime } from "../runtime/studio-runtime";


import { useEffect, useState, type ReactNode } from "react";
import { usePathname } from "next/navigation";

import { StudioSidebar } from "./layout/studio-sidebar";
import { type CanvasDocument, type WorkspaceSummary } from "../lib/api";

function pageTitle(pathname: string): { eyebrow: string; title: string } {
  if (pathname === "/live-avatar/2d/shoulder") return { eyebrow: "Isolated joint study", title: "Shoulder Lab" };
  if (pathname.startsWith("/live-avatar")) return { eyebrow: "Local webcam session", title: "Live Avatar" };
  if (pathname.startsWith("/canvases/")) return { eyebrow: "Canvas editor", title: "Canvas Draft" };
  if (pathname === "/canvases") return { eyebrow: "Workspace drafts", title: "Canvases" };
  if (pathname.startsWith("/workflows/")) return { eyebrow: "Versioned automation", title: "Workflow" };
  if (pathname === "/workflows") return { eyebrow: "Published automation", title: "Workflows" };
  if (pathname.startsWith("/characters")) return { eyebrow: "Reusable identity bundles", title: "Characters" };
  if (pathname.startsWith("/asset/images/") && pathname.endsWith("/edit")) return { eyebrow: "Image workspace", title: "Image Editor" };
  if (pathname.startsWith("/asset/images")) return { eyebrow: "Workspace assets", title: "Image Gallery" };
  if (pathname.startsWith("/asset/videos")) return { eyebrow: "Workspace assets", title: "Video Gallery" };
  if (pathname.startsWith("/asset/audio")) return { eyebrow: "Workspace assets", title: "Audio Library" };
  if (pathname === "/references") return { eyebrow: "Reference collection", title: "References" };
  if (pathname.startsWith("/reference-results")) return { eyebrow: "Reference intelligence", title: "Reference Results" };
  if (pathname === "/runs") return { eyebrow: "Execution & recovery", title: "Runs" };
  if (pathname === "/settings/storage") return { eyebrow: "Storage providers", title: "File storage" };
  if (pathname === "/settings/models") return { eyebrow: "Provider abstraction", title: "Model Registry" };
  if (pathname === "/settings/skills") return { eyebrow: "Trusted execution", title: "Skill Registry" };
  return { eyebrow: "Workspace configuration", title: "Settings" };
}

export function StudioShell({ children }: { children: ReactNode }) {
  const { frameflowApi } = useStudioRuntime();
  const pathname = usePathname();
  const title = pageTitle(pathname);
  const [apiStatus, setApiStatus] = useState<{ connected: boolean; googleConfigured: boolean; openaiConfigured: boolean } | null>(null);
  const [workspace, setWorkspace] = useState<WorkspaceSummary | null>(null);
  const [canvases, setCanvases] = useState<CanvasDocument[]>([]);

  useEffect(() => {
    let active = true;
    Promise.all([frameflowApi.health(), frameflowApi.workspaceSummary()])
      .then(([health, summary]) => {
        if (!active) return;
        setApiStatus({ connected: true, googleConfigured: health.google_configured, openaiConfigured: health.openai_configured });
        setWorkspace(summary);
      })
      .catch(() => {
        if (active) setApiStatus({ connected: false, googleConfigured: false, openaiConfigured: false });
      });
    return () => { active = false; };
  }, [frameflowApi]);

  useEffect(() => {
    let active = true;
    Promise.all([
      frameflowApi.workspaceSummary().catch(() => null),
      frameflowApi.listCanvases().catch(() => null),
    ]).then(([summary, canvasItems]) => {
      if (!active) return;
      if (summary) setWorkspace(summary);
      if (canvasItems) setCanvases(canvasItems);
    });
    return () => { active = false; };
  }, [pathname, frameflowApi]);

  useEffect(() => {
    const refreshWorkspace = () => {
      void frameflowApi.workspaceSummary().then(setWorkspace).catch(() => undefined);
      void frameflowApi.listCanvases().then(setCanvases).catch(() => undefined);
    };
    const refreshHealth = () => {
      void frameflowApi.health().then((health) => setApiStatus({ connected: true, googleConfigured: health.google_configured, openaiConfigured: health.openai_configured })).catch(() => setApiStatus({ connected: false, googleConfigured: false, openaiConfigured: false }));
    };
    window.addEventListener("frameflow:workspace-changed", refreshWorkspace);
    window.addEventListener("frameflow:provider-settings-changed", refreshHealth);
    return () => {
      window.removeEventListener("frameflow:workspace-changed", refreshWorkspace);
      window.removeEventListener("frameflow:provider-settings-changed", refreshHealth);
    };
  }, [frameflowApi]);

  return (
    <div className="grid min-h-screen grid-cols-[240px_minmax(0,1fr)] overflow-hidden max-[980px]:grid-cols-[64px_minmax(0,1fr)]">
      <StudioSidebar pathname={pathname} workspace={workspace} canvases={canvases} />

      <main className="main-stage">
        <header className="topbar">
          <div className="page-identity">
            <span className="page-eyebrow">{title.eyebrow}</span>
            <h1>{title.title}</h1>
          </div>
          <div className="topbar-actions">
            <span className={`api-indicator ${apiStatus?.connected ? "connected" : apiStatus?.connected === false ? "offline" : "checking"}`}>
              <i />
              {apiStatus?.connected
                ? apiStatus.googleConfigured && apiStatus.openaiConfigured
                  ? "API · Google + OpenAI ready"
                  : apiStatus.googleConfigured
                    ? "API · Google ready"
                    : apiStatus.openaiConfigured
                      ? "API · OpenAI ready"
                      : "API · Provider setup required"
                : apiStatus?.connected === false ? "API offline" : "Checking"}
            </span>
          </div>
        </header>

        <section className="view-container">{children}</section>
      </main>
    </div>
  );
}
