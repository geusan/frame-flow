import type { StudioNodeData } from "../../lib/canvas-model";

const GLB_ARTIFACT_TYPES = new Set(["Model3D", "Character3D", "Character3DValidated", "CharacterRigged", "AnimatedCharacter"]);

export function isModel3DArtifactType(type?: string): boolean {
  return GLB_ARTIFACT_TYPES.has(type ?? "");
}

/** Presentation-only adapter: old Node/Artifact contracts remain unchanged. */
export function modelPreviewUrl(data: Pick<StudioNodeData, "outputType" | "output" | "outputArtifactIds">, apiBase: string): string | undefined {
  if (!isModel3DArtifactType(data.outputType) && data.output?.mimeType !== "model/gltf-binary") return undefined;
  const artifactId = data.outputArtifactIds?.[0];
  if (artifactId) return `${apiBase}/artifacts/${encodeURIComponent(artifactId)}/content`;
  return data.output?.mimeType === "model/gltf-binary" ? data.output.url : undefined;
}
