"use client";

import { useParams, useRouter } from "next/navigation";

import { AudioLibrary } from "@/components/views/audio-library";

export default function AudioPage() {
  const params = useParams<{ id?: string }>();
  const router = useRouter();
  return <AudioLibrary
    selectedAssetId={params.id}
    onOpenAsset={(artifactId) => router.push(`/asset/audio/${encodeURIComponent(artifactId)}`, { scroll: false })}
    onCloseAsset={() => router.replace("/asset/audio", { scroll: false })}
  />;
}
