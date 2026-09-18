// Authoring/session data only. These are not Workflow Node contracts.
export type Point = [number, number];
export const JOINTS = ["root", "chest", "neck", "head", "rightShoulder", "rightElbow", "rightWrist", "leftShoulder", "leftElbow", "leftWrist", "rightHip", "rightKnee", "rightAnkle", "leftHip", "leftKnee", "leftAnkle"] as const;
export type Joint = typeof JOINTS[number];
export type Anchors = Record<Joint, Point>;
export const LABELS: Record<Joint, string> = { root: "골반 중심", chest: "가슴 중심", neck: "목", head: "머리", rightShoulder: "오른쪽 어깨", rightElbow: "오른쪽 팔꿈치", rightWrist: "오른쪽 손목", leftShoulder: "왼쪽 어깨", leftElbow: "왼쪽 팔꿈치", leftWrist: "왼쪽 손목", rightHip: "오른쪽 고관절", rightKnee: "오른쪽 무릎", rightAnkle: "오른쪽 발목", leftHip: "왼쪽 고관절", leftKnee: "왼쪽 무릎", leftAnkle: "왼쪽 발목" };
export const REST: Anchors = { root: [512, 686], chest: [512, 421], neck: [512, 311], head: [512, 205], rightShoulder: [401, 346], rightElbow: [337, 526], rightWrist: [261, 732], leftShoulder: [623, 346], leftElbow: [687, 526], leftWrist: [763, 732], rightHip: [441, 738], rightKnee: [416, 1040], rightAnkle: [393, 1363], leftHip: [583, 738], leftKnee: [608, 1040], leftAnkle: [631, 1363] };
export const CONNECTIONS: [Joint, Joint][] = [["root", "chest"], ["chest", "neck"], ["neck", "head"], ["chest", "rightShoulder"], ["rightShoulder", "rightElbow"], ["rightElbow", "rightWrist"], ["chest", "leftShoulder"], ["leftShoulder", "leftElbow"], ["leftElbow", "leftWrist"], ["root", "rightHip"], ["rightHip", "rightKnee"], ["rightKnee", "rightAnkle"], ["root", "leftHip"], ["leftHip", "leftKnee"], ["leftKnee", "leftAnkle"]];
export interface RigProfile { schema_version: "avatar.puppet2d.v1"; asset: "cat-2d-v1"; anchors: Anchors }
export const freshProfile = (): RigProfile => ({ schema_version: "avatar.puppet2d.v1", asset: "cat-2d-v1", anchors: structuredClone(REST) });
export function parseProfile(value: unknown): RigProfile {
  const p = value as RigProfile;
  if (!p || p.schema_version !== "avatar.puppet2d.v1" || p.asset !== "cat-2d-v1" || !p.anchors) throw new Error("이 아바타용 2D 리그 파일이 아닙니다.");
  for (const key of JOINTS) {
    const v = p.anchors[key];
    if (!Array.isArray(v) || v.length !== 2 || v.some((n) => !Number.isFinite(n)) || v[0] < 0 || v[0] > 1024 || v[1] < 0 || v[1] > 1536) throw new Error("관절 위치가 이미지 범위를 벗어났습니다.");
  }
  for (const [a, b] of CONNECTIONS) if (length(sub(p.anchors[b], p.anchors[a])) < 12) throw new Error("서로 연결된 관절 사이에 간격이 필요합니다.");
  return { schema_version: p.schema_version, asset: p.asset, anchors: Object.fromEntries(JOINTS.map((j) => [j, [...p.anchors[j]]])) as Anchors };
}
export type Landmark = [number, number, number, number];
export interface PerformanceFrame { time: number; pose: Landmark[]; world?: Landmark[]; face?: Record<string, number>; expressions?: Record<string, number>; faceLandmarks?: Landmark[]; faceDetected?: boolean }
export interface Performance { schema_version: "avatar.performance.v1"; width: number; height: number; duration: number; fps: number; frames: PerformanceFrame[] }
export interface Pose { joints: Anchors; depth: Partial<Record<Joint, number>>; headTurn: number; headTilt: number; blink: number; mouth: number; smile: number }
export const clamp = (n: number, a: number, b: number) => Math.max(a, Math.min(b, Number.isFinite(n) ? n : 0));
export const sub = (a: Point, b: Point): Point => [a[0] - b[0], a[1] - b[1]];
export const add = (a: Point, b: Point): Point => [a[0] + b[0], a[1] + b[1]];
export const length = (v: Point) => Math.hypot(v[0], v[1]);
export const angle = (v: Point) => Math.atan2(v[1], v[0]);
export const rotate = (v: Point, a: number): Point => [v[0] * Math.cos(a) - v[1] * Math.sin(a), v[0] * Math.sin(a) + v[1] * Math.cos(a)];
export const mix = (a: number, b: number, t: number) => a + (b - a) * t;
export const angleDelta = (a: number, b: number) => Math.atan2(Math.sin(a - b), Math.cos(a - b));
export const neutralPose = (rest: Anchors = REST): Pose => ({ joints: structuredClone(rest), depth: {}, headTurn: 0, headTilt: 0, blink: 0, mouth: 0, smile: 0 });

