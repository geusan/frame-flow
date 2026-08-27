"use client";

import { use } from "react";
import { useRouter } from "next/navigation";
import { GenerationCanvas } from "@/components/views/generation-canvas";

export default function WorkflowPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const router = useRouter();
  return <GenerationCanvas canvasId={id} onBack={() => router.push("/workflows")} key={id} />;
}
