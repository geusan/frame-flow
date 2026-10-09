"use client";

import { useState } from "react";
import { CanvasLibrary } from "../../components/views/canvas-library";
import { GenerationCanvas } from "../../components/views/generation-canvas";
import { WorkflowLibrary } from "../../components/views/workflow-library";
import { WorkflowDetail } from "../../components/views/workflow-detail";
import { WorkflowVersionView } from "../../components/views/workflow-version-view";
import { RunsView } from "../../components/views/runs-view";

/** Shared Studio assembly; authentication remains at the API adapter boundary. */
export function EmbeddedStudio({ workspaceId }: { workspaceId: string }) {
  const [view, setView] = useState<"canvases" | "canvas" | "workflows" | "workflow" | "version" | "runs">("canvases");
  const [canvasId, setCanvasId] = useState<string | null>(null);
  const [workflowId, setWorkflowId] = useState<string | null>(null);
  const [nodeId, setNodeId] = useState<string | undefined>();
  const [version, setVersion] = useState(1);
  const openCanvas = (id: string) => { setCanvasId(id); setView("canvas"); setNodeId(undefined); };
  return <main key={workspaceId}>
    <nav aria-label="Studio views" className="flex gap-4 border-b p-4">
      <button onClick={() => setView("canvases")}>Canvases</button>
      <button onClick={() => setView("workflows")}>Workflows</button>
      <button onClick={() => setView("runs")}>Runs</button>
    </nav>
    {view === "canvases" && <CanvasLibrary onOpen={openCanvas} migrateLegacy={false} />}
    {view === "workflows" && <WorkflowLibrary onOpen={id => { setWorkflowId(id); setView("workflow"); }} onEditDraft={openCanvas} />}
    {view === "canvas" && canvasId && <GenerationCanvas canvasId={canvasId} nodeDetailId={nodeId} onOpenNodeDetail={setNodeId} onCloseNodeDetail={() => setNodeId(undefined)} onBack={() => setView("canvases")} />}
    {view === "workflow" && workflowId && <WorkflowDetail workflowId={workflowId} onBack={() => setView("workflows")} onEditDraft={openCanvas} onOpenVersion={number => { setVersion(number); setView("version"); }} onOpenRun={() => setView("runs")} />}
    {view === "version" && workflowId && <WorkflowVersionView workflowId={workflowId} versionNumber={version} onBack={() => setView("workflow")} onEditDraft={openCanvas} onRun={() => setView("workflow")} />}
    {view === "runs" && <RunsView />}
  </main>;
}
