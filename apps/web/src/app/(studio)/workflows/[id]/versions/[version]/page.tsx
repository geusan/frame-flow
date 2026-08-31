"use client";

import { use } from "react";
import { useRouter } from "next/navigation";

import { WorkflowVersionView } from "@/components/views/workflow-version-view";

export default function WorkflowVersionPage({ params }: { params: Promise<{ id: string; version: string }> }) {
  const { id, version } = use(params);
  const router = useRouter();
  const versionNumber = Number(version);
  return <WorkflowVersionView
    workflowId={id}
    versionNumber={versionNumber}
    onBack={() => router.push(`/workflows/${encodeURIComponent(id)}`)}
    onEditDraft={(canvasId) => router.push(`/canvases/${encodeURIComponent(canvasId)}`)}
    onRun={() => router.push(`/workflows/${encodeURIComponent(id)}`)}
  />;
}
