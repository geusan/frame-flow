# Frameflow 개발·사용 가이드

이 문서는 최초 요구사항 이후 실제 코드에 반영된 기능과 현재 동작 범위를 정리한다. 기획상의 최종 목표가 아니라, 현재 저장소에서 실행하고 확인할 수 있는 상태를 기준으로 한다.

## 1. 프로젝트 개요

Frameflow는 레퍼런스 영상의 원본 자산을 생성 단계와 분리하고, 추출된 포맷과 새로운 Prompt를 이용해 이미지·영상·음성·자막·최종 영상을 제작하는 그래프 기반 도구다.

현재 프로젝트는 다음 두 영역으로 나뉜다.

1. Canvas 중심의 브라우저 편집기
2. Reference·Format·Run·Artifact를 관리하는 FastAPI/Temporal 기반 Control Plane

Canvas는 실제로 노드를 추가·연결·편집하고 Step 단위로 실행할 수 있다. 이미지·음성·텍스트 생성은 Google Gemini 또는 OpenAI 모델을 선택할 수 있고, 영상 생성은 Veo를 사용한다. 생성 결과는 MinIO에 저장한다. Video Editor, 오디오 교체, 자막 생성, Timeline 합성, 최종 렌더와 QC는 입력 Artifact를 읽는 로컬 FFmpeg/ffprobe 실행 경로에 연결되어 있다.

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
| `/workflows` | DB에 저장된 Canvas 목록과 새 Canvas 생성 |
| `/workflows/{id}` | 그래프 편집·Step 실행·결과 Preview |
| `/asset/images` | Image Artifact 목록과 lineage |
| `/asset/videos` | Video Artifact 목록·장면 검색·프레임 캡처 |
| `/runs` | Run 상태·비용·진행률 목록 |
| `/settings` | Google/OpenAI Provider 연결 정보 관리 |
| `/settings/models` | 논리적 모델 별칭과 실제 모델 ID 표시 |

References와 Format Lab의 독립 화면은 제거되었으며 관련 분석 계약은 기존 Backend 호환을 위해 유지한다. Provider 설정은 최초 시작 시 `.env` 값을 DB로 자동 이관한 뒤 DB를 기준으로 동작한다.

## 4. Canvas 기본 사용법

### 4.1 새 Canvas 만들기

상단 `New` 버튼을 누르면 빈 Canvas가 만들어진다. 이름 입력란에서 Canvas 이름을 바꿀 수 있다.

빈 Canvas에서는 다음 방법으로 첫 Step을 추가한다.

- 화면 아래 `+` 버튼
- 빈 공간 더블클릭
- 왼쪽 Node Library 열기
- 이미지 복사 후 Canvas에서 `⌘V`

Canvas에는 샘플 Workflow가 자동으로 삽입되지 않는다. 저장된 실제 Asset과 Format을 선택하고 필요한 Prompt·생성·편집 노드를 추가해 구성한다.

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

Image Generator, Video Generator, Voiceover, LLM Assistant와 Script Generator는 Inspector에서 Provider와 Model을 각각 선택한다. Image·Audio·Text는 Google/OpenAI를 지원하고 Video는 현재 Google Veo를 지원한다. Provider를 바꾸면 해당 Provider의 첫 번째 호환 모델로 자동 전환되며 기존 출력과 하위 Step은 무효화된다.

노드를 복제하거나 삭제할 수 있으며 `Delete`와 `Backspace` 키도 지원한다. Prompt 입력 중에는 삭제 키가 노드 삭제로 전달되지 않는다.

### 4.5 저장과 복구

Canvas 목록과 그래프는 PostgreSQL의 `canvases` 테이블에 자동 저장된다. 브라우저 `localStorage`는 API 저장 실패에 대비한 Canvas별 로컬 백업에만 사용한다. 이전 단일 `frameflow.canvas.v2` 데이터는 실제 사용자 그래프인 경우 첫 Canvas 목록 진입 시 DB로 한 번 이관되며, 과거 샘플 그래프는 이관하지 않는다.

- 노드 위치
- 노드 설정
- 연결선
- 실행 상태
- 실행 결과와 Artifact Preview
- Canvas 이름

Undo·Redo를 지원하며 상단 초기화 버튼으로 Starter Workflow를 다시 불러올 수 있다.

Upload 노드와 클립보드 이미지는 Artifact Upload API에 저장되며 새로고침 후에도 Content URL로 복구된다. 이전 버전에서 저장된 `blob:` URL 출력은 마이그레이션 과정에서 제거된다.

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
| Upload | 로컬 파일 또는 영상 URL | `ReferenceAsset` | 이미지·영상·오디오 파일 선택, 공개 영상 URL 가져오기 |
| Assets | 저장 Asset 한 개 | `ReferenceAsset` | 미니 Popover에서 저장된 이미지·비디오 하나 선택 |

