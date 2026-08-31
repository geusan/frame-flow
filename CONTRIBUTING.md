# Contributing

Frameflow is source-available for noncommercial use under the PolyForm Noncommercial License 1.0.0. By contributing, you confirm that you have the right to submit the work and that it may be distributed under the repository license.

## Development

```bash
make setup
make up
make check
make down
```

Node changes must follow `AGENTS.md`, `NODE_REFACTOR_PLAN.md`, and `docs/workflow-management-design.md`. Do not add production Node keys without a versioned Manifest and Executor contract. Do not commit credentials, local databases, generated media, Terraform state, or provider output.

Keep pull requests focused, include tests for behavior changes, and explain migrations and compatibility impact.
