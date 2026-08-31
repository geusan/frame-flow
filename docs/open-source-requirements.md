# Frameflow 오픈소스·셀프호스트 요구 사양

Status: Draft
작성 기준: 2026-08-31

## 1. 목적

이 문서는 Frameflow를 다음 세 가지 형태로 배포하기 위한 제품·보안·호환성 요구사항을 정의한다.

1. 개인 로컬 설치
2. 사용자가 직접 운영하는 셀프호스트 설치
3. 운영자가 제공하는 다중 사용자 클라우드 서비스

오픈소스 저장소 공개와 인터넷에 노출되는 클라우드 서비스는 별도의 완료 조건을 가진다. 로컬에서 동작한다는 사실만으로 클라우드 서비스가 안전한 것은 아니다.

## 2. 현재 기준선

현재 저장소에는 다음 기반이 있다.

- Next.js Web, FastAPI API, Local/Temporal 실행기
- PostgreSQL, MinIO 또는 S3 호환 Object Storage
- 버전이 있는 Node Definition Registry와 Port type
- Canvas Draft, immutable WorkflowVersion, WorkflowRun, Annotation
- Google, OpenAI, xAI, fal.ai Provider 실행 경로와 Provider 설정 UI
- 파일 또는 URL 기반 단일 Artifact 업로드
- 파일시스템 `.codex/skills/<skill-id>/SKILL.md` 기반 Project Skill 조회와 실행
- Docker Compose 개발 스택과 GCS/Cloud SQL 기반 Terraform 일부

공개·배포 전에 해결할 주요 차이는 다음과 같다.

- Canonical Canvas 저장 형식과 Legacy Node 경로 제거
- 사용자 인증과 Workspace 격리
- 사용자별 암호화 Credential 저장과 실행 시 주입
- DB 기반 Skill Registry와 immutable Skill version
- 로컬 디렉터리 Seed 및 다중 업로드
- Canvas/Workflow package export/import
- 오픈소스 라이선스, 보안 정책, 배포·업그레이드 문서
- Web/API/Worker/Temporal을 포함하는 실제 클라우드 배포 스택

## 3. 배포 Profile

### 3.1 Local

- 단일 사용자와 신뢰된 로컬 네트워크를 전제로 한다.
- 기본 실행기는 Local, 저장소는 MinIO 또는 로컬 S3 호환 저장소다.
- Provider Credential은 `.env`, Docker secret 또는 로컬 DB에서 설정할 수 있다.
- 인증을 끌 수 있지만 API는 기본적으로 loopback에만 bind해야 한다.

### 3.2 Self-hosted

- 하나 이상의 Workspace와 사용자를 지원한다.
- 인증과 Workspace authorization을 반드시 활성화한다.
- PostgreSQL과 Object Storage를 외부 영속 서비스로 사용한다.
- Credential encryption key, 백업, 업그레이드와 보존 정책은 설치 운영자가 관리한다.

### 3.3 Hosted cloud

- 모든 제품 데이터는 사용자와 Workspace 단위로 격리한다.
- 사용자 BYOK Credential과 운영 인프라 Credential을 분리한다.
- 실행 예산, 동시성, Rate limit, 업로드 한도와 Abuse 방지를 적용한다.
- KMS/Secret Manager, 관리형 PostgreSQL, Object Storage와 durable execution을 사용한다.

## 4. 필요 사양

현재 개발 기준 필수 도구는 다음과 같다.

- Node.js 22 이상
- Python 3.11 이상
- FFmpeg와 ffprobe
- Docker와 Docker Compose
- PostgreSQL 17 또는 호환되는 관리형 PostgreSQL
- Temporal 1.28 호환 서버 또는 Local execution mode
- MinIO, R2, S3 등 S3 호환 Object Storage

공개 문서에는 실제 부하 시험을 거쳐 아래 Profile의 최소·권장 CPU, RAM, 디스크와 동시 실행 수를 기록해야 한다.

