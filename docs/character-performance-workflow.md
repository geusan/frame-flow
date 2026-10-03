# 캐릭터 레퍼런스 영상 제작

캐릭터 Image와 연기 레퍼런스 Video를 입력해 동작 전사, 음성 추출, 목소리 변환,
원본 화면 자막 렌더와 최종 Audio 결합을 독립 Node로 실행한다.
Canvas 예시: `canvas_a6f90aaa4c6b4244a4`.

```text
Character Image + reference frame zero → Prompt → OpenAI aligned Image
OpenAI aligned Image + Video → performance_transfer → reference_captions → change_voice
Video → reference.decompose → reference_captions
Video → audio.extract → audio.voice_convert → change_voice → Final Video
```

## 계약과 책임

| Node | 입력 → 출력 | 실행 |
| --- | --- | --- |
| `video.performance_transfer@1` | `media.image.v1` + `media.video.v1` → `media.video.v1` | fal의 Kling 3.0 Pro Motion Control. 캐릭터 외형은 Image, 연기는 Video에서 가져오며 출력 음성은 제거한다. |
| `audio.extract@1` (기존) | Video → `media.audio.v1` | 첫 Audio stream을 재인코딩 없이 추출한다. |
| `audio.voice_convert@1` | Audio → Audio | ElevenLabs Speech to Speech. 지정 Voice ID로 발화·타이밍을 보존해 변환한다. |
| `video.reference_captions@1` | Video + `data.reference_analysis.v1` → Video | 분석된 화면 텍스트를 ASS/libass로 렌더한다. 대사 생성이나 음성 결합을 하지 않는다. |
| `video.change_voice@1` (기존) | Video + Audio → Video | 준비된 영상과 음성을 결합한다. |

세 신규 계약은 Manifest, Generic Inspector, Executor Registry로 등록된다.
기존 계약/Artifact/게시 Version의 의미는 변경하지 않는다.
Local 실행과 Temporal Activity는 동일 Registry와 `NodeExecutionResult`를 사용한다.
기존 generic Artifact 출력 Port의 실행 입력은 실제 Artifact type으로 구체화한다.
이는 `asset.select@2 → audio.extract@1` 연결에서 Video가 ReferenceAsset로 전달되던
호환 버그 수정이며 Node Definition digest는 변경하지 않는다.

## 설정과 결과

- 시작 구도 준비는 기존 `prompt.input@1`과 `image.generate@1`을 사용한다.
  캐릭터 사진은 identity/anatomy, 원본 첫 프레임은 framing/pose로 구분해 연결한다.
  OpenAI `gpt-image-2`의 custom size 지원을 사용해 9:16을 1152×2048로 전달한다.
  종전 1024×1536으로 고정되던 Provider Adapter의 비율 오류를 수정했다.
  구형 Image 모델의 제한된 size fallback은 유지하며 기존 Artifact는 수정하지 않는다.
- Motion: `prompt`, `character_orientation`, `timeout_seconds`.
  video orientation은 3–30초, image orientation은 3–10초 입력을 검증한다.
  H.264 driving video로 정규화하며 결과 길이가 원본과 600ms 넘게 다르면 실패한다.
  Provider 파일 업로드로 입력을 CDN URL로 전달하며 입력 파일은 24시간 만료를 요청한다.
  Kling upstream이 거절한 video data URI는 사용하지 않는다.
- Voice: `voice_id`, `stability`, `similarity_boost`, `seed`, `remove_background_noise`.
  실제 모델은 `eleven_multilingual_sts_v2`다. 길이 편차가 500ms를 넘으면 실패하고,
  허용 범위에서는 재생 속도 변경 없이 padding/trim으로 원본 길이에 맞춘다.
- Captions: font, 색상, outline, 텍스트/시간 override, 누락 track 추가,
  label box와 callout line을 설정한다. 분석 bbox는 출력 해상도에 맞춰 변환한다.
  원본의 단어·시점·배치를 재구성하며 원본 폰트 파일이나 픽셀을 복제하는 계약은 아니다.
- Manifest에서 허용한 필드만 Workflow input으로 노출된다.
  최종 Video를 Primary output으로 선언하면 이 결과의 조상 Node만 Publish된다.
  Sticky 제작 메모는 Annotation이며 실행 그래프에 포함되지 않는다.

