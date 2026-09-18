import type { BufferGeometry, Mesh } from "three";
import type { FaceChannel, FaceValues } from "./face-state";

export function findMorphMapping(names: readonly string[], channel: string): string {
  const normalize = (name: string) => name.toLowerCase().replace(/[^a-z]/g, "");
  const expected = normalize(channel);
  const exact = names.find((name) => normalize(name) === expected);
  if (exact) return exact;
  // Namespaced exports such as "Wolf3D_Head.mouthSmileLeft" are common.
  const matches = names.filter((name) => normalize(name).endsWith(expected));
  return matches.length === 1 ? matches[0] : "";
}

/** GLTFLoader names live in the dictionary, not always on BufferAttributes. */
export function restoreMorphGeometry(mesh: Mesh, geometry: BufferGeometry, dictionary: Record<string, number> | undefined) {
  mesh.geometry = geometry;
  mesh.updateMorphTargets();
  if (dictionary) mesh.morphTargetDictionary = { ...dictionary };
}

export function applyMorphValues(meshes: readonly Mesh[], channels: readonly FaceChannel[], values: FaceValues, mappings: Record<string, string>) {
  for (const mesh of meshes) {
    const weights = mesh.morphTargetInfluences, targets = mesh.morphTargetDictionary;
    if (!weights || !targets) continue;
    weights.fill(0);
    for (const channel of channels) {
      const index = targets[mappings[channel]];
      // The same shape may be mapped to two detector channels. Do not let a zero
      // on one side erase the other side's expression; do not add past 1 either.
      if (index !== undefined) weights[index] = Math.max(weights[index], Math.max(0, Math.min(1, values[channel] || 0)));
    }
  }
}
