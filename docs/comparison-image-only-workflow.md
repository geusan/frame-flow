# Image-and-prompt comparison drafts

2026-10-02. User-directed correction: compare Veo, H3 and Omni using one shared
character scene image and the same motion specification. Do not supply source
video or target speech to any video generator. Retain provider-specific clip
lengths and apply the same Tsuki speech through separate lip-sync/mux nodes.

## Draft graph changes

- Veo: `video.animate_image@1`, three 8-second requests. Retain 6.500, 7.041667,
  and 5.333333 seconds, cut at utterance pauses.
- H3: `video.reference_generate@2`, 11/9-second requests; its optional video and
  audio ports are disconnected. Exactly one image is connected, matching Veo.
  Remove the two driving-video segment nodes and the extra identity image source.
- Omni: replace `video.performance_transfer@2` with `video.animate_image@2`.
  Request 10/9 seconds and retain 9.875/9 seconds. Remove driving-video segments
  and add two explicit motion-prompt source nodes.
- Original video remains connected only to the caption analysis branch. It has
  no path to any generation input. Target speech connects only to audio segments,
  lip-sync and final mux. Caption layout and the final 18.875-second clock remain.
- All generators receive the same immutable scene image. One shared invariant
  paragraph and six global speech/gesture events produce the per-clip prompts.
  Only requested duration and clip-relative timestamps vary between providers.
- Generator node IDs change, and their downstream runtime previews are cleared.
  Previously generated artifacts, costs and Run snapshots remain immutable.
  Existing completed audio segments remain valid where their config is unchanged.

The applied Draft migration and before/after JSON are recorded under
`output/comparison-input-parity/`. No provider generation is submitted during
this change. These are new input conditions; previous video-driven results must
not be presented as results of the image-only comparison.

## Omni image-animation contract

`video.animate_image@2` is an immutable, generic-inspector contract with exactly
one Image and one Prompt input, and one Video output. Video/audio inputs are
rejected before provider submission. Native local and Temporal engines both use
`OmniAnimationExecutor` from the shared registry.

Config defaults: 1080p, 9:16, 8 seconds, 1800-second timeout. Duration is an integer
from 3–10. Resolution, ratio and duration are the only workflow-exposable fields.
The exact model is `gemini-omni-1.1-flash-preview` through the existing Vertex
service account. The request declares `<FIRST_FRAME>@Image1` and
`task=image_to_video`; the original edit capability continues to use `task=edit`.

The Interactions documentation does not specify a structured duration field.
Duration is supplied explicitly in the prompt, then actual output is checked
against -250ms/+1000ms tolerance. The raw provider video is kept immutable;
precise cropping and bounded tail padding belong to downstream segment nodes.
An out-of-bounds output fails validation without automatically submitting a new
billable generation. Character identity and frame-zero fidelity still require
visual QA after generation.

Artifact contract: `video.image_animation.v2`, roles `first_frame` and
`motion_prompt`, native audio retained for downstream replacement. It snapshots
definition/executor/FFmpeg revisions, exact model, normalized config, requested
and measured duration, task and provider interaction ID. The same checkpoint,
resume, usage-before-download and unreported-cost rules as the existing Omni
adapter apply; no fixed dollar amount is invented.

## Compatibility and manual migration

Veo's `video.animate_image@1` and Omni's `video.performance_transfer@2` remain
unchanged and executable. No published WorkflowVersion or historical Artifact
is upgraded. To change another Draft manually:

| Source contract | Destination | Required review |
| --- | --- | --- |
| `video.performance_transfer@2` | `video.animate_image@2` | Remove video input; move config prompt to connected Prompt; add explicit duration and aspect ratio. Source timing is no longer an input. |
| `video.animate_image@1` | `video.animate_image@2` | Provider changes from Veo to Omni; remove `seed`/`output_count`; add timeout; duration range becomes 3–10 and duration control is prompted/validated. |

This is a Draft-only manual replacement, not an automatic upgrade. Review the
before/after diff and publish a new Version if a runnable frozen version is
needed.

## Validation

`test_omni_image_animation.py` verifies image-only normalized request, required
duration instruction, immutable old contracts, config defaults/validation,
registry/generic editor exposure, async resume/task billing context, local and
Temporal fixture/mocked-live parity, artifact lineage/cache, video/audio input
rejection, measured output-duration bounds, bindings, publish reachability and
request hashing. Existing Omni editing, Veo starting-frame, H3 and registry tests
remain in the regression selection. Actual paid visual quality is not assessed
by these tests.

Provider details were checked against the [Omni guide](https://ai.google.dev/gemini-api/docs/omni)
and [Vertex Interactions reference](https://docs.cloud.google.com/gemini-enterprise-agent-platform/reference/models/interactions-api).
