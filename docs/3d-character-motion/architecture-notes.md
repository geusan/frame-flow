# 3D Character Motion — Architecture Notes

Date: 2026-09-04

## Existing Frameflow architecture

- **Graph and persistence:** Canvas authoring state is normalized to `canvas.document.v1` by
  `apps/api/app/canvas_documents.py`. A production node is stored as `type_key`,
  `contract_version`, immutable `definition_digest`, materialized `config`, runtime selection,
  and UI metadata. PostgreSQL/SQLite stores Canvas documents, immutable WorkflowVersions,
  CanvasRuns, CanvasNodeRuns, Experiments, and Artifacts in `apps/api/app/database.py`.
- **Node registration:** JSON manifests under `apps/api/app/nodes/definitions/` are the source of
  truth. `NodeRegistry` validates versioned ports, closed Config Schemas, workflow-input metadata,
  editor refs, and executor refs at process startup. Web library entries and generic inspectors are
  generated from the active manifests returned by `/node-definitions`.
- **Ports:** `apps/api/app/nodes/port_types.v1.json` owns versioned port IDs and explicit
  compatibility. The Web graph uses each type's `legacy_type` only as a rendering/React Flow
  adapter. Publish validates the manifest ports again on the server.
- **Execution:** A CanvasRun freezes a graph snapshot and creates persistent CanvasNodeRuns. The
  local scheduler and Temporal workflow both call the same `execute_canvas_node` function, which
  creates an Experiment and dispatches through `NodeRegistry.execute`. Ready nodes in the same DAG
  wave run concurrently. Temporal supplies retries, cancellation, activity heartbeats, and a
  30-minute activity limit.
- **Long jobs:** The browser never executes providers, FFmpeg, or other heavy work. It creates a
  CanvasRun and consumes `/canvas-runs/{id}/events` SSE updates. The Compose default dispatches
  Node execution through the separate `temporal-worker` service. Blender itself runs in a further
  isolated `blender-worker` container and is reached only over the internal Compose network. This
  is capability/process isolation, not yet a GPU-aware Temporal task queue.
- **Artifacts:** `create_artifact` writes immutable bytes to memory/MinIO/R2/S3, stores SHA-256,
  MIME, size and object location in `artifacts`, and records normalized `artifact_edges` lineage.
  Node results return artifact IDs; downstream nodes resolve those IDs through object storage.
  `/artifacts/{id}/content` streams bytes and supports byte ranges.
- **Caching:** `run_experiment` hashes executor revision, node contract/digest, normalized Config,
  logical and exact models, Prompt, and immutable input snapshots. A successful Experiment with the
  same request hash is reused. At present the input snapshot contains immutable Artifact IDs rather
  than substituting content hashes, so byte-identical separately uploaded artifacts do not share a
  cache entry.
- **Uploads:** `/artifacts/upload` validates type and a 250 MB limit, stores immutable bytes, and
  creates browser-compatible derivatives for video where needed. The existing authoring Upload
  element is converted to an Artifact source before Publish.
- **Previews:** image/video/audio outputs use stable Artifact content URLs. Structured data is
  summarized by the common node card and is fully visible in the common read-only Raw data tab.
  MotionTrack has an existing specialized landmark summary; generic node contracts do not require
  custom UI.
- **Status and errors:** Node state uses `BLOCKED`, `READY`, `QUEUED`, `RUNNING`,
  `WAITING_INPUT`, `SUCCEEDED`, `FAILED`, and `CANCELED` (plus retry/stale states). Errors are stored
  on the NodeRun and returned over SSE. Executor exceptions therefore need actionable messages.
- **Backend/frontend boundary:** Next.js only owns graph authoring, schema-generated Config UI,
  upload controls, previews, and SSE state. FastAPI owns manifests, validation, persistence,
  compilation, execution, Artifact storage, and signed/content URLs.
- **Runtime assumptions:** host development requires Docker; it does not require a host Blender
  installation. Compose provides PostgreSQL, Temporal, MinIO, API, a Temporal worker, Web, and a
  dedicated Blender 4.3.2 worker image. MediaPipe executes inside the Linux Temporal worker and
  Blender subprocesses execute inside the Blender worker.

## Extension points used by this feature

1. New workflow types start at immutable `@1`; Tripo's changed input/config semantics use new `@2`
   contracts while the manual/pass-through `@1` definitions remain available for old Versions.
2. New semantic port types are added to the existing Port Type Registry; no parallel graph type
   system is introduced.
