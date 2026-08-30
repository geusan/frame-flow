export interface MotionPreviewLandmark {
  x: number;
  y: number;
  z: number;
  visibility?: number;
  presence?: number;
}

export interface MotionPreviewFrame {
  timestampMs: number;
  face: MotionPreviewLandmark[];
  pose: MotionPreviewLandmark[];
  leftHand: MotionPreviewLandmark[];
  rightHand: MotionPreviewLandmark[];
  blendshapes: Record<string, number>;
}

export const FINGER_DEFINITIONS = [
  { key: "thumb", label: "엄지", color: "#f7ca5d", landmarks: [1, 2, 3, 4] },
  { key: "index", label: "검지", color: "#ff86a8", landmarks: [5, 6, 7, 8] },
  { key: "middle", label: "중지", color: "#6fdff4", landmarks: [9, 10, 11, 12] },
  { key: "ring", label: "약지", color: "#b99cff", landmarks: [13, 14, 15, 16] },
  { key: "pinky", label: "소지", color: "#9de46f", landmarks: [17, 18, 19, 20] },
] as const;

export type FingerKey = (typeof FINGER_DEFINITIONS)[number]["key"];
export type HandSide = "left" | "right";

export interface FingerMotionValue {
  curl: number;
  speed: number;
}

export interface HandFingerMotion {
  detected: boolean;
  fingers: Record<FingerKey, FingerMotionValue>;
}

export interface FingerMotionFrame {
  left: HandFingerMotion;
  right: HandFingerMotion;
}

const EMPTY_FINGERS: Record<FingerKey, FingerMotionValue> = {
  thumb: { curl: 0, speed: 0 },
  index: { curl: 0, speed: 0 },
  middle: { curl: 0, speed: 0 },
  ring: { curl: 0, speed: 0 },
  pinky: { curl: 0, speed: 0 },
};

const clamp = (value: number, minimum: number, maximum: number) => Math.min(maximum, Math.max(minimum, value));

const distance = (start: MotionPreviewLandmark, end: MotionPreviewLandmark) => Math.hypot(
  start.x - end.x,
  start.y - end.y,
  start.z - end.z,
);

const jointAngle = (start: MotionPreviewLandmark, joint: MotionPreviewLandmark, end: MotionPreviewLandmark) => {
  const first = [start.x - joint.x, start.y - joint.y, start.z - joint.z];
  const second = [end.x - joint.x, end.y - joint.y, end.z - joint.z];
  const firstLength = Math.hypot(first[0], first[1], first[2]);
  const secondLength = Math.hypot(second[0], second[1], second[2]);
  if (firstLength < 1e-6 || secondLength < 1e-6) return Math.PI;
  const cosine = first.reduce((sum, value, index) => sum + value * second[index], 0) / (firstLength * secondLength);
  return Math.acos(clamp(cosine, -1, 1));
};

const relativeTip = (landmarks: MotionPreviewLandmark[], tipIndex: number) => {
  const wrist = landmarks[0];
  const tip = landmarks[tipIndex];
  const palmScale = Math.max(distance(wrist, landmarks[9]), 1e-5);
  return {
    x: (tip.x - wrist.x) / palmScale,
    y: (tip.y - wrist.y) / palmScale,
    z: (tip.z - wrist.z) / palmScale,
  };
};

const measureHand = (
  landmarks: MotionPreviewLandmark[],
  previousLandmarks: MotionPreviewLandmark[] | undefined,
  elapsedMs: number,
): HandFingerMotion => {
  if (landmarks.length !== 21) return { detected: false, fingers: { ...EMPTY_FINGERS } };
  const canMeasureSpeed = previousLandmarks?.length === 21 && elapsedMs > 0 && elapsedMs <= 1000;
  const elapsedSeconds = elapsedMs / 1000;
  const fingers = Object.fromEntries(FINGER_DEFINITIONS.map((finger) => {
    const [baseIndex, firstJointIndex, secondJointIndex, tipIndex] = finger.landmarks;
    const firstAngle = jointAngle(landmarks[baseIndex], landmarks[firstJointIndex], landmarks[secondJointIndex]);
    const secondAngle = jointAngle(landmarks[firstJointIndex], landmarks[secondJointIndex], landmarks[tipIndex]);
    const curl = clamp(1 - (firstAngle + secondAngle) / (2 * Math.PI), 0, 1);
    let speed = 0;
    if (canMeasureSpeed && previousLandmarks) {
      const currentTip = relativeTip(landmarks, tipIndex);
      const previousTip = relativeTip(previousLandmarks, tipIndex);
      speed = Math.hypot(
        currentTip.x - previousTip.x,
        currentTip.y - previousTip.y,
        currentTip.z - previousTip.z,
      ) / elapsedSeconds;
    }
    return [finger.key, { curl, speed }];
  })) as Record<FingerKey, FingerMotionValue>;
  return { detected: true, fingers };
};

export const measureFingerMotion = (
  frame: MotionPreviewFrame,
  previousFrame?: MotionPreviewFrame | null,
): FingerMotionFrame => {
  const elapsedMs = previousFrame ? frame.timestampMs - previousFrame.timestampMs : 0;
  return {
    left: measureHand(frame.leftHand, previousFrame?.leftHand, elapsedMs),
    right: measureHand(frame.rightHand, previousFrame?.rightHand, elapsedMs),
  };
};

export type HolisticWorkerMessage =
  | { type: "ready"; delegate: "GPU" | "CPU" }
  | { type: "frame"; frame: MotionPreviewFrame }
  | { type: "error"; message: string };
