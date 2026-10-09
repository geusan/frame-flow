import * as THREE from "three";
import { HEAD_OUTLINE, PARTS, type ArtPart } from "./parts";
import { add, angle, angleDelta, clamp, length, mix, neutralPose, rotate, sub, type Anchors, type Point, type Pose } from "./rig";

import { neckTransform } from "./rig";
import { partitionArtwork } from "./artwork-partition";
import { FaceArtwork, expressionUniforms, expressionFragment } from "./expression-renderer";
import type { ExpressionImage, ExpressionLibrary } from "./expression-library";
import { FaceRigRenderer } from "./face-rig-renderer";
import { FACE_CROP, neutralRigFace, type FaceRig2D, type RigFaceValues } from "./face-rig";
import { CONNECTED_LEFT_BODY, artworkGrid, ShoulderSurface, garmentPoint } from "./shoulder-surface";
import { SHOULDER_GARMENT, separateShoulderGarment } from "./shoulder-garment";

const vertexShader = `
attribute vec3 surfaceNormal;
attribute vec2 artworkPoint;
varying vec2 vUv;
varying vec2 vArt;
varying vec3 vNormal;
varying vec3 vPosition;
void main() {
  vUv = uv; vArt = artworkPoint; vNormal = surfaceNormal; vPosition = position;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}`;
const fragmentShader = `
${expressionUniforms}
uniform sampler2D artwork;
uniform vec3 lightDirection;
uniform float lightStrength;
uniform float lightMix;
uniform float isHead;
uniform float mouth;
uniform float inspection;
uniform vec3 inspectionColor;
uniform vec4 blockers[5];
uniform vec2 blockerDepth[5];
varying vec2 vUv;
varying vec2 vArt;
varying vec3 vNormal;
varying vec3 vPosition;
float capsule(vec2 p, vec2 a, vec2 b) {
  vec2 ab = b-a;
  float t = clamp(dot(p-a, ab) / max(dot(ab,ab), 0.01), 0.0, 1.0);
  return length(p-a-ab*t);
}
void main() {
  vec4 color = texture2D(artwork, vUv);
  if (color.a < 0.025) discard;
  ${expressionFragment}
  vec3 n = normalize(vNormal);
  float diffuse = max(0.0, dot(n, lightDirection));
  float cel = mix(0.63, 0.92, smoothstep(0.12,0.22,diffuse));
  cel = mix(cel,1.12,smoothstep(0.7,0.85,diffuse));
  float visibility = 1.0;
  for (int i=0; i<5; i++) {
    float dz = blockerDepth[i].y - vPosition.z;
    if (dz > 12.0) {
      vec2 offset = -lightDirection.xy * dz / max(lightDirection.z,0.35);
      float d = capsule(vPosition.xy, blockers[i].xy+offset, blockers[i].zw+offset);
      visibility *= mix(0.76,1.0,smoothstep(blockerDepth[i].x-5.0,blockerDepth[i].x+12.0,d));
    }
  }
  color.rgb *= mix(1.0, (0.25+cel*lightStrength*0.75)*visibility, lightMix);
  // An authored mouth control independent of body geometry; keeps the line-art style.
  if (isHead > 0.5 && mouth > 0.08) {
    vec2 q = (vArt-vec2(509.0,251.0)) / vec2(9.0+mouth*4.0, 1.0+mouth*10.0);
    float shape = 1.0-smoothstep(0.84,1.08,length(q));
    vec3 lip = mix(vec3(0.095,0.027,0.031),vec3(0.49,0.17,0.19),smoothstep(0.12,0.8,q.y));
    if (q.y < -0.42 && mouth > 0.32) lip=vec3(0.86,0.82,0.74);
    color.rgb = mix(color.rgb,lip,shape);
  }
  if (inspection > 0.5) color.rgb = inspectionColor;
  gl_FragColor = color;
  #include <colorspace_fragment>
}`;

interface Layer { part: ArtPart; mesh: THREE.Mesh<THREE.BufferGeometry, THREE.ShaderMaterial>; points: Point[]; normals: number[]; shoulder?: ShoulderSurface; }
interface Segment { start: Point; target: Point; delta: number; restEnd: Point; end: Point }

