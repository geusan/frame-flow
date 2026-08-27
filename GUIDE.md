# Frameflow 개발·사용 가이드

이 문서는 최초 요구사항 이후 실제 코드에 반영된 기능과 현재 동작 범위를 정리한다. 기획상의 최종 목표가 아니라, 현재 저장소에서 실행하고 확인할 수 있는 상태를 기준으로 한다.

## 1. 프로젝트 개요

Frameflow는 레퍼런스 영상의 원본 자산을 생성 단계와 분리하고, 추출된 포맷과 새로운 Prompt를 이용해 이미지·영상·음성·자막·최종 영상을 제작하는 그래프 기반 도구다.

현재 프로젝트는 다음 두 영역으로 나뉜다.

1. Canvas 중심의 브라우저 편집기
2. Reference·Format·Run·Artifact를 관리하는 FastAPI/Temporal 기반 Control Plane

Canvas는 실제로 노드를 추가·연결·편집하고 Step 단위로 실행할 수 있다. 로컬 미디어 생성 결과는 deterministic SVG·MP4·WAV 파일로 만들어 MinIO에 저장되고 Canvas에서 표시·재생된다. 이 결과는 실제 Google 생성 결과가 아니며, Google Provider와 FFmpeg Timeline Worker는 별도 Adapter/Worker로 구현되어 있지만 Canvas 실행과 완전히 연결되지는 않았다.

## 2. 실행 방법

### Docker Compose

전체 로컬 스택을 실행한다.

```bash
docker compose up --build
```

접속 주소:

| 서비스 | 주소 |
| --- | --- |
| Web Canvas | <http://localhost:3001> |
| FastAPI 문서 | <http://localhost:8000/docs> |
| API 상태 | <http://localhost:8000/health> |
| Temporal UI | <http://localhost:8081> |
| MinIO Console | <http://localhost:9001> |

### Web/API 개별 실행

```bash
make setup
make dev-api
make dev-web
```

## 3. 주요 화면

| 화면 | 현재 역할 |
| --- | --- |
| Canvas | 그래프 생성·편집·Step 실행·결과 Preview |
| References | Reference 목록과 URL Metadata Inspect |
| Format Lab | FormatCore, Evidence, Beat, Diff 시각화 |
| Runs | Run 상태·비용·진행률 목록 |
| Models | 논리적 모델 별칭과 실제 모델 ID 표시 |

References의 Metadata Inspect를 제외한 일부 목록·필터·설정 UI는 아직 데모 데이터 기반이다.

## 4. Canvas 기본 사용법

### 4.1 새 Canvas 만들기

상단 `New` 버튼을 누르면 빈 Canvas가 만들어진다. 이름 입력란에서 Canvas 이름을 바꿀 수 있다.

빈 Canvas에서는 다음 방법으로 첫 Step을 추가한다.

- 화면 아래 `+` 버튼
- 빈 공간 더블클릭
- 왼쪽 Node Library 열기
- 이미지 복사 후 Canvas에서 `⌘V`

`Use starter workflow`를 누르면 고급 숏츠 파이프라인 예제가 배치된다.

### 4.2 Step 추가

하단 `+` 버튼을 누르면 검색 가능한 Step Picker가 열린다. 목록 항목을 클릭하면 화면 중앙 또는 더블클릭한 위치에 노드가 생성된다.

Node Library에서는 항목을 클릭하거나 Canvas로 드래그할 수 있다.

### 4.3 노드 연결

노드 오른쪽 출력 Handle을 다른 노드 왼쪽 입력 Handle로 드래그한다.

- 포트 타입이 다르면 연결되지 않는다.
- 단일 입력 포트는 한 개의 연결만 허용한다.
- `Video Generator.Image`와 `Video Editor.Video`는 여러 연결을 허용한다.
- 자기 자신으로 연결할 수 없다.
- 순환 연결은 Validate 단계에서 차단된다.

### 4.4 노드 편집

노드를 선택하면 오른쪽 Inspector가 열린다.

- 노드 이름
- 설명
- 모델
- 해상도
- 화면 비율
- 단일 출력 설정
- Video Editor 전환 방식과 목표 길이
- 입력 연결 상태
- 실행 횟수와 최근 결과

노드를 복제하거나 삭제할 수 있으며 `Delete`와 `Backspace` 키도 지원한다. Prompt 입력 중에는 삭제 키가 노드 삭제로 전달되지 않는다.

### 4.5 저장과 복구

Canvas 그래프는 브라우저 `localStorage`에 자동 저장된다.

- 노드 위치
- 노드 설정
- 연결선
- 실행 상태
- Mock 결과 Preview
- Canvas 이름