사이드바의 Asset Library는 저장된 이미지와 비디오를 탭·검색·미리보기로 모아 보여준다. 비디오 플레이어에서 원하는 위치로 이동한 뒤 `Capture frame`을 누르면 해당 시점의 JPEG가 새 Image Artifact로 저장된다. `Prompt search`는 Google 또는 OpenAI Provider와 논리적 모델 별칭을 선택할 수 있다. 영상을 샘플링한 뒤 선택한 Vision 모델이 Prompt 관련도를 평가해 후보 썸네일·점수·타임스탬프를 반환한다. 후보를 누르면 플레이어가 해당 위치로 seek하며 선택 장면을 캡처할 수 있다. 캡처 이미지는 원본 Video Artifact ID, 정확한 타임스탬프, 검색 Prompt·점수·Provider·논리 모델·정확한 모델 ID와 FFmpeg 작업 버전을 lineage로 보존한다. Canvas의 Assets 노드는 같은 목록을 축소한 Popover를 열며, 이미지/비디오 탭에서 한 개를 선택해 해당 노드 출력으로 사용한다. ReferenceSet을 Canvas 생성 입력으로 직접 사용하지 않는다.

이미지를 다른 앱에서 복사한 뒤 Canvas에서 `⌘V`를 누르면 마우스 위치에 Upload 노드가 생성되고 Preview와 `ReferenceAsset` 출력이 설정된다. 공개 영상 URL을 Canvas 빈 영역에 붙여넣어도 Upload 노드가 생성되고 Video Downloader Adapter로 영상을 내려받아 Artifact로 저장한다. 현재 기본 Adapter는 `yt-dlp`다. Upload 노드의 URL 입력란에서는 URL을 붙여넣는 즉시 가져오기를 시작한다. 그 밖의 일반 텍스트 붙여넣기는 Prompt 입력으로 유지된다.

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
| Translate Video | `Video` | `Video` | Chirp 3 인식, Gemini 번역·TTS와 자막 Mux |

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

검증을 통과하면 Canvas 그래프와 NodeRun이 PostgreSQL에 저장되고 Worker가 실행을 담당한다. 같은 의존성 단계의 노드는 병렬 실행되며, 브라우저는 `/canvas-runs/{id}/events` SSE를 구독해 각 노드 상태와 결과를 실시간 반영한다. 활성 Run ID는 Canvas 로컬 상태에 보존되어 새로고침 후 다시 구독할 수 있고 Stop은 서버 Run과 Temporal Workflow를 취소한다.

## 9. Canvas 결과 Preview

현재 Canvas는 생성·편집 노드의 결과를 단일 Experiment API에서 받아 노드 안에 표시한다. Image Generation은 SVG, Video Generation은 오디오를 포함한 H.264 MP4, Audio Generation은 24kHz WAV를 생성해 Object Storage에 저장한다. Compose·Logic 노드도 API 실행 이력과 입력/출력 Artifact Lineage를 남긴다.

| 결과 | Preview |
| --- | --- |
| Image | 이미지 카드 |
| Video | 영상 Poster와 재생 표시 |
| Upload Video | 브라우저 Video Player |
| Audio | Waveform 또는 Audio Player |
| Text | 텍스트 Preview |
| JSON/Spec | JSON Preview |

중요: 운영 기본값은 `google-live.v1`이며 자격증명이나 Provider 설정이 없으면 Step이 실패한다. Translate Video는 `google-localization.v1`, Speech Subtitle은 `google-speech.v1`, 로컬 편집은 `local-media.v1`로 실행되고 이 구분은 Experiment 이력의 `execution_mode`에 기록된다. `fixture-media.v2`는 테스트에서만 활성화된다.

Video Editor는 연결된 Video Artifact를 실제로 디코딩·정규화하고 Hard cut, Crossfade, Dip to black과 목표 길이를 적용해 새 MP4 Artifact를 만든다. Replace Audio는 Video의 오디오 스트림을 연결된 Audio로 교체한다. Translate Video는 60초 이하 영상에서 음성을 추출하고 Chirp 3로 언어·세그먼트 타임스탬프를 인식한 뒤, Gemini가 세그먼트를 보존해 번역하고 Gemini-TTS가 번역 음성을 생성한다. Transcript, 번역문, WAV, SRT와 최종 MP4는 각각 Artifact로 저장된다. Timeline Compose, Render와 QC도 각각 실제 Timeline JSON, H.264/AAC MP4와 ffprobe 검사 결과를 저장한다.

