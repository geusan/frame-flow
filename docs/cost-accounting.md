# Provider cost accounting

2026-10-02. This is additive execution observability: Node definitions, config/ports,
artifact schemas and published Workflow/Run snapshots are not migrated.

## Source of truth

`provider_costs` is the current receipt projection. `provider_cost_observations`
keeps each observation. A receipt is committed in its own transaction **before**
the provider call; response usage is committed before output validation/download.
Rollback of an Experiment or Artifact transaction cannot erase a paid response.
Amounts use `NUMERIC(24,12)`/Decimal. No prompt, media, credential, or signed URL is
written to the receipt.

Each new Experiment records its Run and NodeRun ownership, plus `cost_summary`.
Local/Temporal use the same `run_experiment` scope. Direct API capabilities also
enter a cost scope. One composite execution may have many receipts. Provider
request IDs deduplicate polling and resumes; a resumed task keeps its original
owner and original price, even when a later attempt completes the download.

`cost_usd` is a compatibility subtotal. **It is not sufficient to decide that a
Run was free.** Readers must inspect `cost_summary`:

| Status | Meaning |
| --- | --- |
| `recorded` | Provider reports the billed USD amount. |
| `calculated` | Measured usage × a recorded price; may differ from an invoice after account discounts/taxes. |
| `no_charge` | Local processing, cache/reused request, or explicit request rejection. |
| `pending` | Execution/submission not yet resolved. |
| `unreported` | Amount cannot yet be determined; `amount_usd` is null. |
| `partial` | Some charges known, others unresolved; show the known subtotal plus an unresolved marker. |
| `legacy` | Historical number without a trustworthy receipt basis; never silently relabel it as confirmed. |

`/workflow-runs` includes new standalone Experiments and direct provider calls,
in addition to existing Generation/Canvas/Version Runs. Each request is counted
once. `/costs?owner_id=...&limit=100&offset=0` returns paginated evidence. Reads can
reflect a later receipt resolution without rewriting a historical Run snapshot.

## Provider integration

Use `call_with_cost` for synchronous SDK requests, `submit_with_cost` /
`submit_sdk_with_cost` for async submissions, then `record_provider_result` before
download/validation. Do not invent a provider request ID from a prompt hash.
OpenAI SDK retries and Google GenAI SDK retries are disabled at the client boundary
so execution retries are individually observable. Uncertain transport outcomes
remain unresolved, even when no response usage is available.

Capture coverage: OpenAI Responses, chat/audio analysis, image generate/edit,
speech/transcription; Google GenAI text/image/TTS/Omni, Veo submissions/completion,
Chirp speech recognition; fal image/training/performance/lip-sync; Tripo tasks;
ElevenLabs speech-to-speech; MiniMax video; xAI Responses.

xAI's reported `cost_in_usd_ticks` converts at 10^10 ticks/USD. fal uses reported
billable units with the endpoint pricing response. Tripo credits, ElevenLabs
character cost are retained in their native units; lacking a
verified USD tariff must produce `unreported`, never an invented conversion.

MiniMax-H3 generation uses the official provider `usage.output_seconds` and
`usage.input_seconds` at $0.08/second for 768P or $0.13/second for 2K. Reference
images beyond the first five add $0.04 each; reference audio is free. Output
padding, requested duration, audio seconds and informational token counts do not
inflate the billable video seconds. Resolution, operation/task type and all
billable quantities must be known; regeneration/Context-IR/H3-Max use different
tariffs and are not silently priced as H3 generation. Native usage and the price
source remain attached to the receipt, including after a download failure.

The versioned public catalog in `cost_pricing.py` currently covers configured
OpenAI chat/text/image models, TTS-1/HD and Whisper, and verified Vertex
text/image/TTS/Veo rates. It handles cached/cache-write inputs, reasoning tokens,
regional and long-context prices where verified, and multiple generated videos.
Unknown models/modalities/tiers/custom endpoints and expired catalog prices fail
closed to an unresolved amount while preserving usage. Refresh the catalog's
rates, source date and validity after checking official sources; old receipt
prices remain fixed. Account-specific USD charges require provider billing data.

Sources checked on 2026-10-02:

- [OpenAI pricing](https://developers.openai.com/api/docs/pricing) and [image usage](https://developers.openai.com/api/docs/guides/image-generation).
- [Vertex pricing](https://cloud.google.com/vertex-ai/generative-ai/pricing), [Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing), [Google TTS pricing](https://cloud.google.com/text-to-speech/pricing).
- [xAI cost tracking](https://docs.x.ai/developers/cost-tracking).
- [MiniMax pricing](https://platform.minimax.io/docs/pricing/overview) and [H3 task usage](https://platform.minimax.io/docs/api-reference/video-generation-v2-query).
- fal's authenticated `GET https://api.fal.ai/v1/models/pricing` response is saved with each calculation.

## Validation and rollout

Migration `0012` only adds receipt tables and Experiment ownership/summary fields.
Apply it before restarting API and Temporal workers. Existing artifacts, graph
hashes, outputs and previously recorded numeric costs are preserved.

`tests/test_billing.py` covers pending-before-call durability, output rollback,
unknown/rejected outcomes, composite partial costs, async resume deduplication,
thread isolation, failed-run aggregation, standalone executions, historical
projection, cached/token/image/video calculations, and an SDK bypass guard.
`scripts/test-cost.mjs` covers UI distinctions and sub-cent precision.
