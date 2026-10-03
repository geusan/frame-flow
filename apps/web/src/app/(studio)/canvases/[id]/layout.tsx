"use client";

import type { ReactNode } from "react";
import { useParams, useRouter } from "next/navigation";
import { GenerationCanvas } from "@/components/views/generation-canvas";

export default function CanvasLayout({ children }: { children: ReactNode }) {
  const { id, nodeId } = useParams<{ id: string; nodeId?: string }>();
  const router = useRouter();
  const canvasPath = `/canvases/${encodeURIComponent(id)}`;

  // Keep the editor mounted while the URL opens or closes a node detail dialog.
  return <>
    <GenerationCanvas
      canvasId={id}
      nodeDetailId={nodeId}
      onOpenNodeDetail={(nextNodeId) => router.push(`${canvasPath}/nodes/${encodeURIComponent(nextNodeId)}`, { scroll: false })}
      onCloseNodeDetail={() => router.replace(canvasPath, { scroll: false })}
      onBack={() => router.push("/canvases")}
      key={id}
    />
    {children}
  </>;
}
