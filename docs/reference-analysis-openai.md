# Reference analyzer: OpenAI contract v2

`reference.decompose@1` remains unchanged, including its definition digest and Google pipeline. A Vertex AI 404 for `gemini-3.6-flash` means that model is unavailable to the project/region, not that the source video is corrupt.

`reference.decompose@2` uses the existing common executor and ports (`media.video.v1` → `data.reference_analysis.v1`). Its default semantic model is `openai.chat.latest` (`chat-latest`). OpenAI Responses receives timestamped JPEG frames in original aspect ratio, with strict structured output; Whisper (`whisper-1`) returns timed speech segments. `gpt-audio-1.5` receives actual audio in bounded 45-second chunks to identify music/SFX. FFmpeg scene detection and optional Demucs separation remain local. No Google request is required by v2. Reference media and all derived artifacts remain analysis-only.

## Explicit Draft migration

This is a breaking execution/config change. Until a general Upgrade UI is available, replace the Draft node contract explicitly through canonical Canvas save, preserving node ID, ports, edges, position and existing bindings. Do not modify a published Version or past artifact/run.

```diff
 type_key: reference.decompose
-contract_version: 1
-execution: {provider: local+google, model_alias: reference-analysis.pipeline}
+contract_version: 2
+execution: {provider: openai, model_alias: openai.chat.latest}
 config:
   source_language: auto
   separate_music: true
   scene_threshold: 0.28
+  sample_interval_seconds: 2
+  max_frames: 120
```

Materialize defaults and replace `definition_digest` with the v2 Registry digest. Report this diff and the following warnings to the Draft author: new OpenAI API usage (separate from ChatGPT subscription); sampled-frame event timing is approximate; for long clips sampling interval grows to respect `max_frames`; audio event boundaries are model estimates. Preview the new result and Publish a new WorkflowVersion if desired. No automatic in-place Version migration.

The common Local/Temporal dispatch records the selected semantic model in the Run. The manifest and Artifact runtime snapshot also preserve transcription/audio models, provider request IDs, actual sampling interval/count, normalized config and definition/executor revision. Unreported provider costs are not fabricated. Errors from each OpenAI stage identify whether transcription, visual analysis or audio analysis failed.

Tests cover v1 digest/lookup/execution, v2 schema/defaults and port compatibility, actual FFmpeg frame extraction, OpenAI request shapes and original image coordinates, timed transcripts and audio-window offsets, Japanese caption matching, lineage/reference isolation, cache separation and stored Canvas Local/Temporal parity.
