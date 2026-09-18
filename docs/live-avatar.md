# Live Avatar

Live Avatar is a browser-only authoring/session surface, not a Workflow execution
Node. It does not change Node contracts, published Versions, Runs or source GLBs.
Open **웹캠 연결** from a GLB preview, or choose a model under **Live Avatar**.

## Model preparation

- A GLB with existing morph targets can map the full ARKit-style expression
  vocabulary to its own targets. Choose the head bone separately. The v3 profile
  supports 44 facial channels and eight gaze channels, with per-channel gain,
  dead zone and maximum strength. MediaPipe does not output `tongueOut`; that
  target is available for manual testing only. The six-channel starter rig is
  unchanged.
- A body-only rig can use the **간이 얼굴 리그** authoring mode. Pick the character's
  left eye, right eye, and mouth center on the actual mesh. Six relative morph
  targets are generated in memory, limited to vertices weighted to the selected
  head bone and to the front surface around the selected points.
- This is an approximate deformation tool. It does not generate an oral cavity,
  teeth, separate eyeballs, or professionally modeled eyelids.
  Fine facial performance still requires facial modeling/rigging in Blender.
  An optional flat inner-mouth patch provides a basic opening cue; it is not
  anatomical mouth geometry. A manually checked preset is included for the
  current cat avatar, matched by its SHA-256 rather than its Canvas Node key.
- Test each slider, adjust the eye radius and depth, and save the profile locally.
  The versioned profile is bound to the immutable model SHA-256. Importing a
  profile for another model is rejected. Profiles can be exported as JSON.
- **표정 리그 GLB 내보내기** exports a new neutral GLB with the authored morph targets
  and original skin/bone names/textures/animation clips. It never overwrites the source Artifact.

## Capture

Camera access only starts on the explicit start action. MediaPipe Face Landmarker
runs in a Worker with one frame in flight, at up to 24 input FPS. Raw video and
face measurements stay in the browser. A local video file can exercise the same
tracking path without accessing the webcam.

Neutral calibration averages 24 detected frames. Head rotation uses a neutral
reference matrix; expression strengths are baseline-adjusted and clamped.
Exponential smoothing is time-based. Losing the face returns controls to neutral.
Stop, page navigation, hidden-tab changes, permission errors and late permission
resolution all release camera tracks, Worker, frame callbacks, and video URLs.
The live input and calibration are never written to Canvas or Run payloads.

## Gaze tracking

The v2 and v3 face profiles support optional directional gaze. The eight MediaPipe
`eyeLookIn/Out/Up/Down` scores are combined in character-left/up coordinates.
Closed eyes are excluded; one open eye can still drive the estimate. Missing
face/eye data returns gaze to neutral. This estimates direction, not a screen
pixel or a point of regard.

**시선 중심 보정** averages 24 valid frames while looking at the camera. The
existing neutral-face calibration also calibrates gaze when enough eye samples
are available. Calibration times out after eight seconds, and remains in memory
only. Sensitivity, a dead zone, time-based smoothing and axis inversion can be
saved with the model profile. Manual horizontal/vertical sliders test the output.

Three model adapters are available:
- **Surface**: localized base-color UV displacement inside the two eye regions.
  It preserves the original texture at neutral and fades during blinks. This is
  a simple Live Avatar effect for the existing body-only Tripo model; seams and
  source mesh quality limit its appearance. It does not create eye geometry.
- **Bones**: two separately selected eye bones rotate from their rest poses,
  following the head and respecting the configured angle limit.
- **Morphs**: the eight standard eye-look channels map to existing model targets.

`avatar.face_profile.v1` imports migrate with gaze disabled, preserving previous
behavior. V1/v2 profiles migrate to v3 in basic expression mode. The original JSON
is not modified; v3 saves use a separate local-storage key. New native rigs use
the extended expression mode, while old mappings and starter settings are kept.
A gaze-enabled preset is included for the original cat avatar.
Original GLBs and Workflow/Node contracts are unchanged.

GLB export retains native bones/morphs and records a portable v3 face profile.
The surface shader is applied only in Live Avatar, not in external GLB viewers.
Prepared exports import their embedded profile, normalize the front axis once,
and bind the profile to the newly imported artifact's hash. Exported JSON still
checks its exact source model hash.

## Detailed expressions

The expression editor groups eyes/brows, mouth/jaw and cheeks/nose. Each native
channel offers a target mapping and capture response controls. Unmapped targets
are explicitly disabled. Named presets (smile, laugh, surprise, sadness, frown,
pucker) test combinations without opening a camera. Missing tracking channels
remain neutral. Eye widening is suppressed during blinks, and mouth closure is
bounded by jaw opening. Shared mappings use the maximum contributing weight,
so the other side's zero cannot erase an expression or add past one.

The model-specific Blender authoring recipe and resulting cat-avatar rig are
documented in [live-avatar-face-authoring.md](live-avatar-face-authoring.md).
This adds real facial geometry as a separate Artifact; it is not a new Workflow
Node and does not regenerate the model through Tripo.

The pinned Face Landmarker v1 model and the installed MediaPipe WASM files are
served locally. `scripts/prepare-live-avatar.mjs` prepares them before dev/build;
the model download is checksum-verified. Generated vendor files are gitignored.

Validation: `npm run test:live-avatar --workspace apps/web`, typecheck, lint,
production build, and visual tests on the actual rigged avatar. Real webcam use
requires the user to grant camera access in their browser.
