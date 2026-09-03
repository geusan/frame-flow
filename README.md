# Frameflow

레퍼런스 영상의 원본 자산을 생성 단계와 격리하고, 추상적인 영상 포맷만 구조화해 새로운 숏츠를 만드는 그래프 기반 AI 영상 제작 시스템입니다.

> **Source-available, noncommercial software.** Frameflow는 PolyForm Noncommercial License 1.0.0으로 제공됩니다. 개인 연구·학습·취미와 비영리 기관 사용은 허용되지만 상업적 사용에는 별도 서면 라이선스가 필요합니다. 비상업 제한 때문에 OSI 승인 오픈소스는 아닙니다.

현재 구현과 Canvas 사용법은 [`GUIDE.md`](./GUIDE.md)를 참고하세요.
오픈소스·셀프호스트·BYOK·데이터 이동 요구사항과 구현 순서는 [`docs/open-source-requirements.md`](./docs/open-source-requirements.md)를 참고하세요.

이 저장소는 실제 Google Cloud Provider와 로컬 FFmpeg 실행을 사용하는 실행 가능한 MVP입니다. 운영 기본 모드는 `live`이며 Google Cloud 프로젝트와 Application Default Credentials가 없으면 AI 생성·분석 Step이 명확히 실패합니다. 자동화 테스트만 명시적인 `fixture` 모드를 사용합니다.

## 현재 구현

- React Flow 기반 Generation Canvas
- URL 기반 분리 화면: Canvas·Image/Video Assets·Runs·Settings·Model Registry
- Settings의 Google/OpenAI/xAI Provider 연결 정보 DB 관리와 `.env` 최초 자동 이관
- Run 목록, Model Registry, Candidate Compare
- Workspace 카운트·통합 Run·모델 사용량·Format evidence를 실제 저장 데이터로 표시하는 UI
- PostgreSQL 기반 Canvas 문서 목록·자동 저장·localStorage 데이터 1회 이관
- `frameflow.package.v1` 기반 Canvas template export/import와 checksum·ZIP 안전 검증
- DB 기반 immutable Skill Definition/Version Registry와 `SKILL.md` 관리 UI
- `/imports` read-only mount를 사용하는 Skill·Asset Seed CLI
- FastAPI Reference·Format·Generation·Run·Artifact API
- URL 정규화와 중복 감지, analysis-only 권한 강제
- Format 추출·변형·가중 병합과 필드별 Lineage
- 실행 전 그래프 확장량·비용·예산 검사
- 불변 Artifact와 NodeRun Attempt 이력
- Prompt·모델·입력·파라미터 Snapshot을 보존하는 단일 Experiment 실행 이력
- Gemini Image·Veo·Gemini-TTS 결과를 MinIO에 저장하고 Canvas에서 재생하는 실제 생성 경로
- 교체 가능한 Video Downloader Adapter(`yt-dlp` 기본)를 통한 Canvas URL 업로드 Artifact와 FFmpeg 기반 Video Editor·오디오 교체·드래그 자막 배치·승인 후 이어지는 하드 자막 최종 렌더·ffprobe QC
- Canvas `Video Reference Analyzer` composite 노드의 STT·음악 구간/선택적 Demucs 2-stem·컷·액션·화면 자막 위치 변화·효과음 타임라인과 `reference.decomposition.v1` Artifact
- `curl_cffi` Chrome impersonation, 제한 재시도, 성공한 메타데이터 재사용을 이용한 TikTok TLS/JS 챌린지 대응
- Asset Library 비디오 seek·현재 프레임 캡처와 원본 Video → Image Artifact lineage
- Images의 브라우저 Canvas 수동 편집과 Nano Banana/GPT Image 자연어 편집, 원본을 보존하는 파생 Image Artifact lineage
- 정규화된 `artifact_edges`, 양방향 Lineage API·그래프·Before/After·생성 Prompt/모델 상세
- Google/OpenAI 모델 선택형 Prompt 장면 검색·후보 seek/캡처
- `memory`·`minio`·`r2`·`s3`로 교체 가능한 S3 호환 Storage Provider
- Artifact SHA-256·Object Key·MIME·크기 보존과 Signed GET/PUT URL
- 동일 요청 해시 캐시와 노드별 Baseline 지정
- Retry·Regenerate·Fork·Candidate Select API
- SSE Run Event 스트림과 사용자 선택 후 재개
- Canvas DAG Run·NodeRun 영속화, 독립 노드 병렬 Worker 실행과 SSE 실시간 상태 복구
- 실제 Google Provider request hash와 Veo operation submit/poll·결과 다운로드
- Google Gen AI SDK 기반 Structured Output·Gemini Image·Veo·Gemini-TTS 운영 Adapter
- OpenAI Responses API·ChatGPT Latest·GPT-5.6·GPT Image 2·GPT-4o Mini TTS Provider
- xAI Responses API·Grok 4.6 Text Provider
- Translate Video의 Chirp 3 STT → Gemini 세그먼트 번역 → Gemini-TTS → FFmpeg Mux 파이프라인
- Temporal Workflow/Activity/Signal Worker와 `EXECUTION_BACKEND` 전환
- yt-dlp Ingest Adapter의 권리 승인 Gate, DNS 기반 SSRF 차단과 취소
- FFmpeg 세로형 렌더, ffprobe 기반 기본 QC, Provenance Manifest
- PostgreSQL/Temporal/MinIO 로컬 Compose
- GCS 버킷과 Reference/Generation 서비스 계정 분리 Terraform

