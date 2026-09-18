# Left eye image-layer prototype

Open `/live-avatar/2d/face`, expand **왼쪽 눈 이미지 레이어 실험**. Anatomical left is viewer right. Three original transparent PNG sprites were generated with the built-in image_gen tool using the existing cat avatar as reference, saved without modifying their pixels under `apps/web/public/avatars/cat-2d-v1/left-eye-v1/`. Full prompts are in `prompts.json`.

The UI normalizes the measured visible bounds using SVG viewBoxes. The iris moves independently at constant size. A luminance mask from the sclera excludes black lashes, narrows the visible aperture during a blink, and hides the iris at full closure. The closed-lid sprite fades in near full closure. Manual controls exercise horizontal/vertical gaze, partial/full blink, and iris size; webcam mode reads the same calibrated left-eye channels as the existing avatar. No extra camera session is created.

This is an authoring experiment, not a replacement of the avatar's full-face eye. The existing face renderer is unchanged. Generated artwork differs in detail from the source and needs approval/alignment before integration. Intermediate eyelid deformation currently scales the sclera/lash plate vertically; a separate upper/lower lid mesh and a reconstructed skin backing are still needed for production-quality eyelids. Nothing is represented as a completed fully separated production eye rig.

Assets: sclera.png (white + outline), iris.png (iris/pupil/highlights), closed-lid.png (closed upper lash line). Genuine alpha verified. Low-alpha stray pixels exist in generated padding; viewBox crops use alpha > 20 visible bounds while preserving originals.

## Spherical rotation and independent pupil (v2)

The eye now uses orthographic projection of an iris plane attached to a spherical globe. Yaw/pitch rotate the iris center on a spherical orbit and project its local axes; diagonal gaze includes shear/foreshortening. Gaze does not resize the authored iris. A separate dark pupil ellipse shares the same transform; its diameter is controlled independently as a fraction of iris diameter, including during webcam input. Corneal highlights are separate from the rotating texture. This is a stylized geometric approximation, not refractive cornea/lens rendering. Pupil size is manual, not inferred from MediaPipe or light exposure.

The built-in image generator produced pupil/highlight-free `iris-surface-v2.png`. Its padding contains a painted checkerboard (RGB); the runtime samples only an interior ellipse, so it is intentionally treated as an opaque texture, not a transparent sprite. The old transparent iris sprite remains downloadable as the previous source asset. Prompt provenance is in `iris-surface-v2.prompt.json`.

Validation: `node --experimental-strip-types apps/web/scripts/test-eye-projection.mjs` checks spherical distance, mirrored yaw, projected-area reduction and diagonal gaze. Browser checks compare pupil radius changes without iris-transform changes, pupil projection during gaze, and full-blink occlusion.

## Body integration

The face renderer now enables the generated left eye by default. A local skin-colored backing removes the original eye; the transparent layered-eye canvas replaces only the anatomical left eye. The existing left-eye mesh/gaze deformation is disabled to avoid double transformation. Both eye renderers use `projectEye`; the body consumes calibrated face channels and supports independent pupil/iris appearance. **본체 왼쪽 눈 · 구면 리그** allows disabling it for A/B comparison. **얼굴 리그 저장** persists appearance separately under `frameflow.left-eye-appearance.v1`; the older exported face-rig package does not include these new appearance settings. Debug iris and eyelid points follow the new renderer. The backing is a sampled skin approximation; hair/eyelid-edge alignment and matching the right eye remain art refinements.

## Binocular spherical surface

Both body eyes now use the same generated asset set (mirrored for the right eye) and shared world-horizontal gaze, computed from the signed in/out signals of both eyes. Blinks remain independent. Each iris texture vertex is mapped to a sphere with `x=R sin(u/R)`, `y=R sin(v/R)`, `z=sqrt(R²-x²-y²)`, then rotated about a fixed globe center and projected. A 5-ring, 32-sector triangle mesh warps the texture; pupil contours use the same spherical projection. Body and authoring preview share the canvas renderer. This replaces the earlier affine plane projection and unilateral eye replacement. It is stylized spherical rendering, not measured convergence or a refractive anatomical eye model. Artwork consistency improves by using the same assets in both eyes; sampled skin backing and face artwork matching remain limitations.

Neutral gaze is centered at (448,317) in the shared 1000×600 eye coordinate frame, aligned to the visible sclera rather than the full sprite including its outer lash wing. Both eyes mirror this same rest position; zero gaze and tracking stop return to it.

Finite fixation now supersedes the shared-angle assumption. A configurable virtual target distance (20–200 cm, default 60) and a stylized 6.4 cm eye separation define one point in head coordinates. Each eye computes yaw=atan2(targetX-eyeX,targetZ) and pitch=atan2(targetY,hypot(targetX-eyeX,targetZ)). Exact angles feed the spherical renderer without re-normalizing gaze sliders. This gives symmetric inward vergence at rest and target convergence off-axis. The distance is authored, not webcam-measured; old appearance preferences receive 60 cm when absent. Save it with face rig settings.

## Character-space layout

Body eye placement now derives from neutral `left/rightIris`, eye corner/lid landmarks and cheek width. Eye spacing defaults to 94% of the authored iris separation and is adjustable from 80–115%. Both sprite origins, dimensions, debug points and fixation origins use this same layout. Target distance is measured in face widths (stored slider value divided by ten, default six face widths), replacing the invented physical-centimeter interpretation. Existing saved distance numbers remain as visual tuning values; missing spacing defaults to 0.94. No anatomical human eye separation is used in the body renderer. The old `fixationTarget` helper is retained solely for the earlier projection fixture.

Validation: `node apps/web/scripts/test-eye-layout.mjs` verifies alignment between sprite and optical center, spacing-dependent vergence, scale-invariant fixation and common ray intersection.