3. Twelve single-responsibility executors are registered in the existing Executor Registry. Provider
   choices are resolved through capability abstractions, not Canvas UI conditionals or one central
   node-key switch.
4. Every result is created by the existing `create_artifact` function and carries existing lineage,
   storage, caching, and preview URLs.
5. MediaPipe's existing `motion.track.v1` extractor remains intact. A dedicated adapter converts
   its landmarks into the new provider-independent `humanoid.motion.v1` contract. Raw landmark
   coordinates are never applied directly to a target rig.
6. `HttpBlenderExecutionProvider` uploads immutable inputs to the internal `blender-worker` service
   and downloads only declared outputs. The service invokes Blender with an argument vector,
   `--background`, and `--disable-autoexec` in a fresh temporary directory. `local` remains an
   explicit development provider; changing placement does not change node contracts.
7. Tripo is implemented behind `TripoImageTo3DProvider` and `TripoAutoRigProvider`. The API client
   performs bounded uploads/downloads, asynchronous task polling, progress reporting, safe download
   host validation, and actionable retry classification. Submitted task IDs are persisted on the
   Experiment so a Temporal retry can resume instead of spending credits on a duplicate task.
   Database-managed credentials must pass Tripo `/account/balance` validation when saved before the
   API or Temporal worker is allowed to export the key into its process environment.
   Task IDs are opaque URL-path-safe values because the live v3 API returns UUIDs even though some
   documentation examples use a `task_` prefix.
8. Tripo contracts are snapshotted into `single_attempt_node_ids` when a CanvasRun is scheduled.
   Temporal therefore uses `maximum_attempts=1` for those Activities. Immediately before each
   billable `generate`, `rig_check`, or `rig` POST, the executor takes a request-hash PostgreSQL
   advisory lock and persists a stage-specific `pending` claim. Concurrent runs cannot issue a
   second POST, and an unknown submission outcome is blocked for manual reconciliation rather than
   replayed.

## New contracts

All elements below are Workflow data/execution nodes, not Canvas-only elements.

| Node | Responsibility | Primary port |
| --- | --- | --- |
| `character.reference.validate@1` | Validate and freeze a source character image | `artifact.character_reference.v1` |
| `character.image_to_3d@1` | Provider-backed image-to-GLB conversion/manual override | `model.character_3d.v1` |
| `character.reference.multiview@1` | Select and validate role-keyed images from a Character bundle | `artifact.character_reference_set.v1` |
| `character.image_to_3d@2` | Tripo P1/H3.1 multiview generation with immutable task/model snapshot | `model.character_3d.v1` |
| `character.model.validate@1` | Parse and assess an animation candidate GLB | `model.character_3d_validated.v1` |
| `character.auto_rig@1` | Provider-backed rigging/manual or already-rigged pass-through | `model.character_rigged.v1` |
| `character.auto_rig@2` | Tripo Rig Check and Mixamo-compatible biped Auto Rig | `model.character_rigged.v1` |
| `motion.video.validate@1` | ffprobe and freeze a motion source video | `media.motion_source_video.v1` |
| `motion.humanoid.extract@1` | Provider extraction plus canonical motion normalization | `data.humanoid_motion_raw.v1` |
| `motion.humanoid.cleanup@1` | Deterministic interpolation, smoothing, limits and foot/root cleanup | `data.humanoid_motion_clean.v1` |
| `motion.humanoid.retarget@1` | Map canonical rotations onto a rig and bake animation | `model.character_animated.v1` |
| `video.blender_render@1` | Apply independent camera/light/style settings and render video | `media.video.v1` |

## Known architectural constraints

- The current Web compatibility adapter renders one source handle from a manifest's first output.
  Secondary Artifact IDs can be inspected and reused by executors, but distinct secondary output
  handles are not yet fully represented on the Canvas. These contracts therefore put the
  composable downstream value first and expose validation/metadata/preview artifacts second.
- Temporal and local execution share one registry. Blender has a dedicated container boundary, but
  Blender/GPU requests do not yet have a dedicated Temporal task queue, concurrency semaphore, or
  resource scheduler. Production should scale and admission-control this capability separately.
- Current request caching is safe for immutable inputs but only deduplicates the same Artifact IDs.
  A future cache revision should replace input IDs with their stored SHA-256 values.
- The MVP Blender HTTP protocol base64-encodes complete files in a bounded internal request/response.
  Large production assets should be exchanged through immutable object-store references and signed
  worker-scoped URLs to avoid holding hundreds of megabytes in both services.
