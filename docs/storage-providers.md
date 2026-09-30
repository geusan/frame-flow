# Selectable file storage

Frameflow supports **MinIO**, **Cloudflare R2**, and **AWS S3** through the same object storage interface. Configure connections in **Settings → File storage** (`/settings/storage`). Storage has a single settings surface, separate from AI/service-provider authentication. Previous R2 training credentials are retained in its compatibility section.

## Configure and select

1. Create private buckets for reference media, derived formats, generated assets, and final renders. Reference media must use a separate bucket. The other three may share a bucket.
2. Select a provider and enter its endpoint/region and bucket names.
   - MinIO: internal endpoint, browser-reachable endpoint, access key and secret key.
   - R2: Account ID (or explicit jurisdiction endpoint), region `auto`, and an R2 S3 Object Read & Write credential covering the selected buckets.
   - AWS S3: AWS region, empty endpoint for native AWS addressing, and either access keys (optional session token) or the execution host's IAM role / standard AWS credential chain. API and Worker hosts must both have the required role permissions.
3. Save the connection, run **Check connection**, then select **Use this storage**. Activation also runs the bucket checks. Tests write/read temporary probe objects and attempt to clean them up; allow DeleteObject to remove those probes.
4. New writes use the selected connection on the next operation. In-progress writes keep their chosen connection.

Connections are versioned when endpoints or bucket settings change. Artifact storage metadata records the connection ID. Switching the write default never makes old files use the new provider accidentally. The original environment connection is captured at first activation for artifacts that predate connection IDs. Do not remove that connection while files still reference it. Use **Rotate credentials** when replacing keys for the same connection, including historical files.

Credentials are stored in the existing server-side Provider secret store and are not returned by the settings API. No bucket is made public. Browser access uses short-lived signed URLs; for MinIO the public endpoint must be reachable by the browser. Cloud S3 API endpoints normally use the same endpoint for server and browser. Set bucket CORS when browser integrations require it; activation does not change bucket policies.

## Existing-file migration

Choose the target connection and use **Preview migration → Copy, verify and migrate**. Each object is streamed from its original storage to the target, without a full-size temporary file on the Docker disk. The destination bytes are read back to verify SHA-256 and byte count before switching the Artifact locator. ID, SHA-256, lineage, WorkflowVersion and Run content remain unchanged. Old locations are recorded in `storage_history`.

The operation is resumable. A successful object is skipped on retry; an already-present destination must match the checksum. A failed verification leaves the original locator untouched. Concurrent locator changes fail closed. Closing the page stops scheduling further batches; the active batch can finish. Reopen the plan to continue.

**Source objects are retained.** File migration does not by itself reclaim MinIO disk space. Review verified migration results before a separate source-cleanup operation. Database and media-processing temporary space remain local.

CLI equivalent (dry run by default):

```bash
# Run on the API host / container with its database configuration.
python -m app.storage_migration --target storagep_CONNECTION_ID
python -m app.storage_migration --target storagep_CONNECTION_ID --apply
```

To move back, select the original connection and run the same verified migration toward it. Existing matching objects are verified and reused.

## Environment-only deployments

Existing `STORAGE_PROVIDER`, endpoint, credential and bucket environment variables remain the fallback until a stored connection is activated. AWS S3 permits an empty endpoint and supports the SDK credential chain. `STORAGE_SESSION_TOKEN` and `STORAGE_ADDRESSING_STYLE` are available for environment-based deployments. The DB-selected connection is shared by Local and Temporal workers; it does not depend on vendor-specific Node configuration.

Tests cover secret redaction, immutable connection versions, activation failure, IAM-role configuration, key rotation, old reads and signed URLs after switching providers, streamed migration, hash mismatch, resume, and R2-to-S3 switching.

Cloud-selected file storage also hosts new LoRA training ZIPs in the generation bucket, so AWS S3 users do not need an R2 account for that path. External trainers require a publicly reachable signed URL. Existing local-environment deployments retain the legacy dedicated R2 training connection as a compatibility fallback; previously created training snapshots are unchanged.

For R2, the form can reuse the already saved Cloudflare R2 Provider credential entirely on the server. This copies the credential into the new versioned storage connection; it does not grant it permissions on new buckets. Supply buckets already covered by that credential or rotate it with a suitably scoped credential.

## Settings organization

`Settings` lists AI, speech, agent and video-download service connections. Storage is managed only in `File storage`. The former Cloudflare R2 model-provider card is not shown in the service list. Existing R2 training credentials remain available under the collapsed **Previous-version compatibility settings** section of `File storage`, visible only when previous credentials exist. **Import previous R2 credentials** copies the key into a versioned storage connection; subsequent changes belong to that saved connection. No credentials or legacy execution fallback are deleted by this UI reorganization.
