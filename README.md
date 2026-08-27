# Frameflow

레퍼런스 영상의 원본 자산을 생성 단계와 격리하고, 추상적인 영상 포맷만 구조화해 새로운 숏츠를 만드는 그래프 기반 AI 영상 제작 시스템입니다.

현재 구현과 Canvas 사용법은 [`GUIDE.md`](./GUIDE.md)를 참고하세요.

이 저장소는 외부 Google API 자격증명 없이도 전체 제품 흐름을 검증할 수 있는 실행 가능한 MVP입니다. 로컬 Demo Provider는 모델 요청 ID·operation ID·Artifact·비용·대기 상태를 결정적으로 생성합니다. 실제 Google 호출은 동일한 `GenerationProvider` 경계 뒤에 연결합니다.

## 현재 구현

- React Flow 기반 Generation Canvas
- Reference Library와 Metadata Inspect API 연동
- Format Lab, Evidence, Core/Extensions JSON, 비교 시각화
- Run 목록, Model Registry, Candidate Compare
- FastAPI Reference·Format·Generation·Run·Artifact API
- URL 정규화와 중복 감지, analysis-only 권한 강제
- Format 추출·변형·가중 병합과 필드별 Lineage
- 실행 전 그래프 확장량·비용·예산 검사
- 불변 Artifact와 NodeRun Attempt 이력
- Prompt·모델·입력·파라미터 Snapshot을 보존하는 단일 Experiment 실행 이력
- MinIO에 저장되는 실제 SVG·MP4·WAV 로컬 생성 결과와 Canvas 미디어 재생
- `memory`·`minio`·`r2`·`s3`로 교체 가능한 S3 호환 Storage Provider
- Artifact SHA-256·Object Key·MIME·크기 보존과 Signed GET/PUT URL
- 동일 요청 해시 캐시와 노드별 Baseline 지정
- Retry·Regenerate·Fork·Candidate Select API
- SSE Run Event 스트림과 사용자 선택 후 재개
- Mock Provider의 idempotency request hash와 video operation ID
- Google Gen AI SDK 기반 Structured Output·Gemini Image·Veo·Gemini-TTS 운영 Adapter
- Temporal Workflow/Activity/Signal Worker와 `EXECUTION_BACKEND` 전환
- yt-dlp Ingest Adapter의 권리 승인 Gate, DNS 기반 SSRF 차단과 취소
- FFmpeg 세로형 렌더, ffprobe 기반 기본 QC, Provenance Manifest
- PostgreSQL/Temporal/MinIO 로컬 Compose
- GCS 버킷과 Reference/Generation 서비스 계정 분리 Terraform

## 빠른 시작

필요 조건은 Node.js 22+, Python 3.11+, FFmpeg, Docker입니다.

```bash
make setup
```

터미널 두 개에서 실행합니다.

```bash
make dev-api
make dev-web
```

`make dev-api`는 로컬 MinIO를 먼저 시작하고 필요한 Bucket은 API 시작 시 자동 생성합니다.

Web은 3000번부터 사용 가능한 포트를 자동으로 선택합니다. 시작 포트를 직접 지정하려면
`WEB_PORT=3100 make dev-web`을 사용합니다. API 포트를 바꿔야 할 때는
`API_PORT=8100 make dev-api`로 실행한 다음 Web도
`NEXT_PUBLIC_API_BASE_URL=http://localhost:8100 make dev-web`로 실행합니다.

