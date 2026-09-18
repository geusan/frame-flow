# Cat avatar facial authoring

The original Tripo artifact `art_b46aa4f9f7a141b5b3` has a 23-bone body rig and no
native facial shapes. Its immutable SHA-256 is
`46e2f1035e6596156d0137bf21ae1fa5c550fee200651a4d41e855662a69a7ff`.

`scripts/author_avatar_face.py` is a model-specific Blender 4.3 authoring recipe.
It is **not a generic automatic face-rigging service** and deliberately rejects
another source hash. Faceit was not installed and was not used or purchased.
All authoring uses Blender's built-in geometry, shape-key, bone and glTF tools.

The recipe reconstructs the front face with constrained eyelid/lip loops, a
smooth skin surface, eyelid-edge ribbons and brows. It adds volumetric eyeballs,
amber irises, eye highlights, two head-parented eye bones, a mouth cavity, upper
and lower teeth, and a tongue. Forty-four named expression targets are shared by
the appropriate facial parts. Existing body bones and vertices outside the
facial region are retained; the source artifact is never overwritten.

This is a procedural facial-rig draft. Reconstructing the face changes its
appearance, including the cheek/jaw outline, skin shading and eye artwork.
Hair remains from the generated model and can hide eyebrow movement. Artistic
sculpting, texture polish and combination-specific corrective shapes may still
be needed for a finished performance avatar. Adding more tracked channels does
not make the underlying character anatomy or capture exact.

## Reproduce

Download the immutable source GLB to an authoring work directory, then run:

```sh
blender --background --factory-startup --disable-autoexec --python-exit-code 1 \
  --python scripts/author_avatar_face.py -- \
  --input /absolute/path/source.glb --output /absolute/path/result --render

python3 scripts/validate_avatar_face.py /absolute/path/source.glb \
  /absolute/path/result/cat-expressive.glb --report /absolute/path/result/glb-validation.json
```

The local outputs are under `output/live-avatar/expressive/`:

- `cat-expressive.blend`: editable meshes, shape keys, original armature and preview lighting.
- `cat-expressive.glb`: neutral, skinned model with portable v3 profile metadata.
- `face-profile.json`: profile bound to the output GLB's hash for explicit import.
- `authoring-report.json`, `glb-validation.json`: source, parts, shape displacement and preservation checks.
- Neutral, smile, laugh, blink, pucker, sadness and three-quarter PNG previews.

The saved derivative is `art_857a6d4b2c47498486`, with an explicit `source_avatar`
lineage edge to the original. It can be opened at
`/live-avatar/art_857a6d4b2c47498486`. It is a Model3D authoring Artifact, not a
NodeRun, and consumed no Tripo credits. Published graph contracts and previous
run snapshots remain unchanged.

## Validation

The GLB validator checks the container, finite vertex/morph data, neutral export,
all advertised target names, the embedded profile, original bones, geometry
outside the edited face (within a two-millionth model-unit export tolerance),
and independent eye-bone weights. Live Avatar tests cover v1/v2 migration,
extended capture calibration, missing channels, per-channel limits, shared
target mapping, multi-mesh application and return to neutral.

`tongueOut` can be authored and tested manually, but the current MediaPipe model
does not provide that score. The eight directional gaze channels drive the
independent eye bones through the existing calibrated gaze adapter.
