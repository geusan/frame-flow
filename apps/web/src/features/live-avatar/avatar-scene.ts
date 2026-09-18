import {
  AnimationClip, Bone, Box3, BufferAttribute, CircleGeometry, Color, DirectionalLight, DoubleSide, Euler, Group, HemisphereLight, Matrix4, Mesh, Object3D, PropertyBinding,
  PerspectiveCamera, Quaternion, Raycaster, Scene, SkinnedMesh, SphereGeometry,
  MeshBasicMaterial, Texture, Vector2, Vector3, WebGLRenderer, SRGBColorSpace, NeutralToneMapping,
} from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { GLTFExporter } from "three/addons/exporters/GLTFExporter.js";
import { MeshoptDecoder } from "three/addons/libs/meshopt_decoder.module.js";
import { buildStarterRig } from "./starter-rig";
import { SurfaceEyeGaze, rotateEye } from "./eye-gaze";
import { applyMorphValues, restoreMorphGeometry } from "./morph-binding";
import { FACE_CHANNELS, expressionChannels, GAZE_CHANNELS, gazeMorphs, neutralGaze, smoothGaze, neutralFace, smoothFace, type Gaze, type AnchorName, type FaceValues, type FaceProfile, type Point3 } from "./face-state";

export class AvatarScene {
  readonly scene = new Scene();
  readonly camera = new PerspectiveCamera(32, 1, .001, 100);
  readonly renderer = new WebGLRenderer({ antialias: true, alpha: false });
  readonly controls: OrbitControls;
  root: Group | null = null;
  meshes: SkinnedMesh[] = [];
  morphMeshes: Mesh[] = [];
  bones: Bone[] = [];
  profile: FaceProfile | null = null;
  targetValues = neutralFace();
  targetRotation = new Quaternion();
  targetGaze = neutralGaze();
  gazeError: string | null = null;
  embeddedProfile: unknown = null;
  onPick: ((name: AnchorName, point: Point3) => void) | null = null;
  picking: AnchorName | null = null;
  private rest = new Map<Bone, Quaternion>();
  private values = neutralFace();
  private appliedRotation = new Quaternion();
  private markers = new Group();
  private disposed = false;
  private frame = 0;
  private lastTime = 0;
  private resize: ResizeObserver;
  private height = 1;
  private mount: HTMLElement;
  private original = new Map<SkinnedMesh, SkinnedMesh["geometry"]>();
  private originalMorphNames = new Map<SkinnedMesh, Record<string, number> | undefined>();
  private rootRotation = new Quaternion();
  private pointerStart = new Vector2();
  private rawNames = new Map<Object3D, string>();
  private mouthMesh: Mesh | null = null;
  private animations: AnimationClip[] = [];
  private eyeSurface: SurfaceEyeGaze | null = null;
  private gaze = neutralGaze();
  private headRestWorld = new Quaternion();

  constructor(mount: HTMLElement) {
    this.mount = mount;
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.outputColorSpace = SRGBColorSpace;
    this.renderer.toneMapping = NeutralToneMapping;
    this.renderer.setClearColor(new Color("#edf0e8"));
    this.renderer.domElement.setAttribute("aria-label", "Live avatar 3D preview");
    mount.appendChild(this.renderer.domElement);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.scene.add(new HemisphereLight(0xffffff, 0x849070, 2.5));
    const light = new DirectionalLight(0xffffff, 2.3); light.position.set(2, 3, 4); this.scene.add(light);
    this.scene.add(this.markers);
    this.resize = new ResizeObserver(() => {
      const { clientWidth: width, clientHeight: height } = mount;
      if (!width || !height) return;
      this.renderer.setSize(width, height); this.camera.aspect = width / height; this.camera.updateProjectionMatrix();
    });
    this.resize.observe(mount);
    this.renderer.domElement.addEventListener("pointerdown", this.pointerDown);
    this.renderer.domElement.addEventListener("pointerup", this.pointerUp);
    const tick = (time: number) => {
      if (this.disposed) return;
      const dt = Math.min(.1, (time - this.lastTime) / 1000); this.lastTime = time;
      this.values = smoothFace(this.values, this.targetValues, dt, this.profile?.smoothing ?? .09);
      this.gaze = smoothGaze(this.gaze, this.targetGaze, dt, this.profile?.gaze.smoothing ?? .12);
      this.applyFace(this.values, dt);
      this.applyGaze(this.gaze);
      this.controls.update(); this.renderer.render(this.scene, this.camera);
      this.frame = requestAnimationFrame(tick);
    };
    this.frame = requestAnimationFrame(tick);
  }

