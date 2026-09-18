# Illustrated 2D Avatar

`/live-avatar/2d` is a local authoring and performance surface. It is not a Workflow
Node and does not modify Canvas definitions, published versions, historical runs,
the existing GLB avatar, or its artifacts.

## Use

Open **Live Avatar → 2D 캐릭터 스튜디오**. The bundled prop-free character starts
performing the motion extracted from the supplied reference video. The reference
thumbnail and playback scrubber share a timeline. Pause or select a pose to inspect
the result, or choose **준비 자세** for the neutral illustration.

- **웹캠으로 움직이기** requests video-only camera access on click. Face, body and
  hands are detected locally with the existing Holistic worker. This renderer maps
  the body and basic face controls; individual finger articulation is not authored.
- **동작 영상 불러오기** uses a local file through the same tracking path.
- **영상에서 실시간 추적** exercises that path with the existing reference artifact.
- **관절 수정** stops capture, opens the neutral pose, and allows joint dragging.
  The coordinates refer to the character's anatomical left and right.
- **리그 저장** persists the validated profile in localStorage. JSON import/export
  uses `avatar.puppet2d.v1` and rejects other asset identities and invalid anchors.
- Lighting direction, intensity, shading strength and background can be changed.
- **아바타 영상 녹화** records the rendered avatar canvas at a requested 30 FPS.
  Stop to download WebM or MP4 according to browser support. The original camera
  image, rig overlay and audio are not recorded.

Navigation, page hiding, stop and error paths stop capture. A pending camera grant
after cancellation is released rather than becoming an orphaned camera stream.
Whole-body tracking runs in a worker, with a single frame in flight and a 20 FPS
input cap. The face-only path uses Face Landmarker with a 24 FPS cap.
Missing or low-confidence body tracking returns the avatar to neutral after 700 ms.

## Representation

The illustration is divided into six deformable surfaces: each arm, each leg,
torso and the original head/hair. Head extraction partitions the original pixels
into head and body ownership; it does not synthesize hair or discard neck/shoulder
skin. Their alpha coverage is conserved. The original face, hair volume, ears and
skin/clothing colors come directly from the base illustration.

Hidden torso completion is restricted to pixels that were covered by the original
hair. It cannot expand the neutral silhouette or overwrite visible original skin.
There are no independent shoulder/neck skin discs. Upper arms and torso share the
same shoulder pivots; neck pixels blend from the jaw transform to the torso. Limb
weights cannot cross into another limb, and smoothing preserves target bone lengths.

Explicit painter ordering handles overlap without transparent edges writing depth.
Basic face controls provide blinking and mouth opening. The reference performance
contains 854 samples at 24 FPS, with body detections in every frame.

## Expression library

The gallery is now **표정 제작 자료** for the [webcam face rig](face-rig2d.md).
The default runtime uses landmark-driven facial deformation, neutral/max
calibration and per-channel bindings. Static image review remains explicitly
available in **제작 자료 보기**; it is not the webcam retargeting mechanism.

The **표정 제작 자료** includes image expressions derived from the original
illustration: smile, laugh, surprise, sadness, anger, wink and isolated mouth
opening. The original face
remains a separate immutable choice. No GLB or facial reconstruction is used.

- In **제작 자료 보기**, select a thumbnail while body motion continues. In
  **웹캠 구동**, these images serve the face rig and clicking a thumbnail does
  not override live deformation. **얼굴 확대** provides a closer view.
- The renderer samples only a feathered facial color region from each image.
  Original head alpha, hair outside that region, body artwork and rig profiles
  remain unchanged. Expression images do not replace the entire head or body.
- Static reference review fixes the depicted eye/mouth pose. Choose **원본**
  while in reference-review mode to use the old procedural controls. Static
  review uses a short crossfade. The default webcam mode uses the separate
  landmark-warped face rig described in `face-rig2d.md`.
- Add PNG/JPEG/WebP images (up to 5MB, 64–2048px per side), name, duplicate, delete
  or replace them. Full-body images and face closeups have distinct placement
  defaults, with horizontal/vertical/scale adjustments under expression editing.
- **모음 저장** stores the library and custom image data in IndexedDB, separately
  from the body rig's localStorage profile. Up to 24 entries including original
  and 32MB of image strings are accepted. Nothing is uploaded to a provider.
- **모음 내보내기** embeds expression images in a portable JSON bundle; importing
  validates its asset and source-art SHA-256 before replacing the in-memory
  library. Save after importing to persist it. The bundled original remains
  referenced by its immutable asset identity. Restore defaults is also an
  in-memory edit until saved.

The document contract is `avatar.expression_library.v1`. Bundled PNGs, generation
provenance and exact built-in image-generation prompts live under
`public/avatars/cat-2d-v1/expressions-v1/`. This is an authoring/session feature,
not a Workflow Node. Existing `avatar.puppet2d.v1` profiles and Canvas/Workflow
contracts are unchanged. New generated source images are retained separately;
`base.png` is not overwritten.

Run `npm run test:avatar-expressions --workspace apps/web` for library validation,
asset dimensions/hash binding, original preservation and face-mask bounds. The
existing 854-frame body/attachment tests remain applicable. Browser QA also
covers image import, naming, duplicate/delete, IndexedDB reload, portable export
and import, expression switching during motion, and neutral/expression render
comparison outside the face.

The shader derives approximate surface normals from the authored body/limb templates
and uses a toon ramp for lighting. Simple posed occluders approximate head/arm shadows;
a soft floor shadow follows the feet. This remains a 2.5D approximation with original
painted shading, not physically accurate relighting.

## Supported range and asset preparation

This version targets the reference's front-facing gestures, side steps and moderate
head/body turns. It is not a complete Live2D/Cubism model. Large profile/back turns,
complex foreshortening, hidden anatomy and articulated fingers require additional
authored views/parts and pose corrections. The component masks are specific to the
bundled neutral illustration; arbitrary PNG upload is intentionally not presented
as automatic high-quality rig generation.

The source illustration is the previously generated prop-free A-pose at
`public/avatars/cat-2d-v1/base.png`. Keep this asset version immutable: masks and saved
anchor profiles depend on its pixel layout. A different illustration requires a new
asset identity and newly reviewed part masks. The exported JSON contains authoring
anchors, not the entire portable texture/mask/model bundle.

## Validation

`npm run test:avatar-2d --workspace apps/web` checks all reference frames, target limb
length preservation before/after smoothing, missing tracking, neutral head rotation,
isolated limb chains, and malformed profile rejection. Typecheck, lint and the
repository UI architecture check apply as usual. Browser verification covers the
reference playback, named poses, local video tracking, rig editing, lighting and
canvas recording. Physical webcam quality requires a real camera and suitable
full-body framing; it is separate from local-video tracking verification.

Face and Holistic models are served locally by `prepare-live-avatar.mjs`. The
Holistic download URL includes `latest`, but its exact SHA-256 is pinned; an upstream
replacement is rejected rather than silently changing the model.

## Attachment and silhouette regression checks

Tests assert original-pixel ownership and alpha conservation, the absence of
independent skin geometry, shared shoulder pivots, and neck-to-jaw/torso attachment
for all reference frames. Browser visual checks include the reported crossed-arm
pose at 21.8 seconds, raised arms at 6.2 seconds, and neutral silhouette comparison.

`head-isolated-v2.png` is an earlier preparation artifact and is no longer consumed
by the renderer. `body-underpaint-v2.png` supplies hidden torso pixels only. The
original base and the saved authoring coordinate system remain unchanged.
