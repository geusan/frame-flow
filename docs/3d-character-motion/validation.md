# 3D Character Motion — Validation Results

Date: 2026-09-04

## A. Blender availability

- `blender --version` on the development host initially failed because Blender was not installed.
- A checksum-verified Blender Foundation 4.5.13 LTS arm64 DMG was downloaded under ignored
  `.local/` and used only for the first host-side technical spike.
- `Blender -b --disable-autoexec --python-expr "print('hello')"` succeeded and printed `hello`.
- The production path now builds `frame-flow-blender-worker:local` from
  `apps/blender-worker/Dockerfile`. It contains Debian Blender 4.3.2, FFmpeg, fonts and the NumPy
  dependency required by Blender's glTF importer.
- The service passed its Docker health check and
  `blender -b --python-expr "import numpy" --disable-autoexec` inside the container. It exposes port
  8090 only to the Compose network, accepts bounded `/retarget` and `/render` requests, uses a fresh
  working directory per request, and never enables embedded file auto-execution.
- Compose API and Temporal workers use `BLENDER_EXECUTION_PROVIDER=http` and
  `BLENDER_SERVICE_URL=http://blender-worker:8090`; no host Blender path is required.

Reference: [Blender command-line manual](https://docs.blender.org/manual/en/latest/advanced/command_line/),
[Blender Python API](https://docs.blender.org/api/current/).

## B. GLB import/export round trip

The procedural fixture was exported to GLB, imported into a clean Blender process, and exported to
a second GLB. Results:

```json
{
  "mesh_count": 2,
  "material_count": 3,
  "image_count": 2,
  "armature_count": 1,
  "bone_count": 19,
  "animation_count": 0
}
```

Mesh, materials, embedded generated images, armature and all 19 bones survived. Animation count is
zero at this stage by design; animation was added in the retarget spike. The lightweight Python GLB
parser additionally checks the GLB v2 header/JSON chunk, meshes, POSITION accessors, bounds, skins,
materials, textures, external texture references and animation count. A future production hardening
step should also run the official [Khronos glTF Validator](https://github.com/KhronosGroup/glTF-Validator).
GLB remains the canonical interchange because glTF can carry scene nodes, meshes, materials,
textures, skins, and animations in one binary container ([Khronos glTF overview](https://www.khronos.org/gltf/)).

## C. Known-good rigged character

`create_fixture_character.py` creates a minimal skinned humanoid with 19 semantic bones and rigid
vertex groups. Blender discovered the hierarchy after GLB import, accepted quaternion keyframes,
saved `animation.blend`, exported `animated-character.glb`, and rendered the character. This is a
regression fixture, not a production-quality character or topology sample.

## D. Known motion source

`examples/3d-character-dance/known-motion.json` uses `humanoid.motion.v1`, nine samples over one
second, parent-space `xyzw` quaternions, root sway, body yaw, mirrored arm motion and mirrored leg
motion. Retargeting at 24fps produced 25 baked frames. The output contact sheet visibly changes arm
height, leg crossing/stance, body orientation and root position.

## E. MediaPipe quality on a real dance clip

The validation used an ignored local 4-second excerpt (2s–6s) of the rights-marked free-to-use
[Pexels full-body dance clip 6980766](https://www.pexels.com/video/a-woman-dancing-in-the-gym-6980766/).
The source is not committed.

Host execution of MediaPipe 1.0.1 terminated in native code because the macOS Metal graph service
was unavailable even with the CPU delegate selected. The same extraction succeeded in the existing
Linux worker image using XNNPACK CPU. This confirms MediaPipe extraction belongs in a controlled
worker, not the Web or development host process.

Measured at 640x338 and 8fps over 32 frames:

| Signal | Result |
| --- | --- |
| Pose coverage | 100% |
| Invalid canonical frames | 0% |
| Face coverage | 0% |
| Left/right hand coverage | 15.62% / 37.5% |
| Hip global rotation range | up to 34.7° |
| Spine rotation range | up to 45.7° |
| Left/right upper-arm range | up to 103.4° / 118.6° |
| Left/right upper-leg range | up to 71.5° / 70.8° |
| Root X/Y/Z range | 0.1005m / 0.2948m / 0.0006m |
| Detected left/right foot-contact frames | 3 / 1 |

The first result exposed an important issue: MediaPipe world landmarks are hip-centered, so they
cannot provide global root translation. The adapter now derives bone rotations from world landmarks
but derives root trajectory from the normalized image hip midpoint, scaled by observed body height.
This recovered lateral/vertical root movement, but monocular depth remains effectively absent.

Cleanup can reduce brief confidence gaps, quaternion sign flips, rotation jitter, root drift, and
some planted-foot sliding. It cannot reliably recover occluded/crossed limbs, fast motion missed at a
low sample rate, true depth, persistent left/right swaps, or feet hidden outside the frame. The test
did not show a persistent body-side swap, but hand coverage and foot contact were too weak for
production dance fidelity. A multi-view or temporal 3D mocap backend is recommended for
production-quality feet, spins, occlusion and floor contact. MediaPipe remains a useful MVP/body
preview provider. MediaPipe officially provides 33 pose landmarks, normalized and world-coordinate
outputs, and confidence thresholds ([Pose Landmarker guide](https://developers.google.com/edge/mediapipe/solutions/vision/pose_landmarker)).

## F. Retargeting end to end

Three real executions succeeded:

1. Procedural known-motion spike:
   `rigged GLB → Blender retarget → animated GLB/.blend → toon render` produced H.264, 360x640,
   25 frames, 1.041667 seconds, 20,336 bytes.
2. Real dance extraction through Frameflow nodes:
   `Pexels MP4 → Motion Video Input → MediaPipe → MotionRaw → Cleanup → Retarget → Blender Render`
   produced H.264, 360x640, 90 preview frames, 3.75 seconds, 64,728 bytes.
3. The supplied cat-character Canvas was rerun with the entire Compose stack. Temporal dispatched
   the Node runs, `blender-worker` returned HTTP 200 for both `/retarget` and `/render`, and CanvasRun
   `canvasrun_5893f99796b64025a6` completed at 100%. Artifact `art_0aa412b1b0b745949f` was probed as
   H.264, 360x640, 24fps, 90 frames, 3.75 seconds, 43,245 bytes. Four sampled frames visibly showed
   different torso, arm and leg poses. The geometry was still the procedural rig fixture because
   the V1 Image-to-3D and Auto Rig providers are manual/pass-through implementations.

The second path ran Motion Video Input and Motion Extraction in the Linux worker, then ran Cleanup,
Retarget and Render through the actual Node Registry, Experiment cache, object storage, Artifact
lineage and output contracts. It created seven Artifact lineage edges. Repeating the same Retarget
request returned the same animated GLB/.blend Artifact IDs with `cache_hit=true`.

Visual inspection of six output frames confirmed large overhead/side arm changes, wide and bent leg
poses, torso orientation changes and root displacement. This proves the execution pipeline; it does
not claim production mocap accuracy.

Ignored validation outputs:

```text
output/3d-character-motion-spike/
output/3d-character-motion-dance/
```

## G. Image-to-3D candidate

**Recommended MVP provider: Tripo API v3, using P1 first.** The supplied character already has
multiple consistent views, so the integration should call Multiview-to-Model rather than discarding
them and using only the front image. P1 is optimized for stylized/game assets, exposes a strict
50–20,000-face range, and prioritizes clean topology. This is a better first fit for deformation and
iteration than a very dense presentation mesh. Tripo's current API has one asynchronous task model
spanning multiview generation, GLB output, riggability check, humanoid auto-rigging, and
Mixamo-compatible bone naming.

Proposed request chain:

```text
front + left/profile + back + right/three-quarter
  -> POST /v3/generation/multiview-to-model (P1-20260311, face_limit=20000, textured GLB)
  -> POST /v3/animations/rig-check
  -> POST /v3/animations/rig
       model=v1.0-20240301, rig_type=biped, spec=mixamo, out_format=glb
  -> Frameflow GLB validation
  -> Blender retarget
```

The official multiview contract requires the front and at least one other view and recommends
view-key inputs. Rig Check accepts GLB up to 150 MB. Auto Rig recommends its biped v1.0 model for
humanoids and can emit GLB with Mixamo-compatible names. All calls are asynchronous and require an
API key. If P1 loses too much facial, hair, or costume identity, the controlled fallback is an A/B
run with H3.1 plus `smart_low_poly`, not a change to graph semantics. No supplied character image
was transmitted to Tripo during this validation.

References: [Tripo multiview generation](https://developers.tripo3d.ai/en/docs/generation-multiview-to-model),
[P1 model](https://developers.tripo3d.ai/en/models/p1),
[H3.1 model](https://developers.tripo3d.ai/en/models/v3-1),
[rig check](https://developers.tripo3d.ai/en/docs/animations-rig-check),
[auto rig](https://developers.tripo3d.ai/en/docs/animations-rig).

| Criterion | Finding |
| --- | --- |
| Character identity | Not measured with this LoRA character set; A/B P1 and H3.1 before locking the snapshot |
| Mesh quality | P1 targets clean low-poly topology; skin deformation still needs measurement on the generated result |
| Arms/legs separation, hands, hair | Image-dependent and not guaranteed; must be scored on an A-pose character test set |
| Texture consistency | PBR/textured GLB is available; anime face, hair and costume consistency still needs visual QA |
| A-pose compatibility | No contract guarantee found; pre-validation/correction remains required |
| Animation readiness | Rig Check and Auto Rig exist, but successful rigging does not guarantee good shoulder/hip deformation |
| Runtime | Remote asynchronous API; Frameflow should poll through the Temporal worker |
| Cost and latency | P1 multiview is documented as 40/50/60 credits by texture level and about 10s/60s without/with texture; not measured here |

Hunyuan3D-2.1 was also evaluated as a self-hosted candidate. Its official project provides separate
image-to-shape and PBR texture pipelines, but reports 10 GB VRAM for shape, 21 GB for texture, and
29 GB for both. It does not solve humanoid rigging. More importantly for this repository's South
Korean runtime, its Community License expressly excludes South Korea (as well as the EU and UK), so
it is not an acceptable default without separate licensing. It was not executed.

The provider is now implemented as `character.reference.multiview@1`,
`character.image_to_3d@2`, and `character.auto_rig@2`; the existing manual/pass-through `@1`
contracts remain compatible. MockTransport and Registry integration tests cover role-keyed uploads,
P1 request normalization, asynchronous polling, safe downloads, Rig Check, Mixamo output
validation, Artifact lineage, provider settings, cache inputs, and actionable failures. A live call
then validated the external contract and produced a textured Character3D GLB.

The live Tripo v3 run exposed two differences from the prose examples:

- Generation task IDs were UUIDs rather than `task_...` strings. The adapter now treats task IDs as
  opaque path-safe identifiers and persists them before polling.
- Signed GLB output was hosted under `*.data.tripo3d.com`, not the example `cdn.tripo3d.ai` host.
  The download allowlist accepts only Tripo's `.ai` and `.com` domain suffixes and never stores
  transient signed URLs in Artifact metadata.

The old validator caused Temporal's three configured attempts to submit three P1 jobs. All three
completed and were recovered as distinct immutable Character3D Artifacts; subsequent UUID recovery
used the newest task without another upload or generation request. Non-retryable provider/config
errors now stop after one activity attempt.

The recurrence guard has three layers: every Tripo Canvas Activity has exactly one Temporal attempt;
the billable POST writes a durable `pending` marker first; and a PostgreSQL advisory lock serializes
identical request hashes across concurrent workers. Poll/download failures after a known task ID can
be manually rerun and resume that same task, while an ambiguous POST response is never submitted
again automatically. A deliberately changed Config/input produces a new request hash and is treated
as a separate user-requested job.

## Known operational limitations

- Canceling a Frameflow run stops Tripo polling at the next progress update, but the provider's
  remote cancel endpoint is not integrated yet; an already submitted Tripo task may continue and
  consume credits. A lost response exactly during task submission cannot be reconciled
  automatically without provider-side idempotency; Frameflow keeps the durable pending claim,
  refuses to resubmit, and requires the returned task ID to be attached from Tripo Task History.
- Blender cancellation is checked as frame progress is reported and terminates the child process;
  MediaPipe extraction currently observes cancellation only at executor stage boundaries.
- The current general Temporal activity timeout is 30 minutes even though final-render Config can
  request a longer process timeout. Dedicated Blender activities must align these limits before long
  production renders.
- The Canvas now exposes secondary Manifest output handles. Explicit port selections route typed
  artifacts separately; older implicit first-output edges retain their historical result bundle.
- Preview rendering intentionally caps output at 90 frames. Final quality renders the full baked
  range.

## Reproduce

Known-motion Blender spike:

```bash
python scripts/validate_3d_character_motion.py \
  --blender-executable /path/to/Blender \
  --output output/3d-character-motion-spike
```

Run the actual downstream Frameflow nodes:

```bash
python scripts/validate_frameflow_3d_nodes.py \
  --blender-executable /path/to/Blender \
  --rigged-character output/3d-character-motion-spike/roundtrip-character.glb \
  --motion examples/3d-character-dance/known-motion.json \
  --output output/3d-character-motion-spike
```

The Linux MediaPipe validator and full Canvas example are documented in
`examples/3d-character-dance/README.md`.

Docker Compose execution:

```bash
docker compose build blender-worker
docker compose up -d
curl http://localhost:8000/health
```

Configure Tripo without placing the secret in a Canvas or WorkflowVersion:

1. Open Frameflow **Settings → Tripo**.
2. Enable the provider and save the raw API key without the `Bearer` prefix. The backend calls
   `/account/balance`; only a successful authentication is marked Ready or applied to workers. The
   UI never reads the secret back.
3. Connect `Character → Character Multiview Reference → Image to 3D · Tripo → 3D Asset
   Validation → Auto Rig · Tripo`.
4. Run P1 first with a 20,000 face limit. Inspect identity and deformation before rendering the full
   dance.