  async load(src: string) {
    const gltf = await new GLTFLoader().setMeshoptDecoder(MeshoptDecoder).loadAsync(src);
    if (this.disposed) { this.release(gltf.scene); return; }
    this.root = gltf.scene;
    this.animations = gltf.animations;
    this.rootRotation.copy(this.root.quaternion);
    this.root.updateMatrixWorld(true);
    this.root.traverse((object) => {
      if (object.userData.faceProfilePrepared && object.userData.faceProfile) this.embeddedProfile = object.userData.faceProfile;
      const nodeIndex = gltf.parser.associations.get(object)?.nodes;
      const originalName = nodeIndex === undefined ? undefined : gltf.parser.json.nodes[nodeIndex]?.name;
      if (typeof originalName === "string") this.rawNames.set(object, originalName);
      if (object instanceof Mesh) this.morphMeshes.push(object);
      if (object instanceof SkinnedMesh) { this.meshes.push(object); this.original.set(object, object.geometry); this.originalMorphNames.set(object, object.morphTargetDictionary ? { ...object.morphTargetDictionary } : undefined); object.frustumCulled = false; }
      if (object instanceof Bone) { this.bones.push(object); this.rest.set(object, object.quaternion.clone()); }
    });
    this.scene.add(this.root);
    const box = new Box3().setFromObject(this.root);
    this.height = box.getSize(new Vector3()).y || 1;
    this.camera.near = this.height / 1000; this.camera.far = this.height * 100; this.camera.updateProjectionMatrix();
    this.focus(true);
  }

  focus(face: boolean) {
    if (!this.root) return;
    const box = new Box3().setFromObject(this.root); const center = box.getCenter(new Vector3());
    center.y = face ? box.max.y - this.height * .12 : center.y;
    const radius = this.height * (face ? .58 : 2.1);
    this.controls.target.copy(center); this.camera.position.copy(center).add(new Vector3(0, 0, radius));
    this.controls.minDistance = this.height * .1; this.controls.maxDistance = this.height * 5;
    this.controls.update();
  }