/** Solve in the image plane, retaining the target rig's lengths. Missing limbs hold their last pose. */
export function solvePose(frame: PerformanceFrame, rest: Anchors, aspect: number, previous?: Pose, origin?: Point): Pose {
  const p = frame.pose;
  if (p.length < 33) return previous ?? neutralPose(rest);
  const valid = (i: number) => p[i]?.slice(0, 3).every(Number.isFinite) && (p[i][3] ?? 1) >= .35;
  if (![11, 12, 23, 24].every(valid)) return previous ?? neutralPose(rest);
  const point = (i: number): Point => [p[i][0] * aspect, p[i][1]];
  const mid = (a: number, b: number): Point => [(point(a)[0] + point(b)[0]) / 2, (point(a)[1] + point(b)[1]) / 2];
  const hip = mid(23, 24), shoulders = mid(11, 12);
  const torsoLength = Math.max(.08, length(sub(shoulders, hip)));
  const scale = length(sub(rest.chest, rest.root)) / torsoLength;
  const base = origin ?? hip;
  const root: Point = [rest.root[0] + clamp((hip[0] - base[0]) * scale, -240, 240), rest.root[1] + clamp((hip[1] - base[1]) * scale, -160, 140)];
  const lean = clamp(angle(sub(shoulders, hip)) + Math.PI / 2, -.5, .5);
  const roll = clamp(angle(sub(point(11), point(12))), -.45, .45);
  const pelvis = clamp(angle(sub(point(23), point(24))), -.35, .35);
  const j = structuredClone(rest);
  j.root = root; j.chest = add(root, rotate(sub(rest.chest, rest.root), lean));
  j.neck = add(j.chest, rotate(sub(rest.neck, rest.chest), roll));
  j.head = add(j.neck, rotate(sub(rest.head, rest.neck), roll));
  for (const side of ["right", "left"] as const) {
    j[`${side}Shoulder`] = add(j.chest, rotate(sub(rest[`${side}Shoulder`], rest.chest), roll));
    j[`${side}Hip`] = add(root, rotate(sub(rest[`${side}Hip`], rest.root), pelvis));
  }
  const depth: Pose["depth"] = {};
  const segments: [Joint, Joint, number, number][] = [["rightShoulder", "rightElbow", 12, 14], ["rightElbow", "rightWrist", 14, 16], ["leftShoulder", "leftElbow", 11, 13], ["leftElbow", "leftWrist", 13, 15], ["rightHip", "rightKnee", 24, 26], ["rightKnee", "rightAnkle", 26, 28], ["leftHip", "leftKnee", 23, 25], ["leftKnee", "leftAnkle", 25, 27]];
  for (const [a, b, ai, bi] of segments) {
    let direction = sub(rest[b], rest[a]);
    if (valid(ai) && valid(bi)) direction = sub(point(bi), point(ai));
    else if (previous) direction = sub(previous.joints[b], previous.joints[a]);
    const size = Math.max(.00001, length(direction));
    const targetLength = length(sub(rest[b], rest[a]));
    j[b] = [j[a][0] + direction[0] / size * targetLength, j[a][1] + direction[1] / size * targetLength];
    depth[b] = valid(bi) ? clamp(-(p[bi][2] - (p[23][2] + p[24][2]) / 2) * 180, -70, 90) : previous?.depth[b] ?? 0;
  }
  // Eyes measure head roll, not the ear-to-nose vector that introduced a 90° rest offset.
  const eyeVector = valid(2) && valid(5) ? sub(point(2), point(5)) : [1, 0] as Point;
  const face = frame.face ?? {}, e = frame.expressions ?? {};
  const nose = point(0), eyeMid = mid(2, 5);
  const eyeSpan = Math.max(.015, length(eyeVector));
  const headTurn = clamp((nose[0] - eyeMid[0]) / eyeSpan, -.65, .65);
  const headTilt = clamp(angle(eyeVector), -.5, .5);
  return { joints: j, depth, headTurn, headTilt, blink: clamp(((e.eyeBlinkLeft ?? face.eye_blink_left ?? 0) + (e.eyeBlinkRight ?? face.eye_blink_right ?? 0)) / 2, 0, 1), mouth: clamp(e.jawOpen ?? face.mouth_open ?? 0, 0, 1), smile: clamp(((e.mouthSmileLeft ?? 0) + (e.mouthSmileRight ?? 0)) / 2, 0, 1) };
}
export function smoothPose(current: Pose, next: Pose, dt: number, smoothing: number): Pose {
  const t = 1 - Math.exp(-clamp(dt, 0, .1) / Math.max(.016, smoothing));
  const joints = Object.fromEntries(JOINTS.map((j) => [j, [mix(current.joints[j][0], next.joints[j][0], t), mix(current.joints[j][1], next.joints[j][1], t)]])) as Anchors;
  // Interpolating positions alone shrinks limbs during fast turns. Reproject each
  // child to the current target length after smoothing, in parent-first order.
  for (const [a, b] of CONNECTIONS) {
    const direction = sub(joints[b], joints[a]), size = length(direction);
    const targetLength = length(sub(next.joints[b], next.joints[a]));
    if (size > 1e-5) joints[b] = [joints[a][0] + direction[0] / size * targetLength, joints[a][1] + direction[1] / size * targetLength];
  }
  return { joints, depth: Object.fromEntries(JOINTS.map((j) => [j, mix(current.depth[j] ?? 0, next.depth[j] ?? 0, t)])), headTurn: mix(current.headTurn, next.headTurn, t), headTilt: mix(current.headTilt, next.headTilt, t), blink: mix(current.blink, next.blink, t), mouth: mix(current.mouth, next.mouth, t), smile: mix(current.smile, next.smile, t) };
}
export function frameAt(performance: Performance, time: number): PerformanceFrame {
  const index = Math.min(performance.frames.length - 1, Math.max(0, Math.round(time * performance.fps)));
  return performance.frames[index];
}
export function hipOrigin(frame: PerformanceFrame, aspect: number): Point | undefined {
  if (frame.pose.length < 25 || ![23, 24].every((i) => frame.pose[i].slice(0, 3).every(Number.isFinite) && frame.pose[i][3] >= .35)) return;
  return [(frame.pose[23][0] + frame.pose[24][0]) / 2 * aspect, (frame.pose[23][1] + frame.pose[24][1]) / 2];
}

export const smoothRange = (a: number, b: number, v: number) => { const t = clamp((v - a) / (b - a), 0, 1); return t * t * (3 - 2 * t); };
export function torsoTransform(point: Point, rest: Anchors, pose: Pose) {
  const a = angleDelta(angle(sub(pose.joints.neck, pose.joints.chest)), angle(sub(rest.neck, rest.chest)));
  return { point: add(pose.joints.chest, rotate(sub(point, rest.chest), a)), angle: a };
}

export function neckTransform(point: Point, rest: Anchors, pose: Pose) {
  const body = torsoTransform(point, rest, pose);
  const x = point[0] - rest.head[0], face = Math.max(0, 1 - (x / 170) ** 2);
  const head = add(pose.joints.head, rotate([x + pose.headTurn * 32 * face, point[1] - rest.head[1]], pose.headTilt));
  const influence = (1 - smoothRange(rest.neck[1] - 44, rest.neck[1] + 25, point[1])) * (1 - smoothRange(45, 65, Math.abs(x)));
  return { point: [mix(body.point[0], head[0], influence), mix(body.point[1], head[1], influence)] as Point, angle: body.angle + angleDelta(pose.headTilt, body.angle) * influence };
}
