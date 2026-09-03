# Frameflow MCP server

Status: Implemented local profile

Frameflow MCP server는 기존 Node Registry, Workflow Compiler, WorkflowVersion과
Local/Temporal 실행기를 그대로 사용하는 protocol adapter다. MCP만의 Node 목록,
Config Default, Port 또는 실행 dispatch를 만들지 않는다.

## 실행

로컬 MCP host가 subprocess로 시작할 때는 stdio를 사용한다.

```bash
cd apps/api
../../.venv/bin/python -m app.mcp_server --transport stdio
```

로컬 Streamable HTTP endpoint는 다음 명령으로 실행한다.

```bash
make dev-mcp
```

기본 endpoint는 `http://127.0.0.1:8001/mcp`다. 현재 인증과 Workspace 격리가
구현되지 않았으므로 non-loopback bind는 기본적으로 거부한다.

## Workflow 작성 흐름

```text
node_contracts.list/get
  -> workflow_drafts.plan
  -> workflow_drafts.create
  -> workflow_drafts.get/update
  -> workflow_drafts.validate
  -> workflow_drafts.publish
  -> workflows.run
  -> runs.get / runs.respond / runs.cancel
```

`workflow_drafts.plan`과 `workflow_drafts.create`는 같은 선언형 Spec을 받는다.
Spec은 React Flow JSON이 아니라 다음 계약으로 구성한다.

- Node: symbolic `ref`, `type_key`, 선택적인 `contract_version`, Config와 model alias
- Edge: source/target Node ref와 Manifest Port key
- Workflow input: 타입, validation, default
- Binding: Manifest에서 `x-workflow-input`이 허용된 Config field
- Output: Node ref, output Port key와 Primary 여부

contract version을 생략하면 Plan 시점의 최신 `ACTIVE` 계약을 선택한다. Draft에는
선택된 `contract_version`, `definition_digest`, materialized Config를 명시적으로
저장한다. `DEPRECATED`, `RETIRED`, `BLOCKED` 계약으로 새 Draft를 만들 수 없다.

Server는 Plan/Create 시 다음을 검증한다.

- Node Manifest와 lifecycle
- closed Config Schema와 Default materialization
- versioned Port type compatibility와 cardinality
- 필수 Port와 DAG cycle
- Workflow input type과 `x-workflow-input`
- Primary output과 output reverse reachability
- Artifact/Character reference 존재 여부
- model alias와 Node capability

Publish는 정확한 Canvas revision을 요구하며 기존 WorkflowVersion을 수정하지 않는다.

## Tools

| Tool | 역할 |
| --- | --- |
| `frameflow.node_contracts.list` | 모든 등록 Node 계약 검색 |
| `frameflow.node_contracts.get` | immutable Node Manifest 조회 |
| `frameflow.models.list` | Node capability와 호환되는 논리 model alias 조회 |
| `frameflow.skills.list` | `skill.execute`에서 사용할 Skill 조회 |
| `frameflow.workflow_drafts.plan` | 쓰기 없는 Workflow compile/validation |
| `frameflow.workflow_drafts.create` | Canonical Draft Canvas와 Definition 생성 |
| `frameflow.workflow_drafts.get` | 수정 가능한 선언형 Draft Spec 조회 |
| `frameflow.workflow_drafts.update` | optimistic revision으로 Draft Spec 교체 |
| `frameflow.workflow_drafts.validate` | 현재 Draft dry compile |
| `frameflow.workflow_drafts.publish` | 불변 WorkflowVersion 게시 |
| `frameflow.workflows.list` | Workflow 목록 조회 |
| `frameflow.workflows.get` | Definition/Version 계약 조회 |
| `frameflow.workflows.run` | 게시 Version 실행 후 `run_id` 반환 |
| `frameflow.runs.get` | 상태, 비용, output과 human action 조회 |
| `frameflow.runs.respond` | approval 또는 candidate selection 제출 |
| `frameflow.runs.cancel` | 미완료 Run 취소 |
| `frameflow.artifacts.list` | Artifact/Character/LoRA 입력 검색 |
| `frameflow.artifacts.get` | Artifact metadata와 선택적 Lineage 조회 |

Workflow 실행 Tool은 Provider 작업이 끝날 때까지 연결을 점유하지 않는다. 즉시
명시적인 `run_id`를 반환하고 호출자는 `frameflow.runs.get`을 사용한다.

## Resources

```text
frameflow://node-contracts/{type_key}/{contract_version}
frameflow://workflows/{workflow_id}
frameflow://workflows/{workflow_id}/versions/{version_number}
frameflow://runs/{run_id}
frameflow://artifacts/{artifact_id}
```

Artifact resource는 본문을 MCP 응답에 포함하지 않고 metadata와 안정적인 API content
URL을 반환한다. 대용량 Image/Video/Audio를 LLM context에 Base64로 넣지 않는다.

## 보안 범위

현재 구현은 신뢰된 로컬 사용자 profile이다. 공개 Remote MCP로 전환하기 전 다음이
필수다.

- OAuth 2.1 Protected Resource Metadata와 audience validation
- User/Workspace/Membership와 모든 query의 Workspace scope
- Artifact content URL authorization
- Workflow Run idempotency key, 예산, 동시성, rate limit
- request body의 `local-mcp` 대신 인증 principal 기반 Audit actor
- MCP Origin allowlist와 TLS

`FRAMEFLOW_MCP_ALLOW_INSECURE_REMOTE=true`는 격리된 개발 네트워크에서만 사용할 수
있는 명시적 escape hatch다.

## 검증

```bash
cd apps/api
../../.venv/bin/pytest -q tests/test_mcp_server.py

npx @modelcontextprotocol/inspector --server-url http://127.0.0.1:8001/mcp --transport http
```

Contract test는 Registry에 등록된 모든 `(type_key, contract_version)`이 MCP에서
조회되는지, 잘못된 Port가 쓰기 전에 거부되는지, MCP로 만든 Draft를 Web API가
Canonical Canvas로 읽는지, Publish와 fixture Run 결과가 선언된 output key로
projection되는지를 확인한다.
