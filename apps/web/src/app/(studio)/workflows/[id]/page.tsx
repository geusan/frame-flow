"use client";

import { use } from "react";
import { useRouter } from "next/navigation";
import { GenerationCanvas } from "@/components/views/generation-canvas";

export default function WorkflowPage({ params }: { params: Promise<{ id: string; nodeId?: string }> }) {
  const { id, nodeId } = use(params);
  const router = useRouter();
  const canvasPath = `/workflows/${encodeURIComponent(id)}`;
  return <GenerationCanvas
    canvasId={id}
    nodeDetailId={nodeId}
    onOpenNodeDetail={(nextNodeId) => router.push(`${canvasPath}/nodes/${encodeURIComponent(nextNodeId)}`, { scroll: false })}
    onCloseNodeDetail={() => router.replace(canvasPath, { scroll: false })}
    onBack={() => router.push("/workflows")}
    key={id}
  />;
}
