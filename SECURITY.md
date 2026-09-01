# Security Policy

Frameflow is currently a trusted single-user, self-hosted application. It does not provide user authentication or tenant isolation.

## Safe deployment boundary

- Keep `FRAMEFLOW_BIND_ADDRESS=127.0.0.1` unless an authenticated reverse proxy protects every exposed service.
- Never expose PostgreSQL, MinIO, Temporal, Temporal UI, or the API directly to the public internet.
- Provider credentials are write-only through the API but are not yet protected by a workspace-scoped KMS envelope.
- Review imported media rights and external URL ingestion before use.

## Reporting a vulnerability

Do not open a public issue containing credentials, exploit details, personal data, or private media. Use GitHub private vulnerability reporting for this repository. Include affected versions, reproduction steps, impact, and a proposed mitigation when possible.

Only the latest tagged release is supported until a broader support policy is announced.

## Automated checks

Pull requests and weekly scans check the complete Git history for secrets,
audit locked npm and Python dependencies, scan built container images, and
generate source and image SBOMs. The exception and license review policy is
documented in `docs/security-automation.md`.
