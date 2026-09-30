# 히소히소 릴스 제작 형식

사용자가 합의하고 새 캔버스/워크플로우에 반영한 반복 재생 규칙이다.

**최신 요구사항: 문장마다 그래프를 복제하지 않는다. 워크플로우 하나에 일본어 문장과 한국어 뜻 두 입력을 바꿔 실행한다. 이미지·음성·타이밍은 자동 생성한다.**

현재 활성 Draft는 `canvas_3e7de1a2d0dd4543b9`, Workflow는 `workflow_346ced61574e4f22bc`다. 아래 27개 output 설명은 보존된 v1 이력이다. 새 자동화 구현은 [두 입력 워크플로우](hisohiso-two-input-workflow.md)를 참고한다.

## 장면과 소리

1. 빈칸 화면을 보며 일본어 문장을 듣는다.
2. 후리가나가 있는 정답 화면을 보며 따라 말한다.
3. 같은 정답 화면에서 마지막 문장 발음을 다시 듣는다.
4. 마지막 발음이 끝난 뒤 **최소 1.5초 동안 정답 화면을 무음으로 유지**한다.
5. 영상이 반복되어 첫 장면으로 돌아간다.

마지막 발음 직후 첫 발음이 붙지 않도록 한다. 엔딩에는 새 발음이나 비트를 추가하지 않는다. 기존 안내 자막은 원래 종료 시각에 끝내고 마지막 쉼에는 정답 화면만 남긴다. 사용자 요청 없이 앱 화면/자막 디자인을 바꾸지 않는다.

## v1 구현 이력

- 원본 Canvas: `canvas_09c544e67ddb42f28f` (보존)
- 새 Canvas: `canvas_3e7de1a2d0dd4543b9`
- Workflow: `workflow_346ced61574e4f22bc`
- Published v1: `workflowver_aa19c9342b6c45e3ac`
- 드라마 24개 + えぐい 3개, 총 27개 Primary/Secondary output.
- 기존 Registry 계약과 제작 그래프를 사용한다. 신규 Node나 계약 변경은 없다.
- 각 정답 `image.motion@4`의 길이를 30fps 프레임 경계로 올림한 뒤 1.5초 연장한다.
- `video.change_voice@1`의 기존 Audio padding 동작이 영상 끝까지 무음을 채운다. 기존 고정 mix Artifact는 유지한다.
- 원고/TTS를 바꾸면 고정 mix가 자동으로 갱신되지 않는다. mix와 장면/자막 타이밍을 함께 준비하고, 실제 최종 음성 끝에서 최소 1.5초의 쉼을 다시 검증해야 한다.
- 규칙은 Canvas Sticky와 Published Version Annotation에도 저장했다.

## 검증과 범위

- 27개 output의 Publish compiler 검증 통과, 경고 없음.
- `drama-line-01`의 Motion → Frame Apply → Concatenate → Caption Burn → Audio mux를 실제 Executor로 실행했다.
- 샘플: `output/hisohiso-app-reels/loop-pause/drama-01-loop-pause.mp4`
- 영상 9.333초, 1080×1920, 기존 Concatenate 경로의 24fps. 이 작업은 4K/30fps 마스터 내보내기 변경이 아니다.
- -60dB 기준 마지막 무음 시작 7.627초. 영상 끝까지 약 1.706초의 무음이며, 마지막 프레임에 정답 화면이 남고 안내 자막은 없다.
- 전체 decode 검사 통과. 나머지 26개는 설정/게시 완료이며 이 작업에서 재렌더하지 않았다.
- 재현 요청/응답과 검증 보고서: `output/hisohiso-app-reels/loop-pause/`.

## 화질 확인 시 유의점

파일 크기가 비슷하다는 이유만으로 같은 파일로 간주하지 않는다. 전달된 파일의 해시, 실제 해상도, 길이, 프레임을 비교한다. 이 세션의 카카오톡 수신 파일들은 406×720이었고, 검사한 1080×1920 원본과 달랐다. 이것만으로 iPhone Photos 저장 과정이 해상도를 낮췄다고 단정하지 않는다.