/** Flood only the exterior matte; enclosed white clothes and eyes stay opaque. */
export function exteriorMatte(data: Uint8ClampedArray, width: number, height: number): void {
  const seen = new Uint8Array(width * height), queue = new Int32Array(width * height);
  let read = 0, write = 0;
  const visit = (i: number) => {
    if (seen[i]) return;
    seen[i] = 1;
    const k = i * 4;
    if (Math.min(data[k], data[k + 1], data[k + 2]) < 225) return;
    data[k + 3] = 0; queue[write++] = i;
  };
  for (let x = 0; x < width; x++) { visit(x); visit((height - 1) * width + x); }
  for (let y = 0; y < height; y++) { visit(y * width); visit(y * width + width - 1); }
  while (read < write) {
    const i = queue[read++], x = i % width;
    if (x) visit(i - 1); if (x < width - 1) visit(i + 1);
    if (i >= width) visit(i - width); if (i < width * (height - 1)) visit(i + width);
  }
}

export class PuppetScene {
  private renderer: THREE.WebGLRenderer;
  private scene = new THREE.Scene();
  private camera = new THREE.OrthographicCamera(0, 1024, 0, 1536, .1, 5000);
  private layers: Layer[] = [];
  private resizeObserver: ResizeObserver;
  private disposed = false;
  private rest: Anchors;
  private pose: Pose;
  private backdrop: THREE.Mesh;
  private shadow: THREE.Mesh;
  private shadowTexture: THREE.CanvasTexture;
  private light = new THREE.Vector3(-.5, -.5, 1).normalize();
  private bounds = { left: 0, top: -70, width: 1024, height: 1650 };
  private faceArtwork: FaceArtwork | null = null;
  private faceRig: FaceRigRenderer | null = null;
  private liveFace = false;
  private faceRigValues = neutralRigFace();
  private framing = { x: 512, y: 755, height: 1650, minimumWidth: 0 };
  lightStrength = 1;
  lightMix = .38;
  background = "#ebe9e5";
  inspectionMode: "art" | "flat" | "mesh" = "art";
  motionEffects = true;
  groundShadow = true;
  /** Bounded manual shoulder study; enable before loading artwork. */
  connectedLeftShoulder = false;