- Web: 실행 로그에 표시되는 URL (기본값 <http://localhost:3000>)
- API 문서: <http://localhost:8000/docs>
- API 상태: <http://localhost:8000/health>

API를 실행하지 않아도 Canvas 편집은 가능하지만 생성 노드의 단일 Experiment 실행과 실행 이력은 API가 필요합니다. API가 연결되면 상단에 `API connected`가 표시되고 Reference Metadata Inspect 및 Experiment 계약을 사용합니다.

로컬 Experiment의 이미지·영상·음성은 각각 SVG, H.264 MP4, WAV 파일로 생성되어 MinIO에 저장됩니다. 이 파일은 실제 Google 생성 결과가 아니라 저장·재생 경로를 검증하기 위한 deterministic 미디어입니다.

전체 로컬 서비스는 다음 명령으로 실행할 수 있습니다.

```bash
docker compose up --build
```

- Web: <http://localhost:3001>
- API 문서: <http://localhost:8000/docs>
- Temporal UI: <http://localhost:8081>
- MinIO Console: <http://localhost:9001>

Compose의 호스트 포트는 `.env`에서 `WEB_PORT`, `API_PORT`, `POSTGRES_PORT`,
`TEMPORAL_PORT`, `TEMPORAL_UI_PORT`, `MINIO_PORT`, `MINIO_CONSOLE_PORT`로 변경할 수 있습니다.

## 검증

```bash
make check
```

개별 명령:

```bash
npm run lint
npm run typecheck
npm run build
cd apps/api && ../../.venv/bin/pytest -q
cd apps/worker && ../../.venv/bin/pytest -q
```

Worker 테스트는 실제 FFmpeg로 9:16 MP4를 생성한 후 해상도, 길이, 오디오, 픽셀 포맷과 재생 가능 여부를 ffprobe로 검사합니다.

## 구조

```text
apps/
  web/       Next.js, React Flow, Zustand UI
  api/       FastAPI control plane and local durable-state demo engine
  worker/    FFmpeg/ffprobe render and QC contracts
packages/
  schemas/   FormatCore, GenerationSpec, Timeline JSON Schema
infra/
  terraform/ GCS, IAM separation, Cloud SQL foundations
docs/
  adr/       Architecture decisions
```

```text
Reference bucket ──▶ Reference Analyzer ──▶ FormatProfile bucket
       ▲                                          │
       │ no access from generation worker         ▼
       └─────────────────────────────── Generation Worker
                                                  │
                         Images · Clips · Voice · Timeline · Final MP4
```

PostgreSQL이 사용자에게 보이는 상태의 기준입니다. `apps/api/app/service.py`의 `DemoRunEngine`은 API만 빠르게 실행할 때 사용합니다. Compose에서는 `EXECUTION_BACKEND=temporal`로 실제 Workflow와 Activity Worker가 같은 NodeRun/Artifact 상태 전이를 수행합니다.

## 실제 Google Provider 연결

1. `.env.example`을 `.env`로 복사합니다.
2. `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION`, 인증 방식을 설정합니다.
3. 구현된 `apps/api/app/providers_google.py` Adapter를 활성화하고 Provider Policy를 `live`로 전환합니다.
4. Provider 결과를 반환하기 전에 `provider_request_id`, `provider_operation_id`, `request_hash`를 NodeRun에 저장합니다.
5. video operation은 제출과 완료를 분리하고 Reconciler가 operation ID로 재연결하게 합니다.

Workflow에는 실제 모델 ID를 넣지 않습니다. 논리적 별칭만 사용하고 Run 생성 시점에 정확한 모델 ID를 Snapshot합니다.

## Storage Provider 전환

기본 로컬 Provider는 `minio`입니다. API는 시작할 때 필요한 버킷을 만들고, Artifact 본문을 저장한 뒤 DB에는 S3 URI, SHA-256, Bucket, Object Key, MIME과 크기를 기록합니다. Canvas에는 안정적인 Artifact Content URL을 전달하고, API가 요청마다 짧은 수명의 Signed GET URL로 연결합니다.

지원 Provider:

- `minio`: 로컬 Compose와 로컬 개발 기본값
- `r2`: Cloudflare R2 S3 API
- `s3`: 기타 S3 호환 저장소
- `memory`: 자동화 테스트 전용

R2로 바꿀 때는 `STORAGE_PROVIDER=r2`, `R2_ACCOUNT_ID`, `STORAGE_ACCESS_KEY`, `STORAGE_SECRET_KEY`를 설정하고 버킷을 미리 생성합니다. 자세한 변수는 [`.env.example`](./.env.example)에 있습니다.

## 보안 기준

- Reference 원본은 분석 전용 버킷에 저장합니다.
- `analysis_only`와 `unknown`은 요청값과 무관하게 생성 입력 권한이 `false`로 강제됩니다.
- Generation Worker에는 Reference 원본 버킷 IAM Binding이 없습니다.
- URL Ingest는 HTTP(S)만 허용하고 localhost를 차단합니다. 운영 Adapter에서는 전체 사설 IP 대역과 Redirect도 검사해야 합니다.
- 외부 프로세스는 shell 문자열 없이 인자 배열로 실행합니다.
- Artifact는 덮어쓰지 않고 새 ID와 Hash를 발급합니다.

## 운영 전 남은 외부 설정

소스 코드 밖의 고객 환경 값은 자동 완성할 수 없습니다. 운영 전 다음 항목을 채워야 합니다.

- Google Cloud 프로젝트·결제·Quota·Region
- Temporal Cloud Namespace와 인증서
- 실제 GCS Signed URL signer
- YouTube Data API와 권리 확인 UX의 법무 승인 문구
- Gemini/Veo/TTS/STT Provider Adapter 자격증명
- Cloud Run/GKE 이미지 Registry와 배포 환경 변수
- Sentry DSN과 OpenTelemetry Exporter

이 값들이 없어도 Mock Provider 기반 인수 흐름과 로컬 렌더/QC는 재현 가능합니다.