- Core: Web/API와 Provider 기반 생성만 사용
- Media: FFmpeg, MediaPipe 사용
- Full: Temporal Worker, Demucs와 대용량 영상 처리 포함

Demucs, MediaPipe model download와 대용량 ML 의존성은 optional install profile로 분리한다. 지원 OS, CPU architecture, 브라우저와 GPU 필요 여부도 검증 결과로 명시한다.

## 5. BYOK Credential 계약

사용자에게 노출하는 용어는 `Bring your own key (BYOK)`로 통일한다.

### 5.1 범위

사용자 또는 Workspace가 제공할 수 있는 Credential:

- Google Gemini API key
- Google Service Account 또는 지원되는 OAuth 방식
- OpenAI API key
- fal.ai 및 실제 실행 Adapter가 있는 외부 Provider key

운영자가 관리해야 하는 인프라 Credential:

- PostgreSQL
- Object Storage
- Temporal
- KMS/Secret Manager
- 서비스 내부 서명 key

설정 화면에 Provider가 보인다는 이유만으로 실행 지원을 표시하지 않는다. Provider별로 `configured`, `adapter available`, 지원 capability를 구분한다.

### 5.2 저장

- Credential은 `workspace_id`, 선택적인 `user_id`, provider와 auth method에 연결한다.
- 평문 JSON DB 컬럼을 Source of Truth로 사용하지 않는다.
- KMS 기반 envelope encryption 또는 외부 Secret Manager reference를 사용한다.
- API 응답은 값 자체를 반환하지 않고 `has_value`, fingerprint와 갱신 시각만 반환한다.
- Credential 생성, 갱신, 검증, 사용과 삭제를 Audit event로 기록한다.
- Key rotation과 즉시 revoke를 지원한다.

### 5.3 실행

- Process-global 환경변수 변경으로 사용자 Credential을 전달하지 않는다.
- Run 생성 시 권한이 확인된 Credential reference를 Snapshot하고, Worker의 `ExecutionContext`가 실행 시 복호화한다.
- 평문은 필요한 Provider 호출 범위와 시간 동안만 메모리에 둔다.
- WorkflowVersion, export package, Run input/model snapshot, request hash, 로그와 오류에 Secret을 포함하지 않는다.
- Local과 Temporal은 같은 Credential resolver와 Executor dispatch를 사용한다.

## 6. DB 기반 Skill Registry

2026-08-31 구현 상태: 단일 설치 범위의 SkillDefinition/immutable SkillVersion/SkillInstallation DB 모델, bundled idempotent seed, `SKILL.md` 업로드·버전 활성화·설치 토글 API와 관리 UI가 연결됐다. Workspace scope와 코드 실행형 Skill Sandbox는 남아 있다.

### 6.1 데이터 모델

```text
SkillDefinition
- id
- workspace_id
- skill_key
- display_name
- description
- lifecycle
- current_version_id

SkillVersion
- id
- skill_definition_id
- version_number
- schema_version
- manifest_json
- instruction_body
- content_digest
- source_archive_uri: nullable
- created_by / created_at

SkillInstallation
- workspace_id
- skill_definition_id
- enabled
- permission_policy_json
- default_config_json
```

SkillVersion은 생성 후 수정하지 않는다. `skill.execute@1` Node는 실행할 Skill의 definition/version/digest를 Config 또는 Publish snapshot에 고정한다.

### 6.2 등록 경로

- 관리 UI에서 `SKILL.md` 또는 versioned Skill package 업로드
- API를 통한 생성과 새 버전 등록
- 셀프호스트 CLI를 통한 `.codex/skills` 일괄 Seed
- 저장소에 포함된 built-in Skill을 최초 기동 시 idempotent하게 등록

### 6.3 검증과 실행 안전

- Skill ID, frontmatter, 본문 크기와 UTF-8 검증
- content digest와 package checksum 검증
- lifecycle: `ACTIVE`, `DEPRECATED`, `RETIRED`, `BLOCKED`
- Prompt-only Skill과 코드/도구 실행 Skill을 구분
- 코드/도구 실행은 명시적 permission manifest와 별도 Sandbox가 없으면 허용하지 않음
- 기존 WorkflowVersion이 참조하는 SkillVersion을 삭제하거나 덮어쓰지 않음
- Skill 본문을 일반 관리·Run API 응답이나 로그에 노출하지 않음