  useProfile(profile: FaceProfile) {
    this.eyeSurface?.dispose(); this.eyeSurface = null; this.gazeError = null;
    this.profile = profile;
    const yaw = { "+x": -Math.PI / 2, "-x": Math.PI / 2, "+z": 0, "-z": Math.PI }[profile.front_axis];
    this.root?.quaternion.copy(this.rootRotation).multiply(new Quaternion().setFromAxisAngle(new Vector3(0, 1, 0), yaw));
    this.resetPose();
    if (this.mouthMesh) { this.mouthMesh.removeFromParent(); this.mouthMesh.geometry.dispose(); (this.mouthMesh.material as MeshBasicMaterial).dispose(); this.mouthMesh = null; }
    for (const mesh of this.meshes) {
      if (mesh.geometry !== this.original.get(mesh)) mesh.geometry.dispose();
      restoreMorphGeometry(mesh, this.original.get(mesh)!, this.originalMorphNames.get(mesh));
    }
    if (profile.mode === "starter" && Object.keys(profile.anchors).length === 3) {
      const mesh = this.meshes.find((mesh) => mesh.name === profile.mesh);
      if (!mesh) throw new Error("얼굴 메시를 선택해 주세요.");
      buildStarterRig(mesh, profile);
      if (profile.mouth_patch !== false) this.createMouthPatch(mesh, profile);
    }
    this.showMarkers();
    const head = this.bones.find((bone) => bone.name === profile.head_bone);
    this.headRestWorld.copy(head?.getWorldQuaternion(new Quaternion()) ?? new Quaternion());
    if (profile.gaze.enabled) {
      try {
        if (profile.gaze.method === "surface") {
          const mesh = this.meshes.find((mesh) => mesh.name === profile.mesh);
          if (!mesh) throw new Error("시선에 사용할 얼굴 메시를 선택해 주세요.");
          this.eyeSurface = new SurfaceEyeGaze(mesh, profile);
        } else if (profile.gaze.method === "bones") {
          const names = [profile.gaze.left_eye_bone, profile.gaze.right_eye_bone];
          if (!names[0] || !names[1] || names[0] === names[1] || names.includes(profile.head_bone) || names.some((name) => !this.bones.some((bone) => bone.name === name))) throw new Error("서로 다른 왼쪽·오른쪽 안구 뼈대를 선택해 주세요.");
        } else if (!GAZE_CHANNELS.some((channel) => this.morphMeshes.some((mesh) => mesh.morphTargetDictionary?.[profile.mappings[channel]] !== undefined))) throw new Error("시선 모프를 하나 이상 연결해 주세요.");
      } catch (error) { this.gazeError = error instanceof Error ? error.message : "시선 설정을 확인해 주세요."; }
    }
  }

  setPicking(name: AnchorName | null) { this.picking = name; this.controls.enableRotate = !name; this.showMarkers(); }

  resetPose() {
    this.targetValues = neutralFace(); this.values = neutralFace();
    this.targetRotation.identity(); this.appliedRotation.identity();
    this.targetGaze = neutralGaze(); this.gaze = neutralGaze();
    this.bones.forEach((bone) => bone.quaternion.copy(this.rest.get(bone)!));
    this.morphMeshes.forEach((mesh) => mesh.morphTargetInfluences?.fill(0));
    this.mouthMesh?.morphTargetInfluences?.fill(0);
    this.root?.updateMatrixWorld(true);
    this.eyeSurface?.update(this.gaze, this.values);
  }

  private applyFace(values: FaceValues, dt: number) {
    const profile = this.profile;
    if (!profile || this.picking) return;
    applyMorphValues([...this.morphMeshes, ...(this.mouthMesh ? [this.mouthMesh] : [])], expressionChannels(profile), values,
      profile.mode === "starter" ? Object.fromEntries(FACE_CHANNELS.map((key) => [key, key])) : profile.mappings);
    const head = this.bones.find((bone) => bone.name === profile.head_bone);
    if (head) {
      head.quaternion.copy(this.rest.get(head)!);
      head.parent?.updateWorldMatrix(true, false);
      const parent = head.parent?.getWorldQuaternion(new Quaternion()) ?? new Quaternion();
      this.appliedRotation.slerp(this.targetRotation, 1 - Math.exp(-dt / (profile.smoothing || .09)));
      head.quaternion.copy(parent.clone().invert().multiply(this.appliedRotation).multiply(parent).multiply(this.rest.get(head)!));
    }
  }

  setHeadMatrix(matrix: number[], baseline: number[] | null) {
    if (matrix.length !== 16) { this.targetRotation.identity(); return; }
    const q = new Quaternion().setFromRotationMatrix(new Matrix4().fromArray(matrix)).normalize();
    if (baseline?.length === 16) q.premultiply(new Quaternion().setFromRotationMatrix(new Matrix4().fromArray(baseline)).invert());
    const angles = new Euler().setFromQuaternion(q, "YXZ");
    angles.x = Math.max(-.45, Math.min(.45, angles.x));
    angles.y = Math.max(-.75, Math.min(.75, angles.y));
    angles.z = Math.max(-.35, Math.min(.35, angles.z));
    this.targetRotation.setFromEuler(angles);
  }

