import { LiveAvatar } from "@/features/live-avatar/live-avatar";
export default async function LiveAvatarPage({ params }: { params: Promise<{ artifactId: string }> }) {
  const { artifactId } = await params;
  return <LiveAvatar key={artifactId} artifactId={artifactId} />;
}
