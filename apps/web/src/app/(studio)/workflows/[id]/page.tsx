"use client";

import { use, useEffect } from "react";
import { useRouter } from "next/navigation";
import { WorkflowDetail } from "@/components/views/workflow-detail";

export default function WorkflowPage({ params }: { params: Promise<{ id: string; nodeId?: string }> }) {
  const { id, nodeId } = use(params);
  const router = useRouter();
  const legacyCanvas = id.startsWith("canvas_");
  useEffect(() => {
    if (legacyCanvas) router.replace(`/canvases/${encodeURIComponent(id)}${nodeId ? `/nodes/${encodeURIComponent(nodeId)}` : ""}`);
  }, [id, legacyCanvas, nodeId, router]);
  if (legacyCanvas) return <div className="route-loading">Redirecting legacy Canvas URL…</div>;
  return <WorkflowDetail
    workflowId={id}
    onBack={() => router.push("/workflows")}
    onEditDraft={(canvasId) => router.push(`/canvases/${encodeURIComponent(canvasId)}`)}
    onOpenVersion={(version) => router.push(`/workflows/${encodeURIComponent(id)}/versions/${version}`)}
    onOpenRun={() => router.push("/runs")}
  />;
}
