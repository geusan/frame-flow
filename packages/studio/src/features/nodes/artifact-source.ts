import type { UploadedArtifact } from "../../lib/api";
import type { CanvasOutput, NodeTemplate, StudioFlowNode } from "../../lib/canvas-model";
import type { PortType } from "../../lib/types";

export function uploadedArtifactOutput(filename: string, artifact: UploadedArtifact): CanvasOutput {
  const kind: CanvasOutput["kind"] = artifact.type === "Image" ? "image" : artifact.type === "Video" ? "video" : artifact.type === "Audio" ? "audio" : artifact.type === "Model3D" ? "json" : "text";
  return {
    kind,
    title: filename,
    url: ["image", "video", "audio"].includes(kind) ? artifact.url : undefined,
    text: kind === "json"
      ? JSON.stringify({ schema_version: "model.gltf.v1", artifact_id: artifact.artifact_id, size_bytes: artifact.size_bytes })
      : kind === "text" ? filename : `${(artifact.size_bytes / 1_000_000).toFixed(1)} MB`,
    mimeType: artifact.content_type,
  };
}

/** Complete an authoring upload using the registered Artifact source contract. */
export function importedAssetData(artifact: UploadedArtifact, templates: NodeTemplate[], title = artifact.filename): StudioFlowNode["data"] {
  const source = templates.find((template) => template.data.key === "asset.select");
  if (!source) throw new Error("Asset source definition is unavailable. Reload the Canvas and try again.");
  return {
    ...source.data,
    status: "SUCCEEDED",
    configText: artifact.artifact_id,
    config: { ...source.data.config, artifact_id: artifact.artifact_id, artifact_type: artifact.type },
    preview: title,
    output: uploadedArtifactOutput(title, artifact),
    outputType: artifact.type as PortType,
    outputArtifactIds: [artifact.artifact_id],
  };
}

/** Upload requests belong to the previous browser session and cannot resume on load. */
export function recoverInterruptedAssetImport(node: StudioFlowNode): StudioFlowNode {
  if (node.data.key !== "asset.upload" || node.data.status !== "RUNNING") return node;
  return { ...node, data: {
    ...node.data,
    status: "FAILED",
    preview: undefined,
    logs: [...(node.data.logs ?? []), "Import was interrupted. Paste the URL or choose the file again."],
  } };
}
