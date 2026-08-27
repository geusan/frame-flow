"use client";

import { useRouter } from "next/navigation";

import { AssetLibrary } from "@/components/views/asset-library";

export default function ImagesPage() {
  const router = useRouter();
  return <AssetLibrary tab="images" onEditImage={(artifactId) => router.push(`/asset/images/${artifactId}/edit`)} />;
}
