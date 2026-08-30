"use client";

import { useParams, useRouter } from "next/navigation";

import { ReferenceResultsView } from "@/components/views/reference-results-view";

export default function ReferenceResultsPage() {
  const params = useParams<{ id?: string }>();
  const router = useRouter();
  return (
    <ReferenceResultsView
      selectedResultId={params.id}
      onOpenResult={(artifactId) => router.push(`/reference-results/${encodeURIComponent(artifactId)}`, { scroll: false })}
      onCloseResult={() => router.replace("/reference-results", { scroll: false })}
    />
  );
}
