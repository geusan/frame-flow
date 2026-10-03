"use client";

import { useParams, useRouter } from "next/navigation";
import type { ReactNode } from "react";

import { AssetLibrary } from "@/components/views/asset-library";

export default function VideosLayout({ children }: { children: ReactNode }) {
  const params = useParams<{ id?: string }>();
  const router = useRouter();
  return <>
    <AssetLibrary
      tab="videos"
      selectedAssetId={params.id}
      onOpenAsset={(artifactId) => router.push(`/asset/videos/${encodeURIComponent(artifactId)}`, { scroll: false })}
      onCloseAsset={() => router.replace("/asset/videos", { scroll: false })}
      onOpenImages={() => router.push("/asset/images")}
    />
    {children}
  </>;
}
