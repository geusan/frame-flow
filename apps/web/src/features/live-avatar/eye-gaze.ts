import { Euler, Material, Matrix3, MeshStandardMaterial, Quaternion, ShaderChunk, Vector2, Vector3, type Bone, type SkinnedMesh } from "three";
import type { FaceProfile, FaceValues, Gaze } from "./face-state";

const fragmentDeclarations = `
varying vec3 vAvatarGazePosition;
uniform vec3 avatarEyeLeft;
uniform vec3 avatarEyeRight;
uniform vec3 avatarAcross;
uniform vec3 avatarUp;
uniform vec2 avatarGaze;
uniform vec2 avatarBlink;
uniform float avatarEyeDistance;
uniform float avatarEyeRadius;
uniform float avatarEyeDepth;
uniform float avatarGazeRange;
float avatarEyeMask(vec3 center) {
  vec3 p = vAvatarGazePosition - center;
  float x = dot(p, avatarAcross) / (avatarEyeDistance * avatarEyeRadius);
  float y = dot(p, avatarUp) / (avatarEyeDistance * avatarEyeRadius * 0.8);
  float z = abs(dot(p, cross(avatarAcross, avatarUp))) / (avatarEyeDistance * avatarEyeDepth);
  return (1.0 - smoothstep(0.45, 1.0, length(vec2(x, y)))) * (1.0 - smoothstep(0.5, 1.0, z));
}
`;

/** Eye-local color/UV warp. Original textures and geometry are never changed. */
export class SurfaceEyeGaze {
  private mesh: SkinnedMesh;
  private original: Material | Material[];
  private copies: Material[];
  private uniforms: Record<string, { value: Vector2 | Vector3 | number }>;

  constructor(mesh: SkinnedMesh, profile: FaceProfile) {
    const { leftEye, rightEye } = profile.anchors;
    if (!leftEye || !rightEye) throw new Error("간이 시선에는 양쪽 눈 기준점이 필요합니다.");
    const left = new Vector3(...leftEye), right = new Vector3(...rightEye), distance = left.distanceTo(right);
    if (distance < 1e-5) throw new Error("양쪽 눈 기준점이 겹칩니다.");
    const across = left.clone().sub(right).normalize();
    const up = new Vector3(0, 1, 0).applyMatrix3(new Matrix3().setFromMatrix4(mesh.matrixWorld.clone().invert())).normalize();
    up.addScaledVector(across, -up.dot(across)).normalize();
    this.mesh = mesh; this.original = mesh.material;
    const materials = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
    if (!materials.some((material) => material instanceof MeshStandardMaterial && material.map)) throw new Error("간이 시선에는 눈 색상이 포함된 표면 텍스처가 필요합니다.");
    this.uniforms = {
      avatarEyeLeft: { value: left }, avatarEyeRight: { value: right },
      avatarAcross: { value: across }, avatarUp: { value: up },
      avatarGaze: { value: new Vector2() }, avatarBlink: { value: new Vector2() },
      avatarEyeDistance: { value: distance }, avatarEyeRadius: { value: profile.gaze.radius },
      avatarEyeDepth: { value: profile.depth }, avatarGazeRange: { value: profile.gaze.range },
    };
    this.copies = materials.map((material) => {
      const copy = material.clone();
      if (copy instanceof MeshStandardMaterial && copy.map) {
        copy.onBeforeCompile = (shader) => {
          Object.assign(shader.uniforms, this.uniforms);
          shader.vertexShader = shader.vertexShader.replace("#include <common>", "#include <common>\nvarying vec3 vAvatarGazePosition;")
            .replace("#include <begin_vertex>", "#include <begin_vertex>\nvAvatarGazePosition = position;");
          shader.fragmentShader = shader.fragmentShader.replace("#include <common>", `#include <common>\n${fragmentDeclarations}`);
          const sample = `
            float leftMask = avatarEyeMask(avatarEyeLeft) * (1.0 - smoothstep(0.4, 0.85, avatarBlink.x));
            float rightMask = avatarEyeMask(avatarEyeRight) * (1.0 - smoothstep(0.4, 0.85, avatarBlink.y));
            float mask = max(leftMask, rightMask);
            vec2 gazeUv = vMapUv;
            float horizontal = dot(vAvatarGazePosition, avatarAcross);
            float vertical = dot(vAvatarGazePosition, avatarUp);
            float a = dFdx(horizontal), b = dFdy(horizontal);
            float c = dFdx(vertical), d = dFdy(vertical);
            float determinant = a * d - b * c;
            vec2 uvDx = dFdx(vMapUv), uvDy = dFdy(vMapUv);
            if (abs(determinant) > 1e-12) {
              vec2 shift = avatarGaze * avatarEyeDistance * avatarGazeRange;
              vec2 screenShift = vec2(d * shift.x - b * shift.y, -c * shift.x + a * shift.y) / determinant;
              gazeUv -= clamp(uvDx * screenShift.x + uvDy * screenShift.y, vec2(-0.025), vec2(0.025)) * mask;
            }
            vec4 sampledDiffuseColor = texture2D(map, gazeUv);
          `;
          shader.fragmentShader = shader.fragmentShader.replace("#include <map_fragment>", ShaderChunk.map_fragment.replace("vec4 sampledDiffuseColor = texture2D( map, vMapUv );", sample));
        };
        copy.customProgramCacheKey = () => "avatar-surface-gaze.v1";
        copy.needsUpdate = true;
      }
      return copy;
    });
    mesh.material = Array.isArray(mesh.material) ? this.copies : this.copies[0];
  }

  update(gaze: Gaze, face: FaceValues) {
    (this.uniforms.avatarGaze.value as Vector2).set(gaze.x, gaze.y);
    (this.uniforms.avatarBlink.value as Vector2).set(face.eyeBlinkLeft, face.eyeBlinkRight);
  }

  dispose() { this.mesh.material = this.original; this.copies.forEach((material) => material.dispose()); }
}

/** Preserve each eye's rest orientation and follow its moving head parent. */
export function rotateEye(bone: Bone, rest: Quaternion, headDelta: Quaternion, gaze: Gaze, maxDegrees: number) {
  bone.quaternion.copy(rest); bone.parent?.updateWorldMatrix(true, false);
  const parent = bone.parent?.getWorldQuaternion(new Quaternion()) ?? new Quaternion();
  const radians = maxDegrees * Math.PI / 180;
  const delta = new Quaternion().setFromEuler(new Euler(-gaze.y * radians * .8, gaze.x * radians, 0, "YXZ"));
  const worldDelta = headDelta.clone().multiply(delta).multiply(headDelta.clone().invert());
  bone.quaternion.copy(parent.clone().invert().multiply(worldDelta).multiply(parent).multiply(rest));
}
