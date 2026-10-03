"use client";

import { useParams, useRouter } from "next/navigation";
import type { ReactNode } from "react";

import { AssetLibrary } from "@/components/views/asset-library";

export default function ImagesGalleryLayout({ children }: { children: ReactNode }) {
  const params = useParams<{ id?: string }>();
  const router = useRouter();
  return <>
    <AssetLibrary
      tab="images"
      selectedAssetId={params.id}
      onOpenAsset={(artifactId) => router.push(`/asset/images/${encodeURIComponent(artifactId)}`, { scroll: false })}
      onCloseAsset={() => router.replace("/asset/images", { scroll: false })}
      onEditImage={(artifactId) => router.push(`/asset/images/${encodeURIComponent(artifactId)}/edit`)}
    />
    {children}
  </>;
}