Undo·Redo를 지원하며 상단 초기화 버튼으로 Starter Workflow를 다시 불러올 수 있다.

업로드 파일의 `blob:` URL은 브라우저 세션 전용이다. 새로고침 후 실제 파일 내용을 복구하려면 Artifact Upload API와 연결해야 한다.

## 5. Prompt와 생성 노드 규칙

Prompt는 독립된 입력 노드다. 생성 노드 내부에는 별도 Prompt 입력창이 없다.

생성 노드를 실행하려면 다음 조건이 필요하다.

1. `Prompt` 포트가 연결되어 있어야 한다.
2. 연결된 Prompt에 내용이 있어야 한다.
3. 필수 상위 Step이 성공 상태여야 한다.

Prompt에 글자를 입력하면 별도 Run 없이 즉시 입력 준비 상태가 된다. 한글 입력은 IME `compositionstart/compositionend`를 처리해 자모가 분리되지 않는다.

Prompt를 수정하면 직접 연결된 기존 생성 결과는 무효화되고 다시 실행 가능한 상태로 바뀐다.

## 6. 현재 제공되는 노드

### 6.1 Quick

| 노드 | 필수 입력 | 선택 입력 | 출력 | 설명 |
| --- | --- | --- | --- | --- |
| Prompt | 없음 | 없음 | `Prompt` | 다음 생성 Step에 전달할 텍스트 |
| Image Generator | `Prompt` | `ReferenceAsset` | `Image` | 이미지 한 장 생성 |
| Video Generator | `Prompt` | `Image × N`, `ReferenceAsset` | `Video` | 단일 영상 생성 |
| Voiceover | `Prompt` | 없음 | `Audio` | Prompt를 음성으로 생성 |
| LLM Assistant | `Prompt` | 없음 | `Text` | Prompt 분석·변환 |

Folder 노드는 현재 목록에서 숨겨져 있다. Canvas 내부의 하위 Canvas 기능이 필요해질 때 다시 도입한다.

### 6.2 References

| 노드 | 입력 | 출력 | 설명 |
| --- | --- | --- | --- |
| Upload | 로컬 파일 | `ReferenceAsset` | 이미지·영상·오디오 파일 선택 |
| Assets | 저장 Asset 한 개 | `ReferenceAsset` | 업로드 Asset 또는 크롤링 Reference 하나 선택 |

Assets는 현재 한 번에 하나의 Reference만 선택한다. ReferenceSet을 Canvas 생성 입력으로 직접 사용하지 않는다.

이미지를 다른 앱에서 복사한 뒤 Canvas에서 `⌘V`를 누르면 마우스 위치에 Upload 노드가 생성되고 Preview와 `ReferenceAsset` 출력이 설정된다. 일반 텍스트 붙여넣기는 Prompt 입력으로 유지된다.

### 6.3 Image/Video

| 노드 | 입력 | 출력 | 설명 |
| --- | --- | --- | --- |
| Image Generator | `Prompt`, 선택 `ReferenceAsset` | `Image` | 단일 이미지 생성 |
| Video Generator | `Prompt`, 선택 `Image × N`, 선택 `ReferenceAsset` | `Video` | 단일 영상 생성 |
| Video Editor | `Video × N` | `Video` | 여러 영상을 하나로 편집 |

Video Editor 설정:

- Hard cut
- Crossfade
- Match cut
- Dip to black
- 출력 비율 9:16, 1:1, 16:9
- 목표 길이 15, 30, 45, 60초

여러 Video 연결은 Edge 생성 순서로 편집 순서가 결정된다. 현재 별도 Drag reorder UI는 없다.

### 6.4 Audio

| 노드 | 필수 입력 | 출력 | 설명 |
| --- | --- | --- | --- |
| Voiceover | `Prompt` | `Audio` | 음성 생성 |
| Change Voice | `Video` | `Video` | 생성된 영상의 음성 교체 |
| Translate | `Video` | `Video` | 생성된 영상의 음성과 자막 번역 |

### 6.5 Utilities

| 노드 | 출력 | 설명 |
| --- | --- | --- |
| Text | `Text` | Canvas 메모 또는 텍스트 전달 |
| Sticky Note | 없음 | 실행과 무관한 시각 메모 |

Utilities 노드는 Run 대상이 아니다.

## 7. 권장 Canvas 흐름

### 단일 Reference 기반 생성

```text
Prompt ────────────────┐
Upload 또는 Assets ────┴→ Image Generator → Image
                                         │
Prompt ──────────────────────────────────┴→ Video Generator → Video
                                                                    │
                                                                    ├→ Translate → Video
                                                                    └→ Change Voice → Video
```