## 빠른 시작

필요 조건은 Node.js 22+, Python 3.11+, FFmpeg, Docker입니다.

```bash
cp .env.example .env
make up
```

- Web: <http://localhost:3001>
- API: <http://localhost:8000/docs>
- 종료: `make down` — 데이터 Volume은 보존됩니다.
- 상태/로그: `make ps`, `make logs`

기본적으로 모든 포트는 `127.0.0.1`에만 바인딩됩니다. 인증 Reverse Proxy 없이 `FRAMEFLOW_BIND_ADDRESS=0.0.0.0`으로 변경하지 마세요.

소스 기반 개별 개발 환경은 `make setup`, `make dev-api`, `make dev-web`을 사용합니다.

터미널 두 개에서 실행합니다.

```bash
make dev-api
make dev-web
```

`make dev-api`는 로컬 MinIO를 먼저 시작하고 Alembic Migration을 적용한 뒤 API를 실행합니다. 필요한 Bucket은 API 시작 시 자동 생성합니다.

Web은 3000번부터 사용 가능한 포트를 자동으로 선택합니다. 시작 포트를 직접 지정하려면
`WEB_PORT=3100 make dev-web`을 사용합니다. API 포트를 바꿔야 할 때는
`API_PORT=8100 make dev-api`로 실행한 다음 Web도
`NEXT_PUBLIC_API_BASE_URL=http://localhost:8100 make dev-web`로 실행합니다.

