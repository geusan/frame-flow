export const FACE_CHANNELS = ["eyeBlinkLeft", "eyeBlinkRight", "jawOpen", "mouthSmileLeft", "mouthSmileRight", "browInnerUp"] as const;
/** ARKit-compatible expression targets. Eye-look is handled by the gaze adapter. */
export const EXPRESSION_CHANNELS = [
  "browDownLeft", "browDownRight", "browInnerUp", "browOuterUpLeft", "browOuterUpRight",
  "cheekPuff", "cheekSquintLeft", "cheekSquintRight", "eyeBlinkLeft", "eyeBlinkRight",
  "eyeSquintLeft", "eyeSquintRight", "eyeWideLeft", "eyeWideRight",
  "jawForward", "jawLeft", "jawOpen", "jawRight", "mouthClose", "mouthDimpleLeft", "mouthDimpleRight",
  "mouthFrownLeft", "mouthFrownRight", "mouthFunnel", "mouthLeft", "mouthLowerDownLeft", "mouthLowerDownRight",
  "mouthPressLeft", "mouthPressRight", "mouthPucker", "mouthRight", "mouthRollLower", "mouthRollUpper",
  "mouthShrugLower", "mouthShrugUpper", "mouthSmileLeft", "mouthSmileRight", "mouthStretchLeft", "mouthStretchRight",
  "mouthUpperUpLeft", "mouthUpperUpRight", "noseSneerLeft", "noseSneerRight", "tongueOut",
] as const;
export type FaceChannel = typeof EXPRESSION_CHANNELS[number];
export type FaceValues = Record<FaceChannel, number>;
export type Point3 = [number, number, number];
export type AnchorName = "leftEye" | "rightEye" | "mouth";
export const FACE_LABELS: Record<FaceChannel, string> = {
  eyeBlinkLeft: "왼눈 감기", eyeBlinkRight: "오른눈 감기", jawOpen: "입 벌리기", mouthSmileLeft: "왼쪽 미소", mouthSmileRight: "오른쪽 미소", browInnerUp: "눈썹 올리기",
  browDownLeft: "왼쪽 눈썹 찡그리기", browDownRight: "오른쪽 눈썹 찡그리기", browOuterUpLeft: "왼쪽 눈썹 끝 올리기", browOuterUpRight: "오른쪽 눈썹 끝 올리기",
  cheekPuff: "볼 부풀리기", cheekSquintLeft: "왼쪽 볼 올리기", cheekSquintRight: "오른쪽 볼 올리기",
  eyeSquintLeft: "왼눈 가늘게 뜨기", eyeSquintRight: "오른눈 가늘게 뜨기", eyeWideLeft: "왼눈 크게 뜨기", eyeWideRight: "오른눈 크게 뜨기",
  jawForward: "턱 앞으로", jawLeft: "턱 왼쪽", jawRight: "턱 오른쪽", mouthClose: "입술 닫기",
  mouthDimpleLeft: "왼쪽 입꼬리 당기기", mouthDimpleRight: "오른쪽 입꼬리 당기기", mouthFrownLeft: "왼쪽 입꼬리 내리기", mouthFrownRight: "오른쪽 입꼬리 내리기",
  mouthFunnel: "입 모으기 · 오", mouthPucker: "입 내밀기 · 우", mouthLeft: "입 왼쪽", mouthRight: "입 오른쪽",
  mouthLowerDownLeft: "왼쪽 아랫입술 내리기", mouthLowerDownRight: "오른쪽 아랫입술 내리기", mouthUpperUpLeft: "왼쪽 윗입술 올리기", mouthUpperUpRight: "오른쪽 윗입술 올리기",
  mouthPressLeft: "왼쪽 입술 누르기", mouthPressRight: "오른쪽 입술 누르기", mouthRollLower: "아랫입술 말기", mouthRollUpper: "윗입술 말기",
  mouthShrugLower: "아랫입술 올리기", mouthShrugUpper: "윗입술 올리기", mouthStretchLeft: "입 왼쪽 늘리기", mouthStretchRight: "입 오른쪽 늘리기",
  noseSneerLeft: "왼쪽 코 찡그리기", noseSneerRight: "오른쪽 코 찡그리기", tongueOut: "혀 내밀기 · 수동 테스트",
};
export const EXPRESSION_GROUPS: { label: string; channels: readonly FaceChannel[] }[] = [
  { label: "눈 · 눈썹", channels: EXPRESSION_CHANNELS.filter((key) => /^(eye|brow)/.test(key)) },
  { label: "입 · 턱", channels: EXPRESSION_CHANNELS.filter((key) => /^(mouth|jaw|tongue)/.test(key)) },
  { label: "볼 · 코", channels: EXPRESSION_CHANNELS.filter((key) => /^(cheek|nose)/.test(key)) },
];
export const EXPRESSION_PRESETS: { label: string; values: Partial<FaceValues> }[] = [
  { label: "미소", values: { mouthSmileLeft: .65, mouthSmileRight: .65, cheekSquintLeft: .3, cheekSquintRight: .3 } },
  { label: "웃음", values: { jawOpen: .5, mouthSmileLeft: .8, mouthSmileRight: .8, eyeSquintLeft: .45, eyeSquintRight: .45, cheekSquintLeft: .4, cheekSquintRight: .4 } },
  { label: "놀람", values: { jawOpen: .6, browInnerUp: .6, browOuterUpLeft: .4, browOuterUpRight: .4, eyeWideLeft: .6, eyeWideRight: .6 } },
  { label: "슬픔", values: { browInnerUp: .6, browDownLeft: .2, browDownRight: .2, mouthFrownLeft: .55, mouthFrownRight: .55 } },
  { label: "찡그림", values: { browDownLeft: .65, browDownRight: .65, eyeSquintLeft: .25, eyeSquintRight: .25, noseSneerLeft: .3, noseSneerRight: .3, mouthPressLeft: .5, mouthPressRight: .5 } },
  { label: "입 오므리기", values: { mouthPucker: .75, mouthFunnel: .2 } },
];
export interface ChannelResponse { gain: number; deadzone: number; max: number }
export interface ExpressionSettings { preset: "basic" | "extended"; channels: Partial<Record<FaceChannel, ChannelResponse>> }
export const defaultExpressions = (preset: ExpressionSettings["preset"] = "basic"): ExpressionSettings => ({ preset, channels: {} });
export const defaultResponse = (): ChannelResponse => ({ gain: 1, deadzone: 0, max: 1 });
export const expressionChannels = (profile: Pick<FaceProfile, "mode" | "expressions">): readonly FaceChannel[] => profile.mode === "starter" || profile.expressions.preset === "basic" ? FACE_CHANNELS : EXPRESSION_CHANNELS;
export const ANCHOR_LABELS: Record<AnchorName, string> = { leftEye: "아바타 왼눈", rightEye: "아바타 오른눈", mouth: "입 중앙" };
export const neutralFace = (): FaceValues => Object.fromEntries(EXPRESSION_CHANNELS.map((key) => [key, 0])) as FaceValues;
export const unit = (value: number) => Number.isFinite(value) ? Math.max(0, Math.min(1, value)) : 0;
export const GAZE_CHANNELS = ["eyeLookInLeft", "eyeLookOutLeft", "eyeLookUpLeft", "eyeLookDownLeft", "eyeLookInRight", "eyeLookOutRight", "eyeLookUpRight", "eyeLookDownRight"] as const;
export const GAZE_LABELS: Record<typeof GAZE_CHANNELS[number], string> = { eyeLookInLeft: "왼눈 안쪽", eyeLookOutLeft: "왼눈 바깥쪽", eyeLookUpLeft: "왼눈 위", eyeLookDownLeft: "왼눈 아래", eyeLookInRight: "오른눈 안쪽", eyeLookOutRight: "오른눈 바깥쪽", eyeLookUpRight: "오른눈 위", eyeLookDownRight: "오른눈 아래" };
export interface Gaze { x: number; y: number }
export interface GazeSettings {
  enabled: boolean;
  method: "surface" | "bones" | "morphs";
  sensitivity: number;
  smoothing: number;
  deadzone: number;
  invert_x: boolean;
  invert_y: boolean;
  radius: number;
  range: number;
  max_angle: number;
  left_eye_bone: string;
  right_eye_bone: string;
}
export const neutralGaze = (): Gaze => ({ x: 0, y: 0 });
export const defaultGaze = (enabled = false): GazeSettings => ({ enabled, method: "surface", sensitivity: 2.5, smoothing: .12, deadzone: .04, invert_x: false, invert_y: false, radius: .32, range: .065, max_angle: 25, left_eye_bone: "", right_eye_bone: "" });
const signedUnit = (n: number) => Number.isFinite(n) ? Math.max(-1, Math.min(1, n)) : 0;