  private applyGaze(gaze: Gaze) {
    const profile = this.profile;
    if (!profile?.gaze.enabled || this.gazeError || this.picking) return;
    if (profile.gaze.method === "surface") this.eyeSurface?.update(gaze, this.values);
    else if (profile.gaze.method === "morphs") {
      const weights = gazeMorphs(gaze);
      for (const mesh of this.morphMeshes) for (const channel of GAZE_CHANNELS) {
        const index = mesh.morphTargetDictionary?.[profile.mappings[channel]];
        if (index !== undefined && mesh.morphTargetInfluences) mesh.morphTargetInfluences[index] = weights[channel];
      }
    } else {
      const head = this.bones.find((bone) => bone.name === profile.head_bone);
      const delta = (head?.getWorldQuaternion(new Quaternion()) ?? this.headRestWorld.clone()).multiply(this.headRestWorld.clone().invert());
      for (const name of [profile.gaze.left_eye_bone, profile.gaze.right_eye_bone]) {
        const eye = this.bones.find((bone) => bone.name === name);
        if (eye) rotateEye(eye, this.rest.get(eye)!, delta, gaze, profile.gaze.max_angle);
      }
    }
  }

  private showMarkers() {
    this.markers.children.forEach((object) => { if (object instanceof Mesh) { object.geometry.dispose(); (object.material as MeshBasicMaterial).dispose(); } });
    this.markers.clear();
    if (!this.picking || !this.profile) return;
    const mesh = this.meshes.find((mesh) => mesh.name === this.profile!.mesh);
    if (!mesh) return;
    for (const point of Object.values(this.profile.anchors)) {
      const marker = new Mesh(new SphereGeometry(this.height * .004), new MeshBasicMaterial({ color: "#ae54f5", depthTest: false }));
      marker.position.copy(mesh.localToWorld(new Vector3(...point!))); marker.renderOrder = 10; this.markers.add(marker);
    }
  }

  private pointerDown = (event: PointerEvent) => { this.pointerStart.set(event.clientX, event.clientY); };
  private pointerUp = (event: PointerEvent) => {
    if (!this.picking || !this.profile || this.pointerStart.distanceTo(new Vector2(event.clientX, event.clientY)) > 5) return;
    const mesh = this.meshes.find((mesh) => mesh.name === this.profile!.mesh); if (!mesh) return;
    this.resetPose();
    const rect = this.renderer.domElement.getBoundingClientRect();
    const ray = new Raycaster(); ray.setFromCamera(new Vector2((event.clientX - rect.left) / rect.width * 2 - 1, -(event.clientY - rect.top) / rect.height * 2 + 1), this.camera);
    const hit = ray.intersectObject(mesh, false)[0];
    if (hit) this.onPick?.(this.picking, mesh.worldToLocal(hit.point).toArray() as Point3);
  };

  async exportGlb(): Promise<ArrayBuffer> {
    if (!this.root) throw new Error("아바타를 먼저 불러와 주세요.");
    this.resetPose();
    this.root.userData.faceProfilePrepared = true;
    this.root.userData.faceProfile = this.profile ? { ...this.profile, front_axis: "+z", mode: "native", mappings: this.profile.mode === "starter" ? { ...this.profile.mappings, ...Object.fromEntries(FACE_CHANNELS.map((key) => [key, key])) } : this.profile.mappings } : null;
    const portableProfile = this.root.userData.faceProfile;
    this.root.traverse((object) => { if (object.userData.faceProfilePrepared) object.userData.faceProfile = portableProfile; });
    const animations = this.animations.map((clip) => {
      const copy = clip.clone();
      for (const track of copy.tracks) {
        const parsed = PropertyBinding.parseTrackName(track.name);
        const node = PropertyBinding.findNode(this.root!, parsed.nodeName);
        if (node instanceof Object3D && parsed.nodeName) track.name = track.name.replace(parsed.nodeName, node.uuid);
      }
      return copy;
    });
    const loadedNames = new Map([...this.rawNames.keys()].map((object) => [object, object.name]));
    this.rawNames.forEach((name, object) => { object.name = name; });
    try { return await new GLTFExporter().parseAsync(this.root, { binary: true, onlyVisible: true, animations }) as ArrayBuffer; }
    finally { loadedNames.forEach((name, object) => { object.name = name; }); }
  }

