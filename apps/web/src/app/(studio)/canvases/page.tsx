"use client";

import { useRouter } from "next/navigation";
import { CanvasLibrary } from "@/components/views/canvas-library";

export default function CanvasesPage() {
  const router = useRouter();
  return <CanvasLibrary onOpen={(canvasId) => router.push(`/canvases/${encodeURIComponent(canvasId)}`)} />;
}
