# Contributing

Frameflow is source-available for noncommercial use under the PolyForm Noncommercial License 1.0.0. By contributing, you confirm that you have the right to submit the work and that it may be distributed under the repository license.

## Development

```bash
make setup
make up
make check
make security-deps
make security-secrets
make down
```

Python 직접 의존성을 변경했다면 `make lock-python`으로
`apps/api/requirements.lock.txt`를 함께 갱신합니다. 취약점 예외와 SBOM·라이선스
정책은 `docs/security-automation.md`를 따릅니다.

Node changes must follow `AGENTS.md`, `NODE_REFACTOR_PLAN.md`, and `docs/workflow-management-design.md`. Do not add production Node keys without a versioned Manifest and Executor contract. Do not commit credentials, local databases, generated media, Terraform state, or provider output.

Keep pull requests focused, include tests for behavior changes, and explain migrations and compatibility impact.
