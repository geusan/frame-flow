"use client";

import { useRouter } from "next/navigation";
import { AssetLibrary } from "@/components/views/asset-library";

export default function VideosPage() {
  const router = useRouter();
  return <AssetLibrary tab="videos" onOpenImages={() => router.push("/asset/images")} />;
}
