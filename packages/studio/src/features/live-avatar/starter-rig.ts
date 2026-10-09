import { BufferAttribute, Matrix3, Vector3, type SkinnedMesh } from "three";
import { FACE_CHANNELS, influence, type FaceProfile } from "./face-state";

/** Editable, approximate surface deformations. Does not invent an oral cavity. */
export function buildStarterRig(mesh: SkinnedMesh, profile: FaceProfile): number {
  const { leftEye, rightEye, mouth } = profile.anchors;
  if (!leftEye || !rightEye || !mouth) throw new Error("양쪽 눈과 입 중앙을 먼저 지정해 주세요.");
  const left = new Vector3(...leftEye), right = new Vector3(...rightEye), lips = new Vector3(...mouth);
  const distance = left.distanceTo(right);
  if (distance < 1e-5) throw new Error("양쪽 눈의 위치가 겹칩니다.");
  const across = left.clone().sub(right).normalize();
  const up = new Vector3(0, 1, 0).applyMatrix3(new Matrix3().setFromMatrix4(mesh.matrixWorld.clone().invert())).normalize();
  up.addScaledVector(across, -up.dot(across)).normalize();
  const forward = across.clone().cross(up).normalize();
  const midpoint = left.clone().add(right).multiplyScalar(.5);
  if (lips.clone().sub(midpoint).dot(up) > -distance * .08) throw new Error("입 중앙은 눈보다 아래에 지정해 주세요.");
  const geometry = mesh.geometry.clone();
  const position = geometry.getAttribute("position");
  const skinIndex = geometry.getAttribute("skinIndex"), skinWeight = geometry.getAttribute("skinWeight");
  const heads = new Set(mesh.skeleton.bones.map((bone, index) => bone.name === profile.head_bone ? index : -1));
  heads.delete(-1);
  if (!heads.size) throw new Error("Head 뼈대가 있는 모델이 필요합니다.");
  const targets = FACE_CHANNELS.map(() => new Float32Array(position.count * 3));
  let affected = 0;
  const v = new Vector3(), delta = new Vector3(), rel = new Vector3();
  const area = (center: Vector3, rx: number, ry: number) => {
    rel.copy(v).sub(center);
    return influence(rel.dot(across) / (distance * rx), rel.dot(up) / (distance * ry), rel.dot(forward) / (distance * profile.depth));
  };
  for (let i = 0; i < position.count; i++) {
    v.fromBufferAttribute(position, i);
    let weight = 0;
    for (let j = 0; j < 4; j++) if (heads.has(skinIndex.getComponent(i, j))) weight += skinWeight.getComponent(i, j);
    if (weight < .2) continue;
    let moved = false;
    for (let channel = 0; channel < FACE_CHANNELS.length; channel++) {
      delta.set(0, 0, 0);
      if (channel < 2) {
        const eye = channel === 0 ? left : right;
        rel.copy(v).sub(eye);
        const y = rel.dot(up);
        const flatFalloff = (value: number) => {
          const t = Math.max(0, Math.min(1, (Math.abs(value) - .7) / .3));
          return 1 - t * t * (3 - 2 * t);
        };
        const w = flatFalloff(rel.dot(across) / (distance * profile.eye_radius * 1.2))
          * flatFalloff(y / (distance * .42))
          * flatFalloff(rel.dot(forward) / (distance * profile.depth * 2));
        delta.copy(up).multiplyScalar(-y * .98 * w);
      } else if (channel === 2) {
        const below = Math.max(0, Math.min(1, -rel.copy(v).sub(lips).dot(up) / (distance * .18) + .35));
        delta.copy(up).multiplyScalar(-distance * .22 * below * area(lips, .65, .65));
      } else if (channel < 5) {
        const sign = channel === 3 ? 1 : -1;
        const corner = lips.clone().addScaledVector(across, distance * .22 * sign);
        const w = area(corner, .38, .28);
        delta.copy(up).multiplyScalar(distance * .11 * w).addScaledVector(across, distance * .035 * w * sign);
      } else {
        const brow = midpoint.clone().addScaledVector(up, distance * .25);
        delta.copy(up).multiplyScalar(distance * .10 * area(brow, .7, .28));
      }
      delta.multiplyScalar(weight);
      targets[channel].set(delta.toArray(), i * 3);
      moved ||= delta.lengthSq() > 1e-14;
    }
    if (moved) affected++;
  }
  if (affected < 15) { geometry.dispose(); throw new Error("얼굴 영역의 정점이 부족합니다. 기준점과 깊이를 조정해 주세요."); }
  geometry.morphAttributes.position = targets.map((values, i) => {
    const attribute = new BufferAttribute(values, 3); attribute.name = FACE_CHANNELS[i]; return attribute;
  });
  delete geometry.morphAttributes.normal;
  geometry.morphTargetsRelative = true;
  mesh.geometry = geometry;
  mesh.updateMorphTargets();
  mesh.morphTargetDictionary = Object.fromEntries(FACE_CHANNELS.map((key, i) => [key, i]));
  mesh.morphTargetInfluences = FACE_CHANNELS.map(() => 0);
  (Array.isArray(mesh.material) ? mesh.material : [mesh.material]).forEach((material) => { material.needsUpdate = true; });
  return affected;
}