  private createMouthPatch(mesh: SkinnedMesh, profile: FaceProfile) {
    const head = this.bones.find((bone) => bone.name === profile.head_bone);
    if (!head || !profile.anchors.leftEye || !profile.anchors.rightEye || !profile.anchors.mouth) return;
    head.updateWorldMatrix(true, false);
    const left = mesh.localToWorld(new Vector3(...profile.anchors.leftEye));
    const right = mesh.localToWorld(new Vector3(...profile.anchors.rightEye));
    const center = mesh.localToWorld(new Vector3(...profile.anchors.mouth));
    const distance = left.distanceTo(right), across = left.sub(right).normalize(), up = new Vector3(0, 1, 0);
    up.addScaledVector(across, -up.dot(across)).normalize();
    const forward = across.clone().cross(up).normalize();
    const inverse = head.matrixWorld.clone().invert();
    const geometry = new CircleGeometry(1, 32), position = geometry.getAttribute("position");
    const offsets = new Float32Array(position.count * 3), smile = new Float32Array(position.count * 3);
    for (let i = 0; i < position.count; i++) {
      const x = position.getX(i), y = position.getY(i);
      const base = center.clone().addScaledVector(forward, distance * .06);
      const open = base.clone().addScaledVector(across, x * distance * .25).addScaledVector(up, (y * .12 - .045) * distance).applyMatrix4(inverse);
      const raised = base.clone().addScaledVector(up, distance * .04).applyMatrix4(inverse);
      base.applyMatrix4(inverse); position.setXYZ(i, base.x, base.y, base.z); offsets.set(open.sub(base).toArray(), i * 3); smile.set(raised.sub(base).toArray(), i * 3);
    }
    const morph = new BufferAttribute(offsets, 3); morph.name = "jawOpen";
    const smileLeft = new BufferAttribute(smile, 3); smileLeft.name = "mouthSmileLeft";
    const smileRight = new BufferAttribute(smile.slice(), 3); smileRight.name = "mouthSmileRight";
    geometry.morphAttributes.position = [morph, smileLeft, smileRight]; geometry.morphTargetsRelative = true;
    const patch = new Mesh(geometry, new MeshBasicMaterial({ color: "#28131b", side: DoubleSide }));
    patch.name = "LiveAvatarMouth"; patch.frustumCulled = false; head.add(patch); this.mouthMesh = patch;
  }

  private release(root: Group) {
    const geometries = new Set(this.original.values());
    root.traverse((object) => {
      if (!(object instanceof Mesh)) return;
      geometries.add(object.geometry);
      for (const material of Array.isArray(object.material) ? object.material : [object.material]) {
        for (const value of Object.values(material)) if (value instanceof Texture) value.dispose();
        material.dispose();
      }
    });
    geometries.forEach((geometry) => geometry.dispose());
  }

  dispose() {
    this.eyeSurface?.dispose(); this.eyeSurface = null;
    this.disposed = true; cancelAnimationFrame(this.frame); this.resize.disconnect(); this.controls.dispose();
    this.renderer.domElement.removeEventListener("pointerdown", this.pointerDown); this.renderer.domElement.removeEventListener("pointerup", this.pointerUp);
    if (this.root) this.release(this.root);
    this.markers.traverse((object) => { if (object instanceof Mesh) { object.geometry.dispose(); (object.material as MeshBasicMaterial).dispose(); } });
    this.renderer.dispose(); this.renderer.forceContextLoss(); this.renderer.domElement.remove();
  }
}