### 여러 이미지로 영상 생성

```text
Prompt A → Image Generator A → Image ─┐
Prompt B → Image Generator B → Image ─┼→ Video Generator → Video
Prompt C → Image Generator C → Image ─┘          ▲
                                                  │
                                             Video Prompt
```

### 여러 영상을 한 번에 편집

```text
Video Generator A → Video ─┐
Video Generator B → Video ─┼→ Video Editor → Video → Translate
Video Generator C → Video ─┘                  └→ Change Voice
```

## 8. Step 실행

### 단일 Step

- 노드 안 `Run`
- 노드 더블클릭
- Inspector의 `Run this step`

필수 입력이 없으면 Run 버튼이 비활성화되고 Inspector에 원인이 표시된다.

생성 노드의 단일 실행은 FastAPI `Experiment` 계약을 사용한다. 실행할 때마다 다음 값이 변경 불가능한 Snapshot으로 저장된다.

- 원본 Prompt 문자열
- 논리 모델 별칭과 정확한 모델 ID
- 해상도·화면비·길이 등 생성 파라미터
- 연결된 입력 노드와 Artifact ID
- 요청 해시, 비용, 실행 시간, 결과 Artifact

동일한 입력 Snapshot은 기존 결과를 캐시로 재사용하지만 새로운 이력 항목을 남긴다. Inspector의 `Experiment history`에서 실행별 Prompt와 모델을 비교하고 성공 실행 하나를 Baseline으로 지정할 수 있다.

### 전체 Workflow

상단 `Run workflow`를 누르면 다음 검사를 수행한다.

- 필수 입력 연결
- 포트 타입
- 빈 Prompt
- 순환 연결
- 예상 비용

검증을 통과하면 위상 정렬 순서대로 Step을 실행한다. Stop으로 중단할 수 있다.

## 9. Canvas 결과 Preview

현재 Canvas는 생성 노드의 결과를 단일 Experiment API에서 받아 노드 안에 표시한다. Image Generation은 SVG, Video Generation은 오디오를 포함한 H.264 MP4, Audio Generation은 24kHz WAV를 생성해 Object Storage에 저장한다. 기타 compose·logic 노드는 아직 로컬 Preview 실행을 사용한다.

| 결과 | Preview |
| --- | --- |
| Image | 이미지 카드 |
| Video | 영상 Poster와 재생 표시 |
| Upload Video | 브라우저 Video Player |
| Audio | Waveform 또는 Audio Player |
| Text | 텍스트 Preview |
| JSON/Spec | JSON Preview |

중요: 기본 Experiment 실행 모드는 요청 해시로 고정되는 `deterministic` 미디어다. 파일은 실제로 저장되고 재생되지만 콘텐츠는 로컬 테스트용이다. 실제 Gemini Image, Veo, Gemini-TTS Adapter 코드는 존재하나 단일 Experiment Executor의 운영 Provider로는 아직 연결되지 않았다. 이 구분은 Experiment 이력의 `execution_mode`에 기록된다.

Video Editor도 현재 설정·다중 입력 검증·Mock 결과까지 동작하며, FFmpeg Timeline 합성은 Canvas 실행과 아직 연결되지 않았다.

### Object Storage

로컬 기본 Provider는 MinIO다. Artifact 본문은 불변 Object Key에 저장되며 PostgreSQL에는 URI, SHA-256, MIME, 크기와 Storage Provider가 기록된다. Canvas가 사용하는 `/artifacts/{id}/content` URL은 API가 매 요청마다 Signed GET URL로 연결하므로 브라우저 저장 데이터에 만료된 서명을 남기지 않는다.

`STORAGE_PROVIDER`로 `memory`, `minio`, `r2`, `s3` 중 하나를 선택할 수 있다. MinIO는 필요한 버킷을 자동 생성하며 R2/S3 버킷은 배포 전에 생성한다. 브라우저 직접 업로드를 위한 `/artifacts/upload-url`도 실제 Signed PUT URL을 반환한다.

## 10. Reference와 권리 격리

Reference는 기본적으로 분석 전용이다.

- `analysis_only`, `unknown`은 생성 입력 권한이 강제로 꺼진다.
- Reference Analyzer와 Generation Worker의 서비스 계정을 분리한다.
- Generation Worker에는 Reference 원본 버킷 읽기 권한을 부여하지 않는다.
- 직접 생성 입력은 승인된 `ReferenceAsset` 단위로만 연결하는 방향이다.

Canvas Assets는 현재 단일 Reference 선택 UX다. 향후 Collection 병렬 실행은 다음 방식으로 확장한다.