/** x is the character's left; preview mirroring does not swap tracker channels. */
export function estimateGaze(frame: Pick<FaceFrame, "detected" | "values">): Gaze & { valid: boolean } {
  if (!frame.detected) return { ...neutralGaze(), valid: false };
  const values = frame.values, eyes: Gaze[] = [];
  for (const side of ["Left", "Right"] as const) {
    if (unit(values[`eyeBlink${side}`] ?? 0) > .55) continue;
    if (["In", "Out", "Up", "Down"].some((dir) => !Number.isFinite(values[`eyeLook${dir}${side}`]))) continue;
    const inward = unit(values[`eyeLookIn${side}`]), outward = unit(values[`eyeLookOut${side}`]);
    eyes.push({ x: side === "Left" ? outward - inward : inward - outward, y: unit(values[`eyeLookUp${side}`]) - unit(values[`eyeLookDown${side}`]) });
  }
  if (!eyes.length) return { ...neutralGaze(), valid: false };
  return { x: eyes.reduce((sum, eye) => sum + eye.x, 0) / eyes.length, y: eyes.reduce((sum, eye) => sum + eye.y, 0) / eyes.length, valid: true };
}

export function calibratedGaze(raw: Gaze, center: Gaze, settings: GazeSettings): Gaze {
  if (!settings.enabled) return neutralGaze();
  const axis = (n: number, invert: boolean) => {
    const value = signedUnit(n * settings.sensitivity);
    const filtered = Math.max(0, Math.abs(value) - settings.deadzone) / (1 - settings.deadzone);
    return signedUnit(Math.sign(value) * filtered * (invert ? -1 : 1));
  };
  return { x: axis(raw.x - center.x, settings.invert_x), y: axis(raw.y - center.y, settings.invert_y) };
}

