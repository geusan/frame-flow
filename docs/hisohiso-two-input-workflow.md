# 히소히소: 일본어·한국어 두 입력으로 릴스 만들기

사용자는 문장별로 27개 그래프를 복제하는 방식을 원하지 않는다. 하나의 Workflow에서 `japanese`와 `korean` 입력을 바꿔 매번 MP4 하나를 생성한다. 이미지와 음성 파일을 미리 만들거나 구간 길이를 계산할 필요가 없다.

- Canvas: `canvas_3e7de1a2d0dd4543b9`
- Workflow: `workflow_346ced61574e4f22bc`
- 원본 27개 복제 그래프는 Published v1 이력으로 보존한다.
- 입력 길이: 일본어 1–180자, 한국어 1–240자. 긴 문장으로 발음/장면 길이 한도를 넘으면 잘라내지 않고 오류를 반환한다.

## 역할과 계약

| 단계 | 계약 | 책임 |
| --- | --- | --- |
| 단어 선정 | 기존 `llm.assistant@2` | 일본어 문장에 실제로 있는 빈칸 단어, 읽기, 사전형, 한국어 단어 뜻을 JSON으로 준비 |
| 화면 | `image.study_screen@1` × 빈칸/정답 | 입력 문장을 보존하는지 검증하고 실제 Flutter 앱 위젯을 PNG로 렌더 |
| 발음 | 기존 `tts.generate@1` | 일본어 문장 한 번 발음 |
| 연습 음성 | `audio.practice_track@1` | 발음과 고정 비트의 배치. Audio + `practice.timing.v1` 결과 |
| 길이 변환 | `image.practice_motion@1` × 빈칸/정답 | 음성 타이밍을 기존 `image.motion.v4` 정지 Motion으로 변환 |
| 장면 | 기존 `video.frame_apply@5`, `video.concatenate@1` | 공유 Frame에 각 장면 적용, 빈칸→정답 연결 |
| 안내 문서 | `subtitle.practice_guide@1` | 같은 타이밍에서 따라 말하기/다시 듣기 CaptionDocument 생성 |
| 합성 | 기존 `subtitle.layout@3`, `video.caption_burn@2`, `video.change_voice@1` | 준비된 Video, CaptionLayout, Audio 결합 |

모두 Workflow execution Node다. 새 type key는 첫 계약 버전 1로 등록되며, Generic Inspector와 Registry Port 검증을 사용한다. 별도 UI Node key 분기나 Provider dispatch 분기를 추가하지 않았다.

`data.practice_timing.v1`의 legacy artifact type은 `PracticeTiming`이다. Audio와 별도 Artifact로 저장하여 multi-output routing이 각 Edge의 고정된 Port로 정확히 분리한다. Schema는 `packages/schemas/practice.timing.v1.schema.json`에 있다.

연습 음성의 phase는 실제 TTS 길이 + 시작 여유 + 말끝 여유를 포함하는 92 BPM 마디 단위로 계산하고 30fps 경계로 올림한다. 첫 phase는 듣기, 둘째는 따라 말하기, 셋째는 다시 듣기다. 마지막 1.5초 이상은 음성과 비트 모두 무음이며 정답 화면을 유지한다. `practice-track.v1.1` Executor는 기존 24fps 장면 연결과 AAC 프레임 반올림 후에도 이 하한이 유지되도록 두 source frame의 여유를 추가한다. 안내 자막은 세 번째 phase가 끝날 때 종료한다. 입력이 길어지면 모든 타이밍을 함께 다시 계산한다.

기존 Concatenate 계약은 24fps로 정규화한다. 최종 영상은 현재 1080×1920 H.264/AAC이며 4K/30fps 마스터 작업은 별도다. 새 계약 없이 기존 Concatenate의 의미를 변경하지 않았다.

## 실제 앱 화면 렌더 서비스

`image.study_screen`은 모사 이미지나 생성형 이미지가 아니라 `japanese-app`의 `ReviewRepo.resolve`, `ReviewSessionPage`, `FuriganaText`를 사용한다. 단어 읽기는 앱의 Rust/Lindera 분석기로 준비한다. 원본 PNG는 2340×5064다. 앱 사용자 DB는 열지 않고 메모리 DB를 사용한다.

