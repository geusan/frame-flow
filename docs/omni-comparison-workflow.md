# Gemini Omni comparison

The active comparison Draft was subsequently changed, at the user's request,
to image-and-prompt generation. See [the current image-only graph](comparison-image-only-workflow.md).
The source-video edit contract documented below remains available for historical
workflows and explicitly selected editing tasks.

2026-10-02. The third comparison draft uses Vertex Gemini Omni 1.1 Flash's
**source-video edit** capability. It is separate from the Veo first-frame and
MiniMax multimodal-reference drafts. All three share the immutable reference,
character scene image, Tsuki speech and caption settings.

## Contract and compatibility

`video.performance_transfer@2` is a new versioned workflow contract with the
existing image/video ports and the generic inspector. It transfers one source
performance to one image identity. The native `performance-edit` executor is
registered in the common registry for both local and Temporal execution.

- Source performance: 3–10 seconds; one PNG/JPEG/WebP identity image, up to 30 MB.
- Config: `prompt`, `resolution` (720p/1080p), `timeout_seconds` (30–3600).
- Binding: only prompt and resolution; credentials and execution state are not inputs.
- Model: `google.video.omni.vertex` → `gemini-omni-1.1-flash-preview`, global,
  existing Google service-account authentication.
- Output: immutable silent Video, `video.performance_transferred.v2`, preserving
  native output frames; source-duration drift above 250 ms is rejected. Separate
  `video.segment` nodes normalize the final frame clock with bounded tail padding.
- Lineage: `character_identity`, `driving_performance`; model, definition digest,
  normalized config, executor/FFmpeg revision and source/output durations are saved.
- No voice generation is included. Lip sync and final audio replacement remain
  independent nodes, as do caption rendering and clip concatenation.

V1 remains the FAL motion-transfer contract with `character_orientation` and its
original 3–30 second video mode. It and all existing definitions, snapshots and
artifacts remain unchanged. The old Gemini-API-only `google.video.omni` path also
remains intact; it is not relabeled as the Vertex model.

There is **no automatic V1 → V2 upgrade**. Manually replace the node in a Draft
and publish a new WorkflowVersion. Review this diff before replacement:

| Field | V1 | V2 |
| --- | --- | --- |
| Provider | FAL/Kling | Google/Vertex Omni preview |
| Config removed | — | `character_orientation` |
| Config added | — | `resolution` |
| Input duration | 3–30s in video mode | 3–10s |
| Output schema | `video.performance_transferred.v1` | `video.performance_transferred.v2` |
| Duration tolerance | 600 ms | 250 ms |

## Submission and costs

The provider adapter does not inspect UI node IDs. It submits Vertex Interactions
with `task=edit`, an explicit source-video tag and image-reference tag; using
`reference_to_video` instead would limit video references to three seconds and
would not represent editing the complete performance.

Submission writes a common billing receipt first. The returned interaction ID
is checkpointed immediately. Known IDs are polled and resumed without another
POST; ambiguous submissions are not automatically resubmitted. Usage is recorded
before output download or media validation. An unavailable dollar amount is
`unreported`, never a fabricated zero or the legacy fixed $1.40 estimate.

Google auth goes only to the fixed Vertex endpoint and the GCS SDK. Public output
URLs and redirects are validated and fetched without the service-account token.
Inline video, `outputs`, `output_video` and step-content video envelopes are read.

## Comparison timeline

The current 18.875-second speech has a pause from 9.614 to 10.841 seconds at
the measured -32 dB threshold. Split at frame 237 (9.875 seconds), producing
9.875s + 9.000s source edits, two lip-sync passes and one edit point. This differs
from the H3 10.208s boundary because an Omni source clip must not exceed 10s.

The original reference ends one frame before the normalized final clock. Only
the final reference segment allows one frame of held-image padding. Speech is
not sped up or stretched. Both final captions and Tsuki audio match the other
comparison drafts. Editing may still fail to preserve identity; visual output
quality is evaluated only after a paid generation is explicitly run.

## Validation

`test_omni_performance_edit.py` covers schema/defaults, old V1 compatibility,
model catalog, request roles, request limits, credential isolation, checkpoint
resume, retry/error policy, usage-before-download, local/Temporal parity in
fixture and mocked live execution, artifact lineage, cache/request hashes,
ambiguous-submission deduplication, duration validation, publish reachability,
binding and annotation isolation. Registry/golden, Google provider and provider
settings suites pass together (90 tests at initial implementation). Clean-architecture and billing checks also
pass (30 tests); the Registry-based Web architecture check passes.

The read-only authenticated interaction lookup reached the Vertex endpoint; it
does not establish model entitlement or prove a live generation will succeed.
No paid Omni generation is part of draft creation.

Sources verified on 2026-10-02:

- [Google video model overview](https://ai.google.dev/gemini-api/docs/video)
- [Omni model limits](https://ai.google.dev/gemini-api/docs/models/gemini-omni-flash)
- [Omni edit and reference modes](https://ai.google.dev/gemini-api/docs/omni)
- [Vertex Omni model](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/omni-1-1-flash)
- [Vertex video editing](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/video/edit-videos)
