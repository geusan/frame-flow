# Single-source 3D character turnaround

`character.turnaround.generate@1` is a Workflow execution Node, separate from
`character.generate` (varied poses for character/LoRA authoring) and
`character.reference.multiview@1` (selection of existing Character bundle views).

```text
Image source → 3D Turnaround · 4 Views → Image to 3D · Tripo @3
```

The new Node calls Tripo API v3 `POST /generation/image-to-multiview` with one
uploaded reference. It returns exactly four images in front/left/back/right order.
Tripo controls the multiview model and exposes neither a pose nor a seed/model
selector on this endpoint. The reference determines the intended pose: use one
full-body character with a clean background, preferably in an A-pose or T-pose
for rigging. A collage or inconsistent character sheet is not a reference image.
Review the generated views for identity, pose, accessories and orientation before
running 3D generation; file validation is not a semantic pose guarantee.

## Contract and storage

- Input: one `media.image.v1` Artifact.
- Output: `artifact.character_turnaround.v1` / `CharacterTurnaround`, with
  `character.turnaround.v1` schema, source Image ID, `preserve_source` pose policy
  and four role-keyed immutable Image Artifacts.
- Each Image uses `character.view.v1`; PNG/JPEG/WebP are decoded to lossless PNG.
  Invalid, undersized, missing or duplicated images cannot produce a usable set.
- Artifact lineage records the original Image and all four output images.
- Manifest defaults are materialized; minimum resolution may be exposed as a
  Workflow input. The source image can be exposed through the existing Asset input.
- The ordinary Registry Library and Generic Inspector provide discovery/editing.
  A shared image gallery previews all views without Node-key UI dispatch.
- Local and Temporal call the same registered Executor. Provider task IDs are
  checkpointed before polling; retry resumes known tasks. Ambiguous submissions
  remain blocked to prevent duplicate billing. Tripo tasks use one automatic attempt.
- Cache identity uses the common config/input/definition/runtime fingerprint.
  The Run model ID explicitly says `provider-managed:image-to-multiview` because
  Tripo does not provide an immutable model version selector. Artifacts also record
  any returned model, API revision, task ID and actual `credits_consumed`.
  Credits are kept in their original unit; no USD conversion is fabricated.
- Workflow Publish includes the Node only when it reaches a declared output.

## Explicit Draft replacement

`character.image_to_3d@3` adds the turnaround input contract. Its geometry, texture
and GLB output settings are the same as @2; @1 and @2 Definitions/digests/execution
remain available. There is no implicit compatibility between a Character bundle
ReferenceSet and a single-source Turnaround.

Manual replacement is required because old images cannot be safely reclassified
as same-pose views. In the Draft, replace the Character selector with an Image
selector, replace `character.reference.multiview@1` with
`character.turnaround.generate@1`, and replace the 3D input edge/node with @3.
Copy the old 3D config verbatim and clear obsolete runtime results for the changed
branch and its dependents. Review this diff:

| Before | After |
| --- | --- |
| Character bundle input | Single Image input |
| Existing view selection, no generation | New four-view image generation; Tripo credits apply |
| `character_reference_set` / `artifact.character_reference_set.v1` | `turnaround` / `artifact.character_turnaround.v1` |
| `character.image_to_3d@2` | `character.image_to_3d@3` |

Keep old Artifact and Run records. Published Versions are never modified; publish
a new Version to use the new branch in a managed Workflow.

Official API references:
- https://developers.tripo3d.ai/en/docs/generation-image-to-multiview
- https://developers.tripo3d.ai/en/docs/generation-multiview-to-model/p