Upload 노드, 클립보드 이미지와 URL 영상은 최대 250MB까지 불변 Artifact로 저장된다. URL 영상은 10분 이하의 공개 HTTP(S) 소스만 허용하며 사설·루프백·링크 로컬 주소는 차단한다. 따라서 새로고침 후에도 `blob:` URL이 아니라 Artifact Content URL로 미디어를 다시 불러올 수 있다. Candidate Select는 고정 카드 대신 연결된 실제 Video Artifact만 표시하고 선택 결과를 다음 노드로 전달한다.

Artifact Content API는 HTTP byte-range 응답을 지원한다. 따라서 브라우저 비디오 플레이어가 전체 파일을 다시 받지 않고 원하는 시점으로 seek할 수 있으며, 현재 재생 위치를 millisecond 단위로 Frame Capture API에 전달한다.

URL 영상 다운로드는 `VideoDownloaderAdapter` 계약과 provider registry를 통한다. `VIDEO_DOWNLOADER_PROVIDER`의 기본값은 `yt-dlp`이며, 실행 파일 경로는 `YT_DLP_EXECUTABLE`로 바꿀 수 있다. 새 provider는 `inspect`와 `download` 계약을 구현하고 registry에 등록하면 Reference 수집과 Canvas URL 업로드에서 같은 방식으로 선택할 수 있다. 사용된 provider 이름은 Artifact metadata와 audit event에 기록된다.

`yt-dlp`는 `curl_cffi` 네트워크 extra를 포함해 설치한다. TikTok처럼 TLS fingerprinting을 사용하는 도메인은 `YT_DLP_IMPERSONATE_DOMAINS`에 포함된 경우에만 `YT_DLP_IMPERSONATE_TARGET`(기본 `chrome`)을 적용한다. 전역 impersonation은 다운로드 안정성과 성능에 영향을 줄 수 있어 기본적으로 사용하지 않는다.

Artifact 파생관계는 `artifact_edges` 테이블에 부모·자식·역할·순서·작업 ID로 정규화된다. `/artifacts/{id}/lineage`는 조상·후손·양방향 그래프를 반환하며 Asset 상세 Drawer에서 생성 설명, Prompt, 모델, 파라미터, Before/After와 전체 lineage를 확인한다. `SCENE_SEARCH_PROVIDER_MODE=live`는 Gemini Vision을 사용하고 테스트에서만 `fixture` 모드를 허용한다.

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
- Canvas DAG Run 생성·조회·취소·SSE·Candidate Select
- Node Retry·Regenerate·Fork·Select
- Artifact 조회·Upload URL·Download URL
- Model Registry 조회

OpenAPI 문서는 `/docs`와 `/openapi.json`에서 확인한다.

### Temporal

`EXECUTION_BACKEND=temporal`일 때 일반 Generation Workflow와 Canvas DAG Workflow 모두 실제 Temporal Activity Worker를 사용한다. Canvas Workflow는 의존성이 충족된 노드들을 한 Wave로 묶어 동시에 Activity로 스케줄한다.

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
- Chirp 3 Speech-to-Text와 Gemini 기반 Translate Video
- OpenAI Responses API, ChatGPT Latest, GPT Image 2, GPT-4o Mini TTS
- 테스트 전용 Fixture Provider
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
| Local 실행 엔진 | `apps/api/app/service.py` |
| Temporal Workflow | `apps/api/app/temporal_workflow.py` |
| Temporal Activity | `apps/api/app/temporal_activities.py` |
| Canvas Run Engine | `apps/api/app/canvas_runs.py` |
| Canvas Temporal Workflow | `apps/api/app/canvas_temporal.py` |
| Canvas Temporal Activity | `apps/api/app/canvas_activities.py` |
| Google Provider | `apps/api/app/providers_google.py` |
| OpenAI Provider | `apps/api/app/providers_openai.py` |
| Reference Ingest | `apps/api/app/reference_ingest.py` |
| Format Extraction | `apps/api/app/format_extraction.py` |
| FFmpeg Worker | `apps/worker/worker/media.py` |
| JSON Schema | `packages/schemas/` |
| 인프라 | `infra/terraform/` |

## 15. 현재 남은 작업

우선순위가 높은 미완성 항목:

1. Veo 장기 operation ID의 프로세스 재시작 후 Reconcile
2. 연결된 Video의 순서 변경·구간 Trim·삭제 UI
3. Canvas 정의를 DB의 WorkflowDefinition/Version으로 저장
4. 일반 Generation Run 상세 Inspector
5. Reference Collection Fan-out 실행
6. 인증·Workspace 데이터 격리·관측성 운영 설정

현재 상태는 편집 가능한 Canvas, 실제 Google 생성·Reference 분석·Format 추출·영상 번역, MinIO 기반 미디어 저장·재생과 로컬 FFmpeg 편집·렌더·QC 경로를 갖춘 MVP다. 자동화 테스트를 제외한 애플리케이션 경로는 Fixture 결과로 폴백하지 않는다.