## 7. 로컬 데이터 Seed와 다중 업로드

2026-08-31 구현 상태: 운영자 전용 `python -m app.seed skills|assets --root ...` CLI, dry-run, symlink·hidden/root 이탈 방지, MIME·용량 검증과 Artifact SHA-256 중복 제거가 구현됐다. Browser directory upload와 resumable multipart upload는 남아 있다.

### 7.1 셀프호스트 Seed

권장 인터페이스:

```text
frameflow seed assets --root /imports/assets --dry-run
frameflow seed skills --root /imports/skills --dry-run
frameflow seed packages --root /imports/packages --dry-run
```

Docker에서는 호스트 경로를 `/imports:ro`로 mount한다. 일반 API가 사용자가 입력한 임의의 서버 절대경로를 읽어서는 안 된다.

### 7.2 클라우드 업로드

- 브라우저 folder picker 또는 CLI
- Signed multipart/direct upload
- 중단 후 재개
- Batch 진행률과 개별 오류 리포트

### 7.3 공통 안전 규칙

- 허용 root 밖으로 나가는 `..`, absolute path와 symlink 차단
- 파일별·Batch 전체 크기, 개수와 MIME allowlist
- 파일 확장자와 실제 content type 교차 검증
- SHA-256 중복 제거
- ignore pattern과 hidden file 정책
- 압축 파일의 path traversal, zip bomb와 과도한 압축률 차단
- Artifact source, 상대경로, hash와 import job을 Lineage에 기록
- Dry-run, idempotency key, retry와 cancel 지원

## 8. Canvas/Workflow package export/import

2026-08-31 구현 상태: `frameflow.package.v1`의 `canvas.template` export/import, checksum 검증, Runtime·Secret·Signed URL 제외, 로컬 Artifact 참조 제거와 Unknown Node 보존이 Backend/Web에 연결됐다. Artifact blob을 포함하는 `portable` mode와 WorkflowVersion package는 남아 있다.

### 8.1 Package 형식

파일 확장자는 `.frameflow`를 사용하고 내부는 ZIP 기반 `frameflow.package.v1`로 시작한다.

```text
manifest.json
workflow/graph.json
workflow/inputs.json
workflow/bindings.json
workflow/outputs.json
annotations/annotations.json
skills/<skill-key>/<version>/manifest.json
artifacts/index.json
artifacts/blobs/<sha256>
checksums.json
```

Manifest는 package schema version, exporter version, source metadata, Node/Skill contract 요구사항, 파일 목록과 checksum을 가진다.

### 8.2 Export mode

- `template`: Canonical graph, 계약, UI metadata와 필요한 Skill reference만 포함
- `portable`: template에 사용자가 포함을 허용한 immutable Artifact metadata와 blob 추가

Run history, 비용, 로그, Credential, Signed URL, runtime status와 임시 preview는 기본 export에 포함하지 않는다.

### 8.3 Node와 Workflow 불변성

- 모든 실행 Node는 `type_key`, `contract_version`, `definition_digest`를 포함한다.
- Manifest default를 export/import 시 다시 적용하지 않는다. 저장된 materialized Config를 사용한다.
- Unknown Node와 설치되지 않은 Custom Editor는 삭제하지 않고 read-only로 보존한다.
- Sticky는 Annotation으로, Folder는 Draft layout으로, Upload/Drawing은 저장된 Typed Artifact source로 처리한다.
- Import는 게시된 WorkflowVersion을 수정하지 않고 새 WorkflowDefinition과 Draft를 생성한다.

### 8.4 Import

Import는 실제 쓰기 전에 Dry-run report를 반환한다.