Artifact schema는 `video.performance_transferred.v1`, `audio.voice_converted.v1`,
`video.reference_captioned.v1`이다. 입력 Artifact와 역할, normalized config,
Definition digest, exact model ID, Executor/FFmpeg revision과 Provider request ID를 기록한다.
일반 Config, Preview와 read-only Raw data는 기존 공통 상세 화면을 사용한다.

## Provider 작업의 재개와 비용

유료 요청 전 Experiment에 Provider checkpoint를 저장한다. fal의 알려진 request ID는
다시 submit하지 않고 status/result 조회로 재개한다. 요청 결과가 불명확한 pending 상태와
재조회가 지원되지 않는 ElevenLabs 응답 이후의 실패는 자동으로 재과금 요청을 만들지 않는다.
확실한 4xx 거절은 rejected로 기록하고 문제 해결 후 명시적 Node 재실행을 허용한다.
Queue status의 COMPLETED도 결과 조회에서 422 입력 오류를 반환할 수 있으므로 별도로
분류한다. 오류 응답의 echoed image/video 데이터는 로그에 포함하지 않는다.

Provider가 비용을 응답하지 않으면 `cost_status=provider_billed_unreported`로 기록한다.
API의 숫자 `cost_usd=0`은 청구액이 0이라는 뜻이 아니다. Library에는 Provider billed로 표시한다.
잔액 소진은 재시도 불가 오류와 충전 경로를 표시한다.

## 예시 캐릭터와 검증 경계

화이트·핑크 단발, 캐릭터 얼굴과 체형, 바스트를 지지하는 니트 형태를 고정한다.
원본의 몸·손·고개·눈·표정·입모양 타이밍은 약 15.954초 driving video에서 가져온다.
목소리는 `IbNtK9ck5SyXyxyjqHEN` (Tsuki)로 지정했다.
영어·일본어 화면 자막은 원본 프레임에서 실제 등장 시점을 확인해 보정했다.
노딸깍 Master Prompt와 개별 Canvas 설정은 `output/character-reference-video/`에 보관한다.

동작 전사는 생성형이므로 프레임 단위의 동일성을 보장하지 않는다.
실제 결과에서 얼굴·체형 일관성, 손가락/입모양, 음성 타이밍, 자막 충돌을 검수해야 한다.
2026-10-01 live 검수: 잔액 충전 후 생성과 자막·음성 결합이 성공했다.
첫 결과는 입력 사진과 원본의 구도·마이크 손이 달라 자막이 얼굴에 겹치고 마이크가
손에서 이탈하는 문제가 있었다. 이 결과를 실행 이력에 보존하고, 위의 시작 이미지
정렬 단계를 추가했다. 새 시작 이미지는 얼굴/체형과 왼쪽 배치, 마이크 그립, 빈 자막
공간을 시각 검수했다. 보정 영상의 2/6/10/14초 샘플에서 왼쪽 배치, 마이크를 든
같은 손의 유지, 자유로운 손의 가리키기 순서와 얼굴/머리 일관성을 확인했다.
생성형 동작의 크기와 미세한 표정은 원본과 완전히 동일하지 않을 수 있다.

최종 Artifact: `art_66127cc338a14d8e97`.
fal 영상 생성 2건은 각각 응답의 billable units가 16초이며 현재 단가 $0.168/초로
합계 $5.376이다. 첫 건은 로그인한 fal Usage 화면에서도 $2.688을 확인했다.
ElevenLabs 응답의 character-cost는 160이다. OpenAI 시작 이미지 1장과 레퍼런스
분석의 실청구액은 현재 Adapter에 token usage가 저장되지 않았고 비용 조회 API 권한도
없어 확인하지 못했다. 앱의 0달러 기록을 실제 무료로 해석하면 안 된다.
상세 관측값은 `output/character-reference-video/cost-report.json`에 보관한다.

자동 검증은 Provider normalized request, pending/resume, 오류와 비용 metadata,
Config/Port/digest, Artifact lineage, cache, Local/Temporal parity, 원본 Audio stream-copy,
자막 렌더, Publish 역방향 도달성·Annotation 제외를 다룬다.
