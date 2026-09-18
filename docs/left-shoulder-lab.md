# Left shoulder study — connected surface

> 최신 상태(2026-09-09): 사용자 시각 평가 실패. 연결성 검사 통과는 자연스러움 검증이 아니다. [실험 노트와 다음 연구 계획](avatar-rig-research/references/experiments.md)을 우선 참고한다.

Route: `/live-avatar/2d/shoulder`. This is a browser authoring experiment, not a
Workflow Node. The main tracker and saved rig profiles are unchanged.

## Scope and cause

Anatomical left is screen right. Input is a single image-plane elevation angle:
0° down, 90° horizontal, 160° upper limit; original art is approximately 19.6°.
The earlier renderer rotated independent arm and torso cutouts around a fixed
shoulder. Their separate boundaries exposed a flat arm root and gaps at elevation.
Adding joint points alone cannot weld those surfaces.

## Connection correction

- Only this lab enables `PuppetScene.connectedLeftShoulder` before loading.
- The skin under the body and left arm uses one exterior contour and shared
  triangle mesh. The old internal cut is removed. Head art is unchanged.
- The tank top is a separate original-art surface. Its neckline, chest and hem
  follow the stationary torso; only the outer strap/armhole follows a maximum
  8-pixel shoulder lift and 1.8-pixel medial shift. Runtime torso underpaint covers
  the region exposed between the elevated armpit and the stationary garment.
  Garment shading retains its original UVs and does not inherit arm rotation.
- Shoulder elevation couples to a bounded lift (up to 32 artwork pixels) and
  9-pixel medial shift. This is an authored 2D rule, not anatomical reconstruction.
- A corrective armpit attachment approaches the shoulder with increasing angle.
  It avoids sweeping the shirt around the full upper-arm lever.
- Cotangent ARAP distributes deformation through the left upper torso. Exact
  concave boundary triangulation, conforming refinement and interior edge flips
  avoid accidental connections across the exterior armpit gap.
- Positive signed-area projection prevents triangle foldovers. Geometry samples
  at 2° intervals are computed during loading and shared by both views. Runtime
  interpolation also checks foldovers; the distal arm uses exact rigid motion.
- Elbow/wrist relative angle and bone lengths stay fixed. Right arm, head and
  lower-body joints stay fixed. The left upper torso artwork intentionally moves.
- Camera, MediaPipe, dynamic lighting, floor shadow and hair sway remain off.

ARAP background: Sorkine and Alexa, SGP 2007,
https://igl.ethz.ch/projects/ARAP/ . The area constraint and armpit rule are local
implementation additions; ARAP itself does not guarantee no foldovers.

## Review and limits

Use presets, slider or number input; slow sweep takes 12 seconds per cycle. The
fixed close-up offers art, flat and mesh inspection. Notes remain browser-local
`avatar.shoulder_review.v1` data; older notes describe the earlier renderer.

This step establishes a connected left shoulder for manual side elevation. It
is not a full-body or out-of-plane rig. The newly exposed skin uses procedural underpaint; its shading still needs
visual review before expanding to other major joints. Garment preservation is
checked independently from skin connectivity.
Do not advance to fingers or other fine joints before that major-joint review.

## Validation

`npm run test:shoulder-lab --workspace apps/web` uses the actual model, mesh and
solver across 641 quarter-degree inputs. It asserts a single connected topology,
positive triangle areas, neutral artwork preservation, bounded edge stretch and
vertex steps, fixed bone lengths/elbow angle, non-target joint isolation, input
validation, sweep continuity and observation serialization. Geometric thresholds
are regression guards, not an automatic visual-quality score.

`npm run test:avatar-2d --workspace apps/web` retains the main renderer's 854-frame
reference-motion and artwork-ownership checks. Inspect 0°, baseline, 45°, 90°,
135° and 160° in the browser as well as the numerical checks.