```text
Reference Collection
→ ReferenceAsset별 Fan-out
→ 독립 Run 병렬 실행
→ 결과 수집
```

Collection 자체를 생성 노드에 직접 전달하지 않고 실행 계획이 단일 Asset 작업으로 확장한다.

## 11. 백엔드 구현

### FastAPI

현재 제공되는 API 영역:

- Reference Inspect·Import·List
- ReferenceSet 생성
- ExtractionRecipe 생성
- Format 추출·조회·Variant·Merge
- GenerationBrief·GenerationRun
- Run 조회·취소·SSE Event
- Node Retry·Regenerate·Fork·Select
- Artifact 조회·Upload URL·Download URL
- Model Registry 조회

OpenAPI 문서는 `/docs`와 `/openapi.json`에서 확인한다.

### Temporal

`EXECUTION_BACKEND=temporal`일 때 실제 Temporal Workflow와 Activity Worker를 사용한다.

```text
READY
→ RUNNING
→ WAITING_INPUT
→ candidate_selected Signal
→ RUNNING
→ SUCCEEDED
```

Worker가 중지된 동안 시작된 Run과 Candidate Signal이 보존되고 재시작 후 완료되는 시나리오를 검증했다.

### Provider Adapter

- Gemini Structured Output
- Gemini Image
- Veo Video operation submit/poll
- Gemini-TTS
- Mock Google Provider
- yt-dlp Reference Ingest Adapter

Workflow는 논리적 모델 별칭을 사용하고 Run에서 정확한 모델 ID를 Snapshot한다.

### Media Worker

- FFmpeg 기반 세로형 MP4 렌더
- ffprobe Metadata/QC
- 해상도·길이·오디오·Pixel Format 검사
- Provenance Manifest 생성

## 12. 데이터·스키마

주요 JSON Schema:

- `format.core.v1`
- `generation.spec.v1`
- `timeline.v1`

주요 엔티티:

- ReferenceAsset
- ReferenceSet
- FormatProfile
- FormatVariant
- GenerationBrief
- Run
- NodeRun
- Artifact
- AuditEvent

Artifact는 불변 객체로 취급한다. 재생성 시 기존 결과를 덮어쓰지 않고 새로운 ID와 Hash를 만든다.

## 13. 개발 검증

전체 검사:

```bash
make check
```

포함 항목:

- ESLint
- TypeScript
- Next.js Production Build
- FastAPI Contract Test
- Format Merge·Variation Test
- Budget Compile Test
- Candidate WAITING_INPUT/Resume Test
- Temporal Worker 복구 검증
- URL 권리·SSRF Test
- FFmpeg Golden Render/QC Test
- Docker 이미지 빌드
- Terraform validate

## 14. 주요 코드 위치

| 영역 | 파일 |
| --- | --- |
| Canvas UI·실행 | `apps/web/src/components/views/generation-canvas.tsx` |
| Canvas 노드·포트·검증 | `apps/web/src/lib/canvas-model.ts` |
| 공통 Web 타입 | `apps/web/src/lib/types.ts` |
| FastAPI | `apps/api/app/main.py` |
| DB 모델 | `apps/api/app/database.py` |
| 실행 계획 Compiler | `apps/api/app/compiler.py` |
| Demo 실행 엔진 | `apps/api/app/service.py` |
| Temporal Workflow | `apps/api/app/temporal_workflow.py` |
| Temporal Activity | `apps/api/app/temporal_activities.py` |
| Google Provider | `apps/api/app/providers_google.py` |
| Reference Ingest | `apps/worker/worker/ingest.py` |
| FFmpeg Worker | `apps/worker/worker/media.py` |
| JSON Schema | `packages/schemas/` |
| 인프라 | `infra/terraform/` |

## 15. 현재 남은 작업

우선순위가 높은 미완성 항목:

1. Canvas Step Run을 FastAPI/Temporal NodeRun과 연결
2. Google Provider 실제 자격증명 기반 생성
3. Upload와 Assets를 Artifact API 및 Reference Library와 연결
4. Video Editor를 Timeline JSON·FFmpeg Render와 연결
5. 연결된 Video의 순서 변경·Trim·삭제 UI
6. Canvas 정의를 DB의 WorkflowDefinition/Version으로 저장
7. Run Inspector를 실제 Canvas Run과 연결
8. Reference Collection Fan-out 실행
9. 인증·Workspace 데이터 격리·관측성 운영 설정

현재 상태는 편집 가능한 Canvas와 MinIO 기반 실제 미디어 저장·재생 경로를 갖춘 MVP지만, 콘텐츠 생성·편집은 아직 deterministic 실행과 실제 Provider/Worker 사이의 통합 작업이 남아 있다.