- Web: 실행 로그에 표시되는 URL (기본값 <http://localhost:3000>)
- API 문서: <http://localhost:8000/docs>
- API 상태: <http://localhost:8000/health>

Web 화면 경로는 `/canvases`, `/canvases/{id}`, `/workflows`, `/workflows/{id}`, `/asset/images`,
`/asset/videos`, `/runs`, `/settings`, `/settings/models`로 분리되어 있습니다.

API를 실행하지 않아도 Canvas 그래프 편집은 가능하지만 생성·미디어 편집 노드 실행, 업로드 Artifact, 실행 이력은 API가 필요합니다. API가 연결되면 상단에 `API connected`가 표시되고 Reference Metadata Inspect 및 Experiment 계약을 사용합니다.

Experiment의 이미지·영상·음성은 각각 Gemini Image, Veo, Gemini-TTS에서 생성되고 MinIO에 불변 Artifact로 저장됩니다. `GENERATION_PROVIDER_MODE=fixture`는 자동화 테스트에서만 사용합니다.

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

신뢰할 로컬 데이터를 먼저 등록하려면 전용 import directory를 사용합니다.

```bash
# Host 개발 환경
IMPORT_ROOT=/absolute/path/to/skills make seed-skills
IMPORT_ROOT=/absolute/path/to/assets make seed-assets

# Compose 환경: FRAMEFLOW_IMPORTS_DIR가 read-only /imports로 mount됨
docker compose run --rm api python -m app.seed skills --root /imports --dry-run
docker compose run --rm api python -m app.seed assets --root /imports
```

Skill directory는 `<skill-id>/SKILL.md` 구조만 등록합니다. Seed CLI는 symlink, hidden file, root 이탈, 허용되지 않은 MIME과 250 MB 초과 파일을 거부하며 Asset은 SHA-256으로 중복 제거합니다. 일반 HTTP API는 서버의 임의 로컬 경로를 읽지 않습니다.

## 검증

```bash
make check
make security-deps
make security-secrets
```

전체 Git 이력 Secret 검사, 해시가 고정된 Python 의존성, npm/Python 취약점 검사,
컨테이너 검사와 SBOM 생성 정책은 [`docs/security-automation.md`](./docs/security-automation.md)를 참고하세요.

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
  api/       FastAPI control plane and local/Temporal execution engine
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

PostgreSQL이 사용자에게 보이는 상태의 기준입니다. 일반 Generation Run과 Canvas DAG Run 모두 Local Worker와 Temporal Activity가 같은 실제 NodeRun/Experiment/Artifact 실행 계약을 사용합니다. 브라우저는 실행을 직접 수행하지 않고 Canvas Run을 생성한 뒤 SSE 상태를 구독합니다.

## 실제 Google Provider 연결

Image, Voiceover, LLM과 Script는 Google 또는 OpenAI Provider를 선택할 수 있고, Video·Format extraction·Speech Subtitle·Translate Video는 실제 Google Cloud API를 사용합니다. Google AI 연결은 Settings에 등록한 Service Account JSON만 사용합니다. 프로젝트 ID는 JSON에서 가져오며 Gemini·Veo는 Vertex AI, Chirp 3 자막은 Speech-to-Text V2에서 같은 Service Account로 인증합니다. API key와 사용자 ADC 파일 경로는 Google Provider 인증에 사용하지 않습니다. Translate Video는 현재 60초 이하를 지원하며 Transcript, 번역문, WAV, SRT와 최종 MP4를 각각 불변 Artifact로 저장합니다.

Service Account에는 사용하는 API를 활성화한 뒤 최소한 Vertex AI User(`roles/aiplatform.user`)와 Cloud Speech Client(`roles/speech.client`)를 부여합니다. Veo 결과를 GCS에 저장하면 대상 버킷에 필요한 Object 권한도 별도로 제한해 부여합니다.

Provider별 인증 방식과 최소 권한은 [`docs/provider-auth-roles.md`](docs/provider-auth-roles.md)를 참고하세요.

Canvas의 Image, Voiceover, LLM Assistant와 Script 노드는 모델 선택에서 OpenAI를 선택할 수 있습니다. Voiceover는 Vertex AI의 Gemini 2.5 Flash TTS, Gemini 3.1 Flash TTS Preview, Gemini 2.5 Pro TTS와 OpenAI GPT-4o Mini TTS, TTS-1, TTS-1 HD를 지원합니다. `OPENAI_API_KEY`를 설정하면 Responses API의 GPT-5.6/ChatGPT Latest, GPT Image 2와 OpenAI TTS 모델이 활성화됩니다. Video Generator는 Vertex AI의 Veo를 사용합니다.

ChatGPT 또는 Claude 구독은 API Provider와 분리된 `Local Subscription Agent` Node에서 사용합니다. 이 Node는 빈 임시 작업 디렉터리에서 도구를 비활성화하거나 read-only로 제한한 로컬 Codex/Claude Code CLI를 실행하고 Text Artifact를 반환합니다.

1. 로컬 실행은 API와 Worker 호스트에 `codex`, `claude` CLI가 설치되어 있어야 합니다.
2. ChatGPT: Settings → OpenAI → `ChatGPT OAuth`를 선택하고 실행 호스트에서 `codex login --device-auth`를 완료합니다.
3. Claude: 호스트에서 `claude setup-token`을 실행하고 Settings → Claude → `Setup token`에 발급 토큰을 저장합니다.
4. Canvas에서 Prompt → `Local Subscription Agent`를 연결하고 ChatGPT 또는 Claude Code 모델을 선택합니다.

Compose 이미지는 두 CLI를 포함합니다. `docker compose run --rm api codex login --device-auth`로 로그인하면 세션이 `FRAMEFLOW_CODEX_AUTH_DIR`에 영속화되어 API와 Temporal Worker가 함께 사용합니다. Claude setup token은 Settings DB에 write-only로 저장되어 Worker 실행 직전에 `CLAUDE_CODE_OAUTH_TOKEN`으로 주입됩니다.

xAI Grok는 Settings → xAI에서 `XAI_API_KEY`를 등록한 뒤 기존 LLM Assistant, Skill Executor 또는 Script Generator의 Provider에서 `xAI`를 선택해 실행합니다. 신규 Draft Node는 xAI model family를 추가한 `@2` 계약을 사용하고, 기존 `@1` WorkflowVersion과 Draft는 그대로 유지합니다. 논리 별칭 `xai.text.quality`는 Run 시점의 `grok-4.6`으로 Snapshot하며 xAI가 권장하는 `prompt_cache_key`에는 Node request hash를 사용합니다. Imagine 이미지·영상 API는 텍스트 출력 계약과 다르므로 이 생성 인터페이스에 포함하지 않습니다.

1. `.env.example`을 `.env`로 복사합니다.
2. `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION`, 인증 방식을 설정합니다. API 최초 시작 시 Google/OpenAI/xAI 연결 값이 `provider_settings` 테이블로 자동 이관됩니다.
3. `GENERATION_PROVIDER_MODE`, `REFERENCE_PROVIDER_MODE`, `FORMAT_PROVIDER_MODE`, `SUBTITLE_ALIGNMENT_MODE`, `REFERENCE_ANALYSIS_MODE`가 `live`인지 확인하고 `VIDEO_DOWNLOADER_PROVIDER=yt-dlp`를 설정합니다. 음악 stem이 필요하면 `REFERENCE_AUDIO_SEPARATOR=demucs`와 `demucs` 실행 파일도 준비합니다.
4. Provider 결과를 반환하기 전에 `provider_request_id`, `provider_operation_id`, `request_hash`를 NodeRun에 저장합니다.
5. video operation은 제출과 완료를 분리하고 Reconciler가 operation ID로 재연결하게 합니다.

이관 이후 Provider 값은 `/settings`에서 관리하며 DB 값이 `.env`보다 우선합니다. OpenAI API Provider는 `OPENAI_API_KEY`와 필요에 따라 `OPENAI_BASE_URL`, `OPENAI_ORG_ID`, `OPENAI_PROJECT_ID`를 사용하고 xAI Grok는 `XAI_API_KEY`를 사용합니다. 로컬 구독 실행은 `CODEX_EXECUTABLE`, `CODEX_HOME`, `CLAUDE_CODE_EXECUTABLE`, `CLAUDE_CODE_OAUTH_TOKEN`을 사용합니다. fal.ai 연결은 서버 전용 `FAL_KEY`를 사용합니다.

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

외부 자격증명 없이 검증할 때는 테스트 스위트가 격리된 `fixture` Provider를 사용합니다. 애플리케이션 실행은 실데이터 모드에서 가짜 결과로 폴백하지 않습니다.

## Terraform

`infra/terraform`은 GCS, 분리된 서비스 계정과 Cloud SQL 기반만 준비합니다. Web/API/Worker 운영 배포는 아직 포함하지 않습니다.

```bash
cp infra/terraform/environments/dev.tfvars.example infra/terraform/environments/dev.tfvars
export TF_VAR_database_password='replace-with-a-generated-secret'
make tf-plan TF_ENV=dev
make tf-apply TF_ENV=dev
```

자세한 내용은 [`infra/terraform/README.md`](./infra/terraform/README.md)를 참고하세요.

## License

Copyright 2026 geusan. PolyForm Noncommercial License 1.0.0. 상업적 이용 문의는 저장소 소유자에게 별도 라이선스를 요청하세요.
