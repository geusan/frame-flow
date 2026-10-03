# Image description and action-preserving outfit workflow

`image.describe@1` is a Workflow execution Node, not a Canvas annotation. It is an
atomic image-to-description capability. It describes observed evidence; it neither
generates an image nor executes NOTTALGGAK. Existing `skill.execute@2` and
`image.generate@1` remain unchanged.

## Contract

- One required `image: media.image.v1`; optional `prompt: prompt.text.v1` for fixed
  downstream generation constraints.
- Output `prompt: prompt.text.v1`, stored as a UTF-8 `Text` Artifact with schema
  `prompt.image_description.v1` and output role `image_description`.
- Text begins with `Observed reference image:` and the model's observations.
  Supplied generation constraints are appended verbatim in a separate section.
  Those constraints are not represented as observed evidence.
- Native Registry executor `image-description`, revision `image-description.v1`;
  runtime revision includes `live` or `fixture`. Fixture mode requires `APP_ENV=test`
  and produces the same `NodeExecutionResult` and Artifact contract as live mode.
- Generic Inspector fields: `instructions`, `image_detail`, `max_output_tokens`.
  Only `instructions` is exposed as an optional workflow input. Defaults are
  materialized in saved Configs; model choices come from capability families.
- PNG/JPEG/WEBP and still GIF are supported. Invalid images, cardinality failures,
  empty/incomplete output and provider 4xx errors are non-retryable, except
  408/409/429. Connection failures and provider 5xx errors are retryable.
- Lineage roles: `described_image` and `generation_constraints`. Artifact metadata
  records normalized Config, Definition digest, executor revision, model alias,
  exact requested model ID, returned response model and token usage. Cost is
  `provider_billed_unreported` until a dollar charge is available; zero recorded
  dollars must not be interpreted as free execution.
- Cache/request identity includes the existing protocol's Definition, executor,
  exact model, normalized Config, context prompt and immutable input Artifact IDs.
  Changing the input photograph or analysis instructions invalidates the request.

The provider adapter uses OpenAI Responses `input_text` and an actual base64
`input_image`, with `store=false`; signed storage URLs are not model input.
API reference: https://developers.openai.com/api/docs/guides/images-vision#analyze-images

## Explicit Draft migration

Before:

`four image references + generic instruction → NOTTALGGAK → image`

After:

`variable reference image + fixed brief → image.describe → NOTTALGGAK`

`NOTTALGGAK + fixed face/side/body + variable reference image → Prompt attachment → image`

The final Prompt attachment has empty `config.text`, so it inherits the generated
master prompt instead of overriding it. Its four image edges precede the incoming
skill edge: fixed face, fixed side, fixed body, variable reference. This preserves
reference indices through the existing prompt-ancestry adapter. The analysis Node
receives only the variable reference, not the canonical character images.

The brief prioritizes the actual action over a generic portrait: gaze direction,
mouth/object contact, each hand's grip, support points, bent joints and camera
viewpoint must survive NOTTALGGAK compression. Body shape and identity come only
from the canonical character references. Unseen details remain uncertain.

Apply this migration only to the Draft, return the added Nodes/rewired edges and
prompt changes, warn that one extra vision request is added, then publish a new
WorkflowVersion. Retain v1, old Run snapshots and prior images. Optional secondary
outputs expose the observed description and refined prompt for inspection.

## Validation

`tests/test_image_description.py` covers actual image bytes in the normalized
provider request, token accounting, incomplete output, valid/invalid Config and
images, fixture parity, Local/Temporal Activity dispatch, lineage, cache replay,
retry classification and the complete published image → description → skill →
image chain with substituted inputs. The final image provider's reference order
and exact improved prompt are asserted. Unused branches are excluded and the
published Version hash remains unchanged by a Run.

Registry digest snapshots, existing OpenAI provider/Node/Workflow/Canvas tests and
the Web Registry contract test cover compatibility, generic editing, workflow
input exposure and Canvas round-tripping. Model-generated descriptions and images
still require visual review; the Node does not perform deterministic pose transfer.