export function meanGaze(frames: FaceFrame[]): Gaze {
  const valid = frames.map(estimateGaze).filter((gaze) => gaze.valid);
  if (valid.length < 15) throw new Error("눈을 뜨고 카메라 정면을 바라본 뒤 시선을 다시 보정해 주세요.");
  return { x: valid.reduce((sum, gaze) => sum + gaze.x, 0) / valid.length, y: valid.reduce((sum, gaze) => sum + gaze.y, 0) / valid.length };
}

export function smoothGaze(current: Gaze, target: Gaze, elapsed: number, seconds: number): Gaze {
  const alpha = 1 - Math.exp(-Math.max(0, Math.min(elapsed, .1)) / Math.max(.02, seconds));
  return { x: current.x + (signedUnit(target.x) - current.x) * alpha, y: current.y + (signedUnit(target.y) - current.y) * alpha };
}

export function gazeMorphs(gaze: Gaze): Record<typeof GAZE_CHANNELS[number], number> {
  const x = signedUnit(gaze.x), y = signedUnit(gaze.y);
  return { eyeLookOutLeft: Math.max(0, x), eyeLookInLeft: Math.max(0, -x), eyeLookInRight: Math.max(0, x), eyeLookOutRight: Math.max(0, -x), eyeLookUpLeft: Math.max(0, y), eyeLookUpRight: Math.max(0, y), eyeLookDownLeft: Math.max(0, -y), eyeLookDownRight: Math.max(0, -y) };
}

export interface FaceFrame {
  landmarks?: [number, number, number][];
  detected: boolean;
  values: Record<string, number>;
  matrix: number[];
  timestamp: number;
}

export interface FaceProfile {
  schema_version: "avatar.face_profile.v3";
  source_sha256: string;
  mode: "native" | "starter";
  mesh: string;
  head_bone: string;
  front_axis: "+x" | "-x" | "+z" | "-z";
  anchors: Partial<Record<AnchorName, Point3>>;
  eye_radius: number;
  depth: number;
  gain: number;
  smoothing: number;
  mappings: Record<string, string>;
  mouth_patch?: boolean;
  gaze: GazeSettings;
  expressions: ExpressionSettings;
}

