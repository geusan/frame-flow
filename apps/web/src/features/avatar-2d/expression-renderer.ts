import * as THREE from "three";
import { FACE_REGION, expressionRect, type ExpressionImage } from "./expression-library";

export const expressionUniforms = `
uniform sampler2D expressionA;
uniform sampler2D expressionB;
uniform vec4 expressionRectA;
uniform vec4 expressionRectB;
uniform float expressionBlend;
uniform float expressionStrength;
`;
export const expressionFragment = `
  if (isHead > 0.5 && expressionStrength > 0.0) {
    vec2 ea = (vArt-expressionRectA.xy)/expressionRectA.zw;
    vec2 eb = (vArt-expressionRectB.xy)/expressionRectB.zw;
    vec4 a = texture2D(expressionA, vec2(ea.x,1.0-ea.y));
    vec4 b = texture2D(expressionB, vec2(eb.x,1.0-eb.y));
    a.a *= step(0.0,ea.x)*step(ea.x,1.0)*step(0.0,ea.y)*step(ea.y,1.0);
    b.a *= step(0.0,eb.x)*step(eb.x,1.0)*step(0.0,eb.y)*step(eb.y,1.0);
    vec4 expression = mix(a,b,expressionBlend);
    float distanceToFace = length((vArt-vec2(${FACE_REGION.x.toFixed(1)},${FACE_REGION.y.toFixed(1)}))/vec2(${FACE_REGION.rx.toFixed(1)},${FACE_REGION.ry.toFixed(1)}));
    float faceMask = 1.0-smoothstep(${(1-FACE_REGION.feather).toFixed(2)},1.0,distanceToFace);
    color.rgb = mix(color.rgb,expression.rgb,faceMask*expressionStrength*expression.a);
  }
`;

/** Image expressions replace only face color. Head silhouette/alpha stays original. */
export class FaceArtwork {
  readonly uniforms: Record<string, THREE.IUniform>;
  private cache = new Map<string, Promise<THREE.Texture>>();
  private textures = new Set<THREE.Texture>();
  private revision = 0;
  private disposed = false;
  private started = 0;
  private duration = 140;
  private amount = 1;
  private fromActive = 0;
  private toActive = 0;
  private key = "neutral";
  effectStrength = 0;

  constructor(private original: THREE.Texture) {
    this.textures.add(original);
    this.uniforms = {
      expressionA: { value: original }, expressionB: { value: original },
      expressionRectA: { value: new THREE.Vector4(0,0,1024,1536) }, expressionRectB: { value: new THREE.Vector4(0,0,1024,1536) },
      expressionBlend: { value: 1 }, expressionStrength: { value: 1 },
    };
  }
  async select(entry: ExpressionImage, strength: number, duration: number) {
    const revision = ++this.revision;
    const key = JSON.stringify([entry.id, entry.image, expressionRect(entry)]);
    this.amount = strength;
    if (key === this.key) return;
    let texture = this.original;
    if (entry.id !== "neutral") {
      if (!this.cache.has(entry.image)) {
        const loading = new THREE.TextureLoader().loadAsync(entry.image).then((loaded) => {
          loaded.colorSpace = THREE.SRGBColorSpace;
          if (this.disposed) loaded.dispose(); else this.textures.add(loaded);
          return loaded;
        }).catch((error) => { this.cache.delete(entry.image); throw error; });
        this.cache.set(entry.image, loading);
      }
      texture = await this.cache.get(entry.image)!;
    }
    if (this.disposed || revision !== this.revision) return;
    this.key = key;
    this.uniforms.expressionA.value = this.uniforms.expressionB.value;
    this.uniforms.expressionRectA.value.copy(this.uniforms.expressionRectB.value);
    this.uniforms.expressionB.value = texture;
    this.uniforms.expressionRectB.value.set(...(entry.id === "neutral" ? [0,0,1024,1536] : expressionRect(entry)));
    this.fromActive = this.toActive; this.toActive = entry.id === "neutral" ? 0 : 1;
    this.started = performance.now(); this.duration = duration;
    this.tick();
  }
  tick() {
    const t = this.duration ? Math.min(1, Math.max(0,(performance.now()-this.started)/this.duration)) : 1;
    const eased = t*t*(3-2*t);
    this.uniforms.expressionBlend.value = eased;
    this.uniforms.expressionStrength.value = this.amount;
    this.effectStrength = (this.fromActive*(1-eased)+this.toActive*eased)*this.amount;
  }
  dispose() { this.disposed = true; this.revision++; this.textures.forEach((texture) => texture.dispose()); this.textures.clear(); this.cache.clear(); }
}
