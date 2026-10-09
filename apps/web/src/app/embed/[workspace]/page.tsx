import { EmbeddedStudio } from "@/features/studio/embedded-studio";

export default async function EmbeddedPage({ params }: { params: Promise<{ workspace: string }> }) {
  const { workspace } = await params;
  return <EmbeddedStudio workspaceId={workspace} />;
}