export function parseFaceProfile(value: unknown, sha: string): FaceProfile {
  if (!value || typeof value !== "object") throw new Error("얼굴 설정 파일이 올바르지 않습니다.");
  const version = (value as { schema_version?: string }).schema_version;
  if (!["avatar.face_profile.v1", "avatar.face_profile.v2", "avatar.face_profile.v3"].includes(version ?? "")) throw new Error("얼굴 설정 버전을 지원하지 않습니다.");
  const p: FaceProfile = { ...(value as FaceProfile), schema_version: "avatar.face_profile.v3", gaze: version === "avatar.face_profile.v1" ? defaultGaze(false) : (value as FaceProfile).gaze, expressions: version === "avatar.face_profile.v3" ? (value as FaceProfile).expressions : defaultExpressions() };
  if (p.source_sha256 !== sha) throw new Error("이 아바타와 일치하는 얼굴 설정이 아닙니다.");
  if (!["native", "starter"].includes(p.mode) || typeof p.mesh !== "string" || typeof p.head_bone !== "string") throw new Error("얼굴 리그 설정이 누락됐습니다.");
  if (!["+x", "-x", "+z", "-z"].includes(p.front_axis)) throw new Error("아바타 정면 방향이 올바르지 않습니다.");
  if (!p.anchors || !p.mappings || typeof p.mappings !== "object") throw new Error("얼굴 매핑이 누락됐습니다.");
  if (p.mouth_patch !== undefined && typeof p.mouth_patch !== "boolean") throw new Error("입 안쪽 표현 설정이 올바르지 않습니다.");
  for (const key of Object.keys(p.anchors)) {
    if (!(key in ANCHOR_LABELS)) throw new Error("알 수 없는 얼굴 기준점입니다.");
    const point = p.anchors[key as AnchorName];
    if (!Array.isArray(point) || point.length !== 3 || point.some((n) => !Number.isFinite(n))) throw new Error("얼굴 기준점이 올바르지 않습니다.");
  }
  for (const [key, min, max] of [["eye_radius", .15, .55], ["depth", .05, .7], ["gain", .5, 3], ["smoothing", .02, .5]] as const) {
    if (!Number.isFinite(p[key]) || p[key] < min || p[key] > max) throw new Error(`얼굴 설정 범위 오류: ${key}`);
  }
  if (Object.values(p.mappings).some((name) => typeof name !== "string" || name.length > 200)) throw new Error("표정 매핑 이름이 올바르지 않습니다.");
  const g = p.gaze;
  if (!g || !["surface", "bones", "morphs"].includes(g.method)) throw new Error("시선 연결 방식이 올바르지 않습니다.");
  for (const key of ["enabled", "invert_x", "invert_y"] as const) if (typeof g[key] !== "boolean") throw new Error("시선 설정이 올바르지 않습니다.");
  for (const key of ["left_eye_bone", "right_eye_bone"] as const) if (typeof g[key] !== "string" || g[key].length > 200) throw new Error("안구 뼈대 이름이 올바르지 않습니다.");
  for (const [key, min, max] of [["sensitivity", .5, 6], ["smoothing", .02, .5], ["deadzone", 0, .3], ["radius", .15, .5], ["range", .01, .15], ["max_angle", 5, 40]] as const) {
    if (!Number.isFinite(g[key]) || g[key] < min || g[key] > max) throw new Error(`시선 설정 범위 오류: ${key}`);
  }
  const expressions = p.expressions;
  if (!expressions || !["basic", "extended"].includes(expressions.preset) || !expressions.channels || typeof expressions.channels !== "object" || Array.isArray(expressions.channels)) throw new Error("표정 범위 설정이 올바르지 않습니다.");
  for (const [name, response] of Object.entries(expressions.channels)) {
    if (!(EXPRESSION_CHANNELS as readonly string[]).includes(name) || !response || typeof response !== "object") throw new Error("알 수 없는 표정 보정 설정입니다.");
    for (const [key, min, max] of [["gain", 0, 3], ["deadzone", 0, .5], ["max", 0, 1]] as const) {
      if (!Number.isFinite(response[key]) || response[key] < min || response[key] > max) throw new Error(`표정 보정 범위 오류: ${name}.${key}`);
    }
  }
  return p;
}

export function calibratedValues(values: Record<string, number>, baseline: Record<string, number>, gain: number, settings = defaultExpressions()): FaceValues {
  const result = neutralFace();
  for (const key of settings.preset === "basic" ? FACE_CHANNELS : EXPRESSION_CHANNELS) {
    const base = unit(baseline[key] ?? 0);
    const response = settings.channels[key] ?? defaultResponse();
    const adjusted = Math.max(0, (unit(values[key] ?? 0) - base) / Math.max(.15, 1 - base));
    result[key] = Math.min(response.max, unit(Math.max(0, adjusted - response.deadzone) / (1 - response.deadzone) * gain * response.gain));
  }
  // Opposing eye controls must not pull a closed lid open at the same time.
  if (settings.preset === "extended") {
    for (const side of ["Left", "Right"] as const) result[`eyeWide${side}`] *= 1 - result[`eyeBlink${side}`];
    result.mouthClose = Math.min(result.mouthClose, result.jawOpen);
  }
  return result;
}

export function meanBaseline(frames: FaceFrame[]): Record<string, number> {
  const valid = frames.filter((frame) => frame.detected);
  if (valid.length < 15) throw new Error("얼굴을 정면으로 유지한 뒤 다시 보정해 주세요.");
  return Object.fromEntries(EXPRESSION_CHANNELS.map((key) => [key, valid.reduce((sum, frame) => sum + unit(frame.values[key] ?? 0), 0) / valid.length]));
}

export function smoothFace(current: FaceValues, next: FaceValues, elapsed: number, seconds: number): FaceValues {
  const alpha = 1 - Math.exp(-Math.max(0, Math.min(elapsed, .1)) / Math.max(.02, seconds));
  return Object.fromEntries(EXPRESSION_CHANNELS.map((key) => [key, unit(current[key]) + (unit(next[key]) - unit(current[key])) * alpha])) as FaceValues;
}

/** Smooth ellipsoid support, zero outside its boundary. */
export function influence(x: number, y: number, z: number): number {
  const r = x * x + y * y + z * z;
  if (r >= 1) return 0;
  return (1 - r) ** 2;
}