  constructor(private mount: HTMLElement, rest: Anchors) {
    this.rest = rest; this.pose = neutralPose(rest);
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false, preserveDrawingBuffer: true });
    this.renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.domElement.setAttribute("aria-label", "2D 아바타 미리보기");
    this.mount.appendChild(this.renderer.domElement);
    this.camera.position.z = 2000;
    this.backdrop = new THREE.Mesh(new THREE.PlaneGeometry(8000, 8000), new THREE.MeshBasicMaterial({ color: this.background, side: THREE.DoubleSide }));
    this.backdrop.position.set(512, 768, -200); this.scene.add(this.backdrop);
    const c = document.createElement("canvas"); c.width = 256; c.height = 128;
    const ctx = c.getContext("2d")!; const gradient = ctx.createRadialGradient(64, 64, 0, 64, 64, 64);
    gradient.addColorStop(0, "rgba(54,46,40,.24)"); gradient.addColorStop(.45, "rgba(54,46,40,.12)"); gradient.addColorStop(1, "rgba(54,46,40,0)");
    ctx.scale(2, 1); ctx.fillStyle = gradient; ctx.fillRect(0, 0, 128, 128);
    this.shadowTexture = new THREE.CanvasTexture(c);
    this.shadow = new THREE.Mesh(new THREE.PlaneGeometry(470, 95), new THREE.MeshBasicMaterial({ map: this.shadowTexture, transparent: true, depthWrite: false, side: THREE.DoubleSide }));
    this.shadow.position.set(512, 1504, -120); this.shadow.renderOrder = -1000; this.scene.add(this.shadow);
    this.resizeObserver = new ResizeObserver(() => this.resize()); this.resizeObserver.observe(mount); this.resize();
  }
  async load(url: string, headUrl?: string) {
    const root = url.slice(0, url.lastIndexOf("/") + 1);
    const [source, completion, replacementHead] = await Promise.all([this.loadPlate(url), this.loadPlate(`${root}body-underpaint-v2.png`),headUrl?this.loadPlate(headUrl):Promise.resolve(null)]);
    if (this.disposed) return;
    const head = document.createElement("canvas"); head.width = 1024; head.height = 1536;
    const headContext = head.getContext("2d", { willReadFrequently: true })!;
    headContext.beginPath(); HEAD_OUTLINE.forEach(([x,y], i) => i ? headContext.lineTo(x,y) : headContext.moveTo(x,y)); headContext.closePath(); headContext.fill();
    const region = headContext.getImageData(0, 0, 1024, 1536);
    const original = source.getContext("2d")!.getImageData(0, 0, 1024, 1536);
    const partition = partitionArtwork(original.data, region.data, 1024, 1536);
    const headPixels = new ImageData(partition.head, 1024, 1536);
    const bodyPixels = new ImageData(partition.body, 1024, 1536);
    headContext.putImageData(headPixels,0,0);
    if(replacementHead){headContext.globalCompositeOperation="source-in";headContext.drawImage(replacementHead,0,0,1024,1536);headContext.globalCompositeOperation="source-over";}
    const originalFaceTexture = new THREE.CanvasTexture(head); originalFaceTexture.colorSpace = THREE.SRGBColorSpace;
    this.faceArtwork = new FaceArtwork(originalFaceTexture);
    const body = document.createElement("canvas"); body.width=1024; body.height=1536;
    const bodyContext = body.getContext("2d")!;
    bodyContext.drawImage(completion,0,35);
    // Completion is allowed only under existing hair: it cannot widen the neutral
    // body silhouette. Original skin/clothes remain unchanged everywhere else.
    bodyContext.globalCompositeOperation="destination-in"; bodyContext.drawImage(head,0,0);
    bodyContext.globalCompositeOperation="source-over";
    const remainder=document.createElement("canvas"); remainder.width=1024; remainder.height=1536;
    remainder.getContext("2d")!.putImageData(bodyPixels,0,0); bodyContext.drawImage(remainder,0,0);
    const surfaces=this.connectedLeftShoulder?separateShoulderGarment(body):null;
    const parts = this.connectedLeftShoulder ? PARTS.filter(p => p.id !== "left-arm").flatMap(p => p.id === "body" ? [CONNECTED_LEFT_BODY,SHOULDER_GARMENT] : [p]) : PARTS;
    for (const part of parts) this.createLayer(part.id===SHOULDER_GARMENT.id?surfaces!.garment:part.id===CONNECTED_LEFT_BODY.id?surfaces!.skin:part.id === "head" ? head : part.paint === "body" || part.id.includes("arm") ? body : source, part);
    await Promise.all(this.layers.map(layer => layer.shoulder?.prepare(() => !this.disposed)));
    if(this.disposed)return;
    this.render(this.pose, 0);
  }
  private async loadPlate(url: string): Promise<HTMLCanvasElement> {
    const image = new Image(); image.crossOrigin = "anonymous";
    await new Promise<void>((resolve, reject) => { image.onload = () => resolve(); image.onerror = () => reject(new Error("2D 아바타 원화를 불러오지 못했습니다.")); image.src = url; });
    const source = document.createElement("canvas"); source.width = image.width; source.height = image.height;
    const context = source.getContext("2d", { willReadFrequently: true })!; context.drawImage(image, 0, 0);
    const pixels = context.getImageData(0, 0, source.width, source.height);
    exteriorMatte(pixels.data, source.width, source.height); context.putImageData(pixels, 0, 0);
    return source;
  }
  private createLayer(source: HTMLCanvasElement, part: ArtPart) {
    const joined = part.id === CONNECTED_LEFT_BODY.id;
    const spacing = part.id === "head" ? 7 : joined ? 12 : 14;
    const {minX,minY,width,height,points,indices} = artworkGrid(part.polygon,spacing,joined);
    const canvas = document.createElement("canvas"); canvas.width = width; canvas.height = height;
    const ctx = canvas.getContext("2d")!; ctx.translate(-minX, -minY); ctx.beginPath();
    part.polygon.forEach(([x, y], i) => i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)); ctx.closePath(); ctx.clip();
    ctx.drawImage(source, 0, 0);
    const texture = new THREE.CanvasTexture(canvas); texture.colorSpace = THREE.SRGBColorSpace; texture.anisotropy = Math.min(8, this.renderer.capabilities.getMaxAnisotropy());
    const positions: number[] = [], normals: number[] = [], uv: number[] = [];
    for (const [px,py] of points) {
      positions.push(px,py,part.depth);uv.push((px-minX)/width,1-(py-minY)/height);normals.push(0,0,1);
    }
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3)); geometry.setAttribute("uv", new THREE.Float32BufferAttribute(uv, 2));
    geometry.setAttribute("surfaceNormal", new THREE.Float32BufferAttribute(normals, 3)); geometry.setAttribute("artworkPoint", new THREE.Float32BufferAttribute(points.flat(), 2)); geometry.setIndex(indices);
    const material = new THREE.ShaderMaterial({ vertexShader, fragmentShader, transparent: true, side: THREE.DoubleSide, depthWrite: false, depthTest: false, uniforms: {
      ...this.faceArtwork!.uniforms,
      artwork: { value: texture }, lightDirection: { value: this.light }, lightStrength: { value: 1 }, lightMix: { value: this.lightMix }, isHead: { value: part.id === "head" ? 1 : 0 }, mouth: { value: 0 },
      inspection: { value: 0 }, inspectionColor: { value: new THREE.Color(part.id === "left-arm" ? "#8672cd" : "#c9cec5") },
      blockers: { value: Array.from({ length: 5 }, () => new THREE.Vector4()) }, blockerDepth: { value: Array.from({ length: 5 }, () => new THREE.Vector2()) },
    } });
    const mesh = new THREE.Mesh(geometry, material); mesh.frustumCulled = false; this.scene.add(mesh);
    this.layers.push({ part, mesh, points, normals, shoulder: joined ? new ShoulderSurface(points, indices, this.rest) : undefined });
  }
  setRest(rest: Anchors) { this.rest = rest; }
  async configureFaceRig(profile: FaceRig2D, library: ExpressionLibrary) {
    this.faceRig ??= new FaceRigRenderer(); await this.faceRig.configure(profile,library); this.setLiveFace(this.liveFace);
  }
  setLiveFace(enabled: boolean) {
    this.liveFace=enabled;
    const head=this.layers.find(layer=>layer.part.id==='head');if(!head||!this.faceArtwork)return;
    if(enabled&&this.faceRig?.ready){
      const rect=new THREE.Vector4(FACE_CROP.x,FACE_CROP.y,FACE_CROP.width,FACE_CROP.height);
      Object.assign(head.mesh.material.uniforms,{expressionA:{value:this.faceRig.texture},expressionB:{value:this.faceRig.texture},expressionRectA:{value:rect},expressionRectB:{value:rect},expressionBlend:{value:1},expressionStrength:{value:1}});
    }else Object.assign(head.mesh.material.uniforms,this.faceArtwork.uniforms);
  }
  setFaceRigDebug(enabled: boolean) { this.faceRig?.setDebug(enabled); }
  setMouthRig(value: import("./mouth-rig").MouthRig) { this.faceRig?.setMouthRig(value); }
  setEyelidRig(value: import("./eyelid-rig").EyelidRig) { this.faceRig?.setEyelidRig(value); }
  setBrowDetail(value: import("./brow-detail").BrowDetail) { this.faceRig?.setBrowDetail(value); }
  setFeatureAlignment(value: import("./feature-alignment").FeatureAlignment) { this.faceRig?.setFeatureAlignment(value); }
  setLeftEyeAppearance(value: import("./left-eye-renderer").EyeAppearance) { this.faceRig?.setEyeAppearance(value); }
  setFaceRigValues(values: RigFaceValues) { this.faceRigValues=values; }
  get faceRigLimited() { return this.faceRig?.limited ?? false; }
  async setExpression(entry: ExpressionImage, strength: number, duration: number) { await this.faceArtwork?.select(entry, strength, duration); }
  setFraming(x: number, y: number, height: number, minimumWidth = 0) {
    this.framing = { x, y, height: Math.max(100, height), minimumWidth }; this.resize();
  }
  setLight(degrees: number, height: number) {
    const angle = degrees * Math.PI / 180;
    this.light.set(Math.cos(angle) * .9, Math.sin(angle) * .9, clamp(height, .2, 2)).normalize();
  }
  private segments(part: ArtPart, pose: Pose): Segment[] {
    return part.chain.slice(0, -1).map((key, i) => {
      const next = part.chain[i + 1];
      return { start: this.rest[key], restEnd: this.rest[next], target: pose.joints[key], end: pose.joints[next], delta: angleDelta(angle(sub(pose.joints[next], pose.joints[key])), angle(sub(this.rest[next], this.rest[key]))) };
    });
  }
  render(pose: Pose, time: number) {
    if (this.disposed) return;
    this.pose = pose;
    this.faceArtwork?.tick();
    if(this.liveFace)this.faceRig?.render(this.faceRigValues,performance.now());
    const authoredFace = this.liveFace&&this.faceRig?.ready ? 1 : this.faceArtwork?.effectStrength ?? 0;
    (this.backdrop.material as THREE.MeshBasicMaterial).color.set(this.background);
    this.renderer.setClearColor(this.background);
    const j = pose.joints;
    const blockers: [Point, Point, number, number][] = [
      [j.head, j.head, 99, 65], [j.rightShoulder, j.rightElbow, 28, 20 + (pose.depth.rightElbow ?? 0)], [j.rightElbow, j.rightWrist, 23, 20 + (pose.depth.rightWrist ?? 0)],
      [j.leftShoulder, j.leftElbow, 28, 20 + (pose.depth.leftElbow ?? 0)], [j.leftElbow, j.leftWrist, 23, 20 + (pose.depth.leftWrist ?? 0)],
    ];
    for (const layer of this.layers) {
      const { part, mesh, points } = layer, segments = this.segments(part, pose);
      const position = mesh.geometry.getAttribute("position") as THREE.BufferAttribute;
      const normal = mesh.geometry.getAttribute("surfaceNormal") as THREE.BufferAttribute;
      const shoulderPoints = layer.shoulder?.deform(pose);
      for (let i = 0; i < points.length; i++) {
        const original = points[i]; const source: Point = [...original];
        let target: Point, orientation: number, normalX = 0, normalY = 0;
        if(part.id===SHOULDER_GARMENT.id) {
          target=garmentPoint(source,this.rest,pose);orientation=0;
        } else if (shoulderPoints) {
          target = shoulderPoints[i]; orientation = 0;
        } else if (part.id === "head") {
          // Head turn is a bounded 2.5D deformation, never an unbounded 3D reconstruction.
          const localX = source[0] - this.rest.head[0], face = Math.max(0, 1 - (localX / 170) ** 2);
          source[0] += pose.headTurn * 32 * face;
          for (const eyeX of [461, 555]) {
            const influence = Math.exp(-(((source[0] - eyeX) / 29) ** 4) - ((source[1] - 201) / 20) ** 4);
            source[1] += (201 - source[1]) * pose.blink * (1-authoredFace) * .9 * influence;
          }
          if (this.motionEffects) source[0] += Math.sin(time * 3 + source[1] / 90) * Math.max(0, source[1] - 280) / 80 * 1.8;
          orientation = pose.headTilt;
          target = add(pose.joints.head, rotate(sub(source, this.rest.head), orientation));
          normalX = clamp((original[0] - 512) / 145, -.9, .9) * .68;
          normalY = clamp((original[1] - 205) / 175, -.9, .9) * .42;
        } else {
          const closest = segments.map((s) => {
            const d = sub(s.restEnd, s.start), t = clamp((sub(source, s.start)[0] * d[0] + sub(source, s.start)[1] * d[1]) / Math.max(1, length(d) ** 2), 0, 1);
            return { s, distance: length(sub(source, [s.start[0] + d[0] * t, s.start[1] + d[1] * t])) };
          });
          const a = closest[0], b = closest[1] ?? a;
          let weight = a === b ? 0 : clamp(.5 + (a.distance - b.distance) / 35, 0, 1);
          weight = weight * weight * (3 - 2 * weight);
          const first = add(a.s.target, rotate(sub(source, a.s.start), a.s.delta));
          const second = add(b.s.target, rotate(sub(source, b.s.start), b.s.delta));
          target = [mix(first[0], second[0], weight), mix(first[1], second[1], weight)];
          orientation = a.s.delta + angleDelta(b.s.delta, a.s.delta) * weight;
          if (part.id === "body" && source[1] < this.rest.chest[1]) {
            const attached = neckTransform(source, this.rest, pose); target = attached.point; orientation = attached.angle;
          }
          const chosen = weight > .5 ? b.s : a.s;
          const d = sub(chosen.restEnd, chosen.start), size = Math.max(1, length(d)), across = (sub(source, chosen.start)[0] * d[1] - sub(source, chosen.start)[1] * d[0]) / size;
          const bulge = clamp(across / part.radius, -.92, .92) * .68;
          normalX = d[1] / size * bulge; normalY = -d[0] / size * bulge;
        }
        const rotated = rotate([normalX, normalY], orientation);
        const depth = part.depth + (part.id.includes("arm") || part.id.includes("leg") ? (pose.depth[part.chain[part.chain.length - 1]] ?? 0) * .6 : 0);
        position.setXYZ(i, target[0], target[1], depth);
        normal.setXYZ(i, rotated[0], rotated[1], Math.sqrt(Math.max(.05, 1 - normalX * normalX - normalY * normalY)));
      }
      position.needsUpdate = true; normal.needsUpdate = true;
      // Every part is a flat depth layer. Explicit painter ordering avoids an
      // almost-transparent hair texel writing depth and erasing skin behind it.
      mesh.renderOrder = part.depth + (part.id.includes("arm") || part.id.includes("leg") ? (pose.depth[part.chain[part.chain.length - 1]] ?? 0) * .6 : 0);
      const u = mesh.material.uniforms; u.lightMix.value = this.lightMix; u.lightStrength.value = this.lightStrength; u.mouth.value = pose.mouth * (1-authoredFace);
      u.inspection.value = this.inspectionMode === "art" ? 0 : 1;
      const wireframe = this.inspectionMode === "mesh" && (part.id === "left-arm" || !!layer.shoulder);
      if (mesh.material.wireframe !== wireframe) { mesh.material.wireframe = wireframe; mesh.material.needsUpdate = true; }
      blockers.forEach(([a, b, radius, depth], i) => { u.blockers.value[i].set(...a, ...b); u.blockerDepth.value[i].set(radius, depth); });
    }
    this.shadow.position.x = (j.rightAnkle[0] + j.leftAnkle[0]) / 2 - this.light.x * 55;
    this.shadow.position.y = Math.max(j.rightAnkle[1], j.leftAnkle[1]) + 123;
    this.shadow.visible = this.groundShadow;
    this.renderer.render(this.scene, this.camera);
  }
  private resize() {
    const { width, height } = this.mount.getBoundingClientRect(); if (!width || !height) return;
    this.renderer.setSize(width, height);
    const h = Math.max(this.framing.height, this.framing.minimumWidth * height / width), w = h * width / height;
    this.bounds = { left: this.framing.x - w / 2, top: this.framing.y - h / 2, width: w, height: h };
    this.camera.left = this.bounds.left; this.camera.right = this.bounds.left + w; this.camera.top = this.bounds.top; this.camera.bottom = this.bounds.top + h; this.camera.updateProjectionMatrix();
    this.render(this.pose, 0);
  }
  get viewBox() { return `${this.bounds.left} ${this.bounds.top} ${this.bounds.width} ${this.bounds.height}`; }
  imagePoint(clientX: number, clientY: number): Point {
    const rect = this.mount.getBoundingClientRect();
    return [clamp(this.bounds.left + (clientX - rect.left) / rect.width * this.bounds.width, 0, 1024), clamp(this.bounds.top + (clientY - rect.top) / rect.height * this.bounds.height, 0, 1536)];
  }
  get canvas() { return this.renderer.domElement; }
  dispose() {
    this.disposed = true; this.resizeObserver.disconnect();
    this.faceArtwork?.dispose();
    this.faceRig?.dispose();
    for (const { mesh } of this.layers) { (mesh.material.uniforms.artwork.value as THREE.Texture).dispose(); mesh.material.dispose(); mesh.geometry.dispose(); }
    for (const m of [this.backdrop, this.shadow]) { m.geometry.dispose(); (m.material as THREE.Material).dispose(); }
    this.shadowTexture.dispose(); this.renderer.dispose(); this.renderer.domElement.remove();
  }
}