- Package schema와 checksum
- Node/Port/Config/Binding/Output contract
- 누락, Deprecated, Retired, Blocked Node와 Skill
- Artifact 권리·타입·hash와 필요한 저장 용량
- ID 충돌과 remapping 계획
- Import 후 생성할 Workflow/Canvas/Skill 목록

Artifact와 Node ID remapping은 Edge, Binding, Output, Annotation과 Lineage reference에 원자적으로 적용한다. 실패 시 부분 Workflow를 남기지 않는다.

### 8.5 필수 테스트

- Template과 Portable round-trip
- Export → Import → Canonical export의 의미적 동일성
- 기존 contract version 호환
- Unknown Node/Skill 보존
- Artifact deduplication과 ID remapping
- Secret, Signed URL와 runtime field 제외
- 악성 ZIP, 손상된 checksum, 과대 package 거부
- Local/Temporal 실행 parity

## 9. 인증과 Workspace 격리

Hosted cloud 전에 반드시 다음을 완료한다.

- User, Workspace, Membership와 role
- 모든 mutable/read model의 Workspace scope
- API request actor를 request body의 `local-user` 값이 아니라 인증 principal에서 결정
- Artifact content와 Signed URL authorization
- WorkflowVersion, Run, Annotation, Skill과 Credential authorization
- Workspace별 예산, 동시 실행, 업로드와 저장 용량 한도
- 계정·Workspace export와 삭제

Local profile의 인증 비활성화는 명시적 설정으로만 허용하며 외부 interface bind 시 경고하거나 시작을 거부한다.

## 10. 오픈소스 공개 조건

- 라이선스와 저작권자 확정
- `LICENSE`, `NOTICE`, `CONTRIBUTING.md`, `SECURITY.md`, Code of Conduct
- 모델, 폰트, Docker image, npm/Python dependency와 샘플 미디어 라이선스 검토
- Git 전체 history secret scan
- dependency vulnerability, license와 SBOM 자동화
- Credential 없는 fixture/demo quickstart
- DB migration, upgrade, backup/restore와 rollback 문서
- Issue/PR template, release versioning과 changelog
- CI의 lint, typecheck, UI/Node architecture check, tests, build, container와 Terraform 검증

라이선스 선택은 별도 제품 결정이다. 라이브러리 재사용을 넓히는 permissive license와 호스팅 수정 공개를 요구하는 copyleft license의 목표를 먼저 확정한다.

## 11. Hosted cloud 배포 조건

- Web, API와 Worker의 개별 배포 단위
- Managed PostgreSQL과 private Object Storage
- Temporal Cloud 또는 운영 가능한 Temporal cluster
- KMS/Secret Manager와 Credential rotation
- TLS, CORS allowlist, CSP와 secure cookie
- Migration job, health/readiness probe와 rollback
- 로그, metric, trace, error reporting
- DB PITR, Object lifecycle와 disaster recovery test
- Provider 장애 격리, retry budget와 circuit breaker
- 사용자별 비용 한도, Abuse 대응과 운영자 kill switch

현재 Terraform의 Storage와 Cloud SQL 기반만으로는 Hosted cloud 완료로 보지 않는다.

## 12. 구현 Milestone

### M0. Public baseline

- 현재 변경사항 정리
- 생성 산출물과 Secret 제외
- `.env`와 무관하게 전체 CI 통과
- 라이선스와 공개 문서 결정

### M1. Stable contracts

- Node 리팩터링 Phase 3~7 완료
- Canonical Canvas/Workflow 저장과 Architecture guard

### M2. Secure tenancy and BYOK

- 인증, Workspace scope와 encrypted Credential resolver
- Local/Temporal credential parity

### M3. Portable content

- DB Skill Registry 완료, Workspace scope와 Sandbox 남음
- Local Seed CLI 완료, browser/resumable batch upload 남음
- `frameflow.package.v1` export/import

### M4. Open-source release

- fixture quickstart, release artifact, SBOM와 보안 자동화

### M5. Hosted preview

- Staging cloud stack
- Quota, 관측성, 백업·복구와 E2E 검증
