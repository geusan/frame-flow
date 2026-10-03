# MiniMax H3 참조 영상 워크플로우

`video.reference_generate@1`은 이미지·영상·오디오 참조와 Prompt를 하나의
Video로 변환하는 Atomic Workflow Node다. 조합/자막/립싱크/오디오 결합은 별도
Node로 유지한다. Canvas-only 요소나 Provider 이름을 넣은 새 Node key가 아니다.

## 공급사 여유 프레임을 보존하는 @2

2026-10-02 실제 MiniMax-H3 4초 요청이 107프레임/24fps(4.458333초) 영상과
4.459초 오디오를 반환했다. 공급사 task/usage는 요청 길이 4초로 보고했다.
`@1`의 ±250ms 검사와 기존 Definition은 유지하고, `@2`는 공급사 원본에
최대 1초의 추가 여유 프레임을 허용하는 별도 계약이다. 짧은 결과는 기존 -250ms
한계를 유지한다. 자르거나 속도를 변경하지 않고 후속 `video.segment`가 정확한
편집 길이를 결정한다. 출력 schema는 `video.reference_generated.v2`이며 요청 길이,
실제 영상/컨테이너 길이와 `provider_padding_ms`를 기록한다.

Draft는 같은 Config/Binding/Port를 유지하면서 version과 digest를 명시적으로
교체해야 한다. Diff와 여유 프레임 경고를 저장하고 새 Publish를 요구한다.
이전 Version/Run/Artifact는 수정하지 않는다. 최초 실패 작업의 완료된 공급사 파일은
다시 생성하지 않고 별도의 불변 Video authoring asset으로 복구해 사용한다.

## 계약

- Provider/model: MiniMax 공식 V2 API, `minimax.video.h3` → `MiniMax-H3`.
- Config: `resolution` (`768P`, `2K`, 기본 `2K`), `duration_seconds` (정수 4–15,
  기본 4), `aspect_ratio` (기본 9:16), `timeout_seconds` (기본 1200).
- 앞 세 Config는 workflow input으로 노출할 수 있다. 인증/작업 ID는 Config에 넣지 않는다.
- Port: `prompt.text.v1`, 필수 다중 `media.image.v1`, 선택 다중 `media.video.v1`,
  선택 다중 `media.audio.v1` → `media.video.v1`.
- 각 모달리티의 참조 순서는 들어오는 Edge 순서다. 동일 ID 중복은 첫 출현으로 통일한다.
  정규화된 Artifact ID 배열을 출력 metadata에 저장한다.
- 이미지 1–9장, 영상/음성 각 최대 3개, 합계 최대 12개. PNG/JPEG/WEBP 이미지,
  H.264/H.265 MP4/MOV, WAV/MP3 음성을 검증한다. 영상/음성은 파일당 2–15초,
  모달리티별 합계 15초 이하. 그림/영상은 256–5760px, 종횡비 0.4–2.5다.
- 직접 data URI를 사용하며 JSON body 64MB, 파일별 이미지 30MB/영상 50MB/
  음성 15MB 제한을 제출 전에 검사한다. 큰 입력은 명시적인 앞 단계에서 줄여야 한다.
- H3의 reference 모드다. 시작 이미지 참조는 외모/장면 기준이며 첫 프레임 픽셀 일치는
  이 계약의 의미가 아니다. 기존 Google `video.animate_image@1`는 그대로 유지한다.
- 출력: `Video`, `video.reference_generated.v1`. H3 native audio를 보존한다.
  고정된 ElevenLabs 음성은 구간 추출/립싱크 뒤 별도 최종 mux로 결합한다.
- Lineage: `identity_appearance_reference`, `motion_reference`, `speech_reference`.
  Definition digest, normalized config, Executor/FFmpeg revision, exact model,
  task ID, usage, 순서가 있는 참조 ID들을 기록한다. 입력 미디어/data URI는 로그에 남기지 않는다.

## 실행/오류/비용

Local과 Temporal은 공통 Registry dispatch를 사용한다. 제출 전에 pending checkpoint를
남기고 task ID를 즉시 저장한다. 조회/다운로드 중단은 같은 ID로 재개한다. 불명확한
제출 결과는 자동 재제출하지 않는다. 명확한 입력/인증/잔액 거절은 rejected로 기록한다.
입력 범위 오류는 Provider 호출 전에 실패한다. 출력은 유효한 Video인지와 요청 길이
대비 250ms 이내인지 확인하고 불변 Artifact로 저장한다.

Provider가 반환한 사용량을 기록하되 청구액을 추측하지 않는다.
`cost_status=provider_billed_unreported`인 경우 기존 숫자 cost 필드의 0은 무료가 아니다.
공통 비용 원장은 공식 H3 가격표에 따라 공급사 usage의 출력 초와 참조 영상 입력 초,
5장을 넘는 참조 이미지를 계산한다. 768P는 $0.08/초, 2K는 $0.13/초이며 초과 이미지는
$0.04/장, 참조 음성은 무료다. 결과 파일의 여유 프레임은 계산에 넣지 않는다.
이 값은 `calculated`(사용량 × 공개 요금표)로 표시하고 공급사 확정 청구액과 구분한다.
사용량이 빠졌거나 다른 task type이면 미확정으로 남긴다. Run/Artifact snapshot은
다시 쓰지 않고 원장 관측 이력을 통해 비용 조회를 갱신한다.
Fixture도 동일 Artifact/NodeExecutionResult 계약과 lineage를 사용하고 fixture임을 명시한다.

## 비교 Canvas

기존 캐릭터, 깨끗한 장면 이미지, 원본 레퍼런스 영상, Tsuki 전체 음성, 자막 분석,
최종 Veo 비교 결과를 새 Draft에서 재사용한다. 미디어는 불변 Artifact source이며
자막 분석은 원본 영상에 연결된 완료된 분석 Node와 Artifact를 함께 복제한다.
원본 18.879초는 기존 24fps 문장 경계 `[0,78,156,245,325,391,453]`로 분리한다.
각 H3 요청은 최소 길이인 4초로 설정하고 생성 후 해당 발화 길이로 추출한다.
기존 립싱크/자막/전체 음성 결합 흐름으로 18.875초 비교 영상을 만들 수 있게 연결한다.
설정 작업에서는 유료 생성 요청을 제출하지 않는다.

설정한 Canvas: `canvas_e7242d1ff55e48ce9a`, Workflow Draft:
`workflow_9379adc1340548ccaa`. 실제 6개 입력의 포맷·길이·용량과 요청 규격을
사전 검증했으며 유료 H3/립싱크 생성 횟수는 0이다. 원본 영상이 음성보다 짧아
마지막 참조 구간에만 1/24초 end padding을 명시했다.

## 검증 및 근거

Manifest/digest/default/binding, 모델 catalog와 Generic Inspector 경로, 참조 순서와
요청 hash, 파일 제약, task 재개/중복 제출 방지, CDN 인증 헤더 분리, Artifact/lineage,
Local/Temporal parity와 cached replay, Publish 도달성/Annotation 제외를 테스트한다.

- [MiniMax V2 생성 API](https://platform.minimax.io/docs/api-reference/video-generation-v2-create)
- [작업 조회](https://platform.minimax.io/docs/api-reference/video-generation-v2-query)

기존 Definition/WorkflowVersion/Run/Artifact의 in-place migration은 하지 않는다.
