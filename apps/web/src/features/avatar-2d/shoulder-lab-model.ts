import { REST, clamp, neutralPose, rotate, add, sub, type Anchors, type Pose } from "./rig";

export const LEFT_SHOULDER_RANGE = { min: 0, max: 160 } as const;
export function restShoulderElevation(rest: Anchors = REST) {
  const v = sub(rest.leftElbow, rest.leftShoulder);
  return Math.atan2(v[0], v[1]) * 180 / Math.PI;
}

/** One degree of freedom only: the avatar's anatomical left shoulder abducts
 * in the image plane, with a coupled shoulder-girdle lift. Elbow/wrist local
 * angles and all non-target joints stay fixed. This is an authored 2D rig rule,
 * not a biomechanical reconstruction. */
export function manualLeftShoulderPose(elevation: number, rest: Anchors = REST): Pose {
  const pose = neutralPose(rest);
  const degrees = Number.isFinite(elevation) ? clamp(elevation, LEFT_SHOULDER_RANGE.min, LEFT_SHOULDER_RANGE.max) : restShoulderElevation(rest);
  const delta = (restShoulderElevation(rest) - degrees) * Math.PI / 180;
  const lift = clamp((degrees - 30) / 130, 0, 1);
  const eased = lift * lift * (3 - 2 * lift);
  pose.joints.leftShoulder = add(rest.leftShoulder, [-9 * eased, -32 * eased]);
  for (const joint of ["leftElbow", "leftWrist"] as const) pose.joints[joint] = add(pose.joints.leftShoulder, rotate(sub(rest[joint], rest.leftShoulder), delta));
  return pose;
}

export function sweepElevation(elapsedSeconds: number, initialAngle = 0) {
  // Six seconds up and six seconds down; zero velocity at both ends.
  const phase = Math.acos(1 - 2 * clamp(initialAngle / LEFT_SHOULDER_RANGE.max, 0, 1));
  return LEFT_SHOULDER_RANGE.max * (1 - Math.cos(phase + elapsedSeconds / 12 * Math.PI * 2)) / 2;
}

export interface ShoulderObservation { id: string; angle: number; note: string; createdAt: string }
export interface ShoulderReview { schema_version: "avatar.shoulder_review.v1"; asset: "cat-2d-v1"; side: "left"; observations: ShoulderObservation[] }
export const emptyReview = (): ShoulderReview => ({ schema_version: "avatar.shoulder_review.v1", asset: "cat-2d-v1", side: "left", observations: [] });
export function parseShoulderReview(value: unknown): ShoulderReview {
  const v = value as ShoulderReview;
  if (!v || v.schema_version !== "avatar.shoulder_review.v1" || v.asset !== "cat-2d-v1" || v.side !== "left" || !Array.isArray(v.observations) || v.observations.length > 100) throw new Error("이 실험의 기록이 아닙니다.");
  for (const item of v.observations) {
    if (!item || typeof item.id !== "string" || item.id.length > 100 || !Number.isFinite(item.angle) || item.angle < 0 || item.angle > 160 || typeof item.note !== "string" || item.note.length > 1000 || typeof item.createdAt !== "string") throw new Error("각도 기록이 올바르지 않습니다.");
  }
  return { schema_version: v.schema_version, asset: v.asset, side: v.side, observations: v.observations.map((item) => ({ id: item.id, angle: item.angle, note: item.note, createdAt: item.createdAt })) };
}
