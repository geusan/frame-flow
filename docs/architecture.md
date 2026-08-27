# Architecture

## Bounded contexts

| Context | 책임 | 주요 엔티티 |
| --- | --- | --- |
| Reference Intelligence | 권리 확인, 수집, Proxy, 분석 | ReferenceAsset, ReferenceSet, Artifact |
| Format Engine | 추출, Evidence, Merge, Variation | ExtractionRecipe, FormatProfile, FormatVariant, FormatComposition |
| Generation Studio | Brief 해석, 후보 생성, Timeline, Render | GenerationBrief, GenerationSpec, Candidate, Timeline |
| Control Plane | Compile, 실행 상태, 비용, 복구 | WorkflowVersion, ExecutionPlan, Run, NodeRun, NodeAttempt |
| Governance | 불변성, Lineage, Audit, 권한 | Artifact, ArtifactLineage, CostLedger, AuditEvent |

## State ownership

- PostgreSQL: 제품 상태의 기준. UI는 이 상태만 신뢰한다.
- Temporal: 장기 실행의 내구성, 재시도, Signal/Update, Timer를 담당한다.
- Object Storage: 대용량 불변 Artifact 본문을 저장한다. 로컬은 MinIO, 운영은 설정에 따라 R2/S3를 사용하며 GCS 기반은 Terraform 확장 대상으로 유지한다.
- Provider: 외부 비동기 operation을 수행하며 operation ID를 통해 재연결한다.

Temporal Payload에는 Artifact 본문을 넣지 않는다. ID, URI, Hash와 작은 실행 메타데이터만 전달한다.

## Run state flow

```text
READY → QUEUED → CLAIMED → RUNNING → SUCCEEDED
                         ├→ SUBMITTED → RUNNING
                         ├→ WAITING_INPUT → RUNNING
                         ├→ RETRY_WAIT → QUEUED
                         ├→ FAILED
                         └→ CANCELED
```

상위 Artifact가 바뀌면 기존 하위 Artifact는 삭제하지 않고 NodeRun만 `STALE`로 표시한다.

## DB ERD

```text
ReferenceAsset ──< ReferenceSet
      │
      └──< Artifact

Format ──< GenerationBrief ──< Run ──< NodeRun
  │                               │         │
  └── parent_ids                  │         └── output_artifact_ids
                                  └── execution_plan snapshot

Artifact ── input_artifact_ids ──> Artifact
AuditEvent ── subject_id ──> any immutable entity
```

초기 SQLAlchemy 모델은 [database.py](../apps/api/app/database.py)에 있습니다. 운영 Migration에서는 JSON 배열을 별도 연결 테이블로 정규화해 대규모 Lineage Query를 최적화할 수 있습니다.

## Trust boundary

Reference transcript, metadata와 외부 페이지 텍스트는 모두 untrusted data입니다. Prompt Compiler는 이를 명령 채널이 아니라 구분된 데이터 블록으로만 전달해야 합니다. 생성 Worker는 Reference 원본 URI를 해석하거나 읽을 권한이 없습니다.
