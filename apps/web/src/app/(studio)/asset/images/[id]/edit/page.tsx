import { ImageEditor } from "@/features/images/components/image-editor";

export default async function ImageEditPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <ImageEditor artifactId={id} key={id} />;
}