로컬 Flutter SDK와 앱 프로젝트가 필요하므로, API/Temporal 컨테이너는 Mac의 인증된 로컬 렌더 서비스에 요청한다. 현재 서비스는 `127.0.0.1:8769`에서 실행 중이다. Docker Desktop에서 `host.docker.internal`로 접근한다.

```sh
python3 scripts/study-screen/server.py \
  --project /Users/geusan/workspaces/projects/study/japanese-app \
  --flutter /Users/geusan/development/flutter \
  --token-file /Users/geusan/workspaces/projects/video-canvas/imports/.study-screen-token \
  --cache /Users/geusan/workspaces/projects/video-canvas/output/hisohiso-app-reels/single-template/screens
```

인증 토큰은 Workflow Config나 Run 입력에 넣지 않는다. 컨테이너 기본 경로는 `/imports/.study-screen-token`이며 `STUDY_SCREEN_TOKEN_FILE`로 설정할 수 있다. URL은 `STUDY_SCREEN_SERVICE_URL`로 설정하며 기본값은 `http://host.docker.internal:8769/render`다. 서비스가 중지되면 화면 Node가 재시도 가능한 오류를 반환한다.

서비스 revision은 렌더 스크립트, 앱 Dart 소스, 폰트, Rust 실행 파일, pubspec.lock을 해시한 값이다. `image.study_screen` Config의 `renderer_revision`에 고정하여 request hash와 Runtime snapshot에 포함한다. 서비스 revision이 달라지면 자동으로 과거 버전을 재해석하지 않고, Draft를 명시적으로 갱신하고 새 Version을 게시해야 한다.

각 요청은 데이터로만 전달한다. 사용자 문자열을 셸 또는 Dart 코드에 삽입하지 않는다. 임시 Flutter 테스트 파일은 고정 템플릿을 복사하고 JSON 입력 경로만 전달하며 실행 후 삭제한다. 렌더 캐시는 입력과 renderer revision으로 구분한다.

## 실행·오류·비용·검증

- Local과 Temporal은 동일한 Registry dispatch/Executor를 사용한다.
- 각 결과는 `NodeExecutionResult`와 immutable Artifact/lineage 계약을 따른다. 이미지에는 renderer revision, 오디오에는 FFmpeg revision과 timing을 기록한다.
- 화면·음성배치·Motion·안내 Node 자체의 Provider 비용은 0이다. LLM/TTS는 기존 Provider 계약의 exact model/cost 기록을 사용한다.
- 문장 변경, JSON/빈칸 불일치, 길이 초과, renderer revision 불일치는 non-retryable 오류다. 렌더 서비스 일시 중단은 retryable 오류다.
- 기존 Definition digest는 변경하지 않았다. 새 네 계약만 golden snapshot에 추가했다.
- 테스트: Config/default/binding, cache key, schema, input cardinality, 음성/타이밍 output routing, Artifact lineage, 실제 WAV 끝 무음, cue 종료 시각, 잘못된 입력, renderer 장애·revision을 검증한다.
- 실제 전체 Workflow 실행 결과와 영상 검증은 `output/hisohiso-app-reels/single-template/`에 저장한다.

## 완료 검증

현재 Published v4는 입력 2개, 실행 Node 18개, Output 1개다. UI 폼에서도 두 입력으로 실행했다. 서로 다른 일본어/한국어 입력으로 Temporal 전체 실행 두 건이 성공했고, 이미지/음성/최종 Artifact가 바뀌는 것을 확인했다. 최종 MP4 decode 검사와 정답/끝 프레임 시각 검증을 통과했다. 마지막 무음은 각각 1.592초와 1.558초다. 계약·Registry·기존 Workflow·Canvas·Architecture 회귀 테스트 96개가 통과했다.

- Run: `canvasrun_293f3ed1293c4b31a0`, `canvasrun_fb6ac90c593448318e`
- 샘플 영상: `output/hisohiso-app-reels/single-template/sample-1.mp4`, `sample-2.mp4`
- v1~v3과 기존 원본 캔버스는 보존했다.
