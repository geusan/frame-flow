"use client";

import { useRouter } from "next/navigation";
import { WorkflowLibrary } from "@/components/views/workflow-library";

export default function WorkflowsPage() {
  const router = useRouter();
  return <WorkflowLibrary
    onOpen={(workflowId) => router.push(`/workflows/${encodeURIComponent(workflowId)}`)}
    onEditDraft={(canvasId) => router.push(`/canvases/${encodeURIComponent(canvasId)}`)}
  />;
}