## Live verification — 2026-10-01

The existing outfit workflow `workflow_6d71a8393b0545318f` was explicitly migrated
through v2 (image-grounded action analysis) and v3 (exclude source identity/hair
descriptions from analysis; preserve the full canonical short bob). Its v1 content
hash and prior Runs/Artifacts are unchanged. The managed input remains the single
Image `outfit_image`; the analysis and master prompt are secondary outputs.

Using source `art_18462dbd0bae4febba`, v3 Run
`canvasrun_8ef0b4f3c0ad4e5093` completed all nine graph nodes. The description
`art_b23402ee9e304f6385` explicitly records sipping, cup/lip contact, off-camera
gaze and the compact seated pose. NOTTALGGAK output `art_fb21cd5ff2294dc9b5`
forwards those action facts. Final Image `art_607393c8c49a46189d` was visually
reviewed for cup/lip contact, gaze direction and the short white/pink bob. The
intermediate v2 image is retained for comparison; it exhibited residual dark
source hair, which prompted the explicit v3 configuration change.

Validation passed: 75 API/Registry/Canvas/Workflow/OpenAI tests, Web Registry
contract tests, UI architecture checks, TypeScript checks and production build.
The read-only secondary text results are collapsible in the existing Run UI.

## Character invariants and context-aware scene washing — 2026-10-02

The corrected flow separates immutable character traits from their presentation:

```text
Fixed character specification ────────────────┐
        │                                     │
        └─ read-only context ──┐              │
Source photo → observations ──┤              │
Scene-washing instructions ───┴→ NOTTALGGAK   │
                                  │          │
                     Extract situation text │
                                  └──────────┤
                           Deterministic combination
                                  │
                  Fixed character + refined situation → image
```

NOTTALGGAK may improve how fixed traits appear in context: facial expression,
joint articulation and perspective, fabric ease/folds over the canonical body,
hair occlusion and scene-dependent illumination. It must not change identity,
body geometry, proportions, hair length or hair color. The character description
is a fixed Prompt source and is not exposed as a Workflow input. The original
character text reaches final composition directly; it is never replaced with
the refiner's wording.

`prompt.extract_section@1` selects exactly one literal Markdown ATX heading,
excluding headings inside fenced code. Its body ends at the next heading of the
same or higher level. Missing, duplicate and empty selections fail non-retryably;
there is no whole-document fallback. Output is a `Text` Artifact with schema
`prompt.section.v1`, port `prompt.text.v1`, and lineage role `source_prompt`.

`prompt.combine@1` has two required `prompt.text.v1` ports, `fixed` and `variable`.
It returns exactly `fixed + separator + variable`, preserving both inputs without
trimming, rewriting, summarizing or calling a model. The separator is materialized
in Config (default two newlines). Missing/duplicate/blank parts fail non-retryably.
Output is `Text` / `prompt.combined.v1`; lineage role is `prompt_fragment` and
metadata records input port provenance plus the hash of each full input. Local
cost is zero. Both Nodes share their production executor across Local, Temporal
and fixture environments. Their executor/Definition/config/input snapshots use
the common cache and Run protocol.

The NOTTALGGAK skill instructions, review translation and blueprint never become
the image provider's prompt. The review document remains separately inspectable.
Tests cover parser boundaries/errors, unmodified combination, lineage, cache,
Local/Temporal parity and two published runs with different situation inputs:
the character is present as read-only refinement context, the image provider gets
the original character plus only the washed situation, references stay ordered,
and the published Version remains unchanged. The former v1–v3 flows remain valid.

The managed workflow's v4 uses the fixed character Source twice: as read-only
context before NOTTALGGAK, and as the unchanged first input to final composition.
Run `canvasrun_adcd4d832744486581` completed with source photo
`art_312b6b99de41443782` and final Image `art_db88376a839d424eb4`. The recorded image
provider prompt was verified equal to the fixed character string, two newlines,
and the extracted situation/rendering string. The character block's SHA-256 is
`894ff276346a672e5967f785cfc79719cc5de7b962e7a25f68414825a31442db`.
The recorded prompt contains neither the skill's processing instructions nor its
section headings, review translation or blueprint. Character identity/anatomy
remain fixed; context-dependent expression, articulation, fabric and lighting are
within the refiner's scope. This verifies prompt preservation, not deterministic
pixel-level anatomy preservation by the image model. Relevant regression tests:
93 API tests plus Web Registry contracts, UI architecture and TypeScript checks.

## Lighting transfer refinement — v5

V5 changes only the image-analysis instructions and situation-washing scope.
The fixed character text (hash above), graph topology, Node contracts and v4
remain unchanged. Analysis now records a lighting map: observed source direction,
camera/subject relationship, bright and occluded planes, cast-shadow direction
and softness, face versus hair/shoulder exposure, and existing ambient fill.
Source technology is not inferred from flare alone. The scene refiner must retain
these relationships in the rendered situation text, recomputing local shadows for
the canonical bob/fringe, face planes and current head angle. It preserves existing
ambient/reflected light while excluding extra beauty fill, global darkening and
painted facial shadow masks.

Validation Run `canvasrun_baca2ce1a7954bdb8d` completed with source
`art_54330f69084942d190` and result `art_c84ede90dc6d492fb7`. The actual image
request was verified equal to the unchanged character text plus the refined
situation, including directional fringe, nose, chin and neck shading. The image
was visually reviewed; this remains generative lighting transfer rather than a
deterministic per-pixel shadow constraint.

## Fidelity failure and separate correction — v6

The later v5 window-side run `canvasrun_3591cafd83d2420eb9` did not preserve the
intended shaded frontal exposure or canonical torso appearance. Keeping the
character prompt unchanged is a verified text property, not proof of visual body
preservation. A correction trial with the original `gpt-image-2` still retained
too much frontal illumination and was not accepted as a solution.

An otherwise equivalent edit with `openai.image.precise`, pinned to
`gpt-image-2.5-sunburst-2026-09-08`, showed more shaded foreground illumination and
canonical torso volume in this sample. V6 therefore keeps the entire first pass
and adds one correction pass: contextual correction-instruction washing, section
selection, verbatim character-plus-correction composition, and image editing.
The four correction images are the first-pass candidate (its existing target
face/scene), canonical side/bust reference, canonical full-body reference, and
original situation. The three original canonical references remain in the first
pass. The default image alias and all v1–v5 contracts/snapshots stay unchanged.

The primary output is labeled as a correction candidate requiring comparison;
the initial image is a secondary output. Execution success is not automated visual
QA acceptance. There is no quality-driven regeneration loop. Uncached runs add one
text-refinement call and one image-edit call. Provider transport/activity retry
policies are unchanged. A deterministic body lock would require stronger geometric
or region-level controls; this two-pass generative flow does not claim one.

Run `canvasrun_b7f9e13132f2484e85` reused the exact v5 first image
`art_6dc5f344460c4a8d99` and produced correction `art_f60e61fdffe1427b97`.
The image provider's prompt was checked against the unchanged character text plus
only the washed edit instruction, and its four image inputs were checked in order.
V5's content hash is unchanged. Provider/Registry/Workflow regression tests: 88
passed, including the pinned precision alias, 9:16 dimensions and documented token
rates. Visual improvement is sample-specific and does not prove anatomy invariance.

Official API references:
- [Precision editing model and pinned snapshot](https://developers.openai.com/api/docs/models/gpt-image-2.5-sunburst)
- [Image editing and model limitations](https://developers.openai.com/api/docs/guides/image-generation)

GPT Image 2 already uses high input fidelity automatically; its preservation
behavior cannot be increased with an `input_fidelity` parameter. The precision
alias uses the documented custom 1152×2048 size and supported `high` quality.
Its exact snapshot was explicitly added to the cost catalog using the documented
token rates matching GPT Image 2. Recorded calculations are list-price estimates,
not invoices; unsupported/missing usage still remains unresolved.
