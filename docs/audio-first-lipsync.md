# 오디오 기준 문장별 립싱크

최종 음성을 먼저 고정하고 문장 사이의 쉼에서 영상·음성을 같은 구간으로 추출한다.
사용자가 확인한 첫 3.25초 pilot은 재사용한다. 남은 다섯 구간은 아래 계약으로 실행한다.

| 계약 | 역할 |
| --- | --- |
| `video.segment@1` | 시작 시각·길이를 출력 FPS 프레임 경계로 반올림해 무음 H.264 Video를 만든다. 끝 부족분은 명시한 `end_padding_seconds` 범위에서만 마지막 프레임으로 채운다. |
| `audio.segment@1` | 동일 시각·길이의 48kHz PCM WAV를 추출한다. 재생 속도를 바꾸거나 부족한 발화를 자동으로 채우지 않는다. |
| `video.lip_sync@1` | 같은 길이의 Video/Audio로 Sync Lipsync 2 Pro를 실행한다. 출력은 입력 프레임 시간축으로 정규화한 무음 Video이며, 음성 결합은 기존 별도 mux Node에서 한다. |

세 Node는 Workflow data/execution Atomic Node다. Manifest/Config/typed Ports/Generic
Inspector/Native Executor를 Registry에 등록했다. 기존 Definition과 과거 Artifact는
수정하지 않는다. `video.split@1`은 균등 분할 계약으로 유지한다.

출력 schema ID는 `video.segment.v1`, `audio.segment.v1`, `video.lip_synced.v1`이다.
Artifact에 원본과 lineage 역할, normalized config, Definition digest, Executor와 FFmpeg
revision을 기록한다. Lip sync는 exact model ID, Provider request ID, billable units와
조회된 단가도 저장한다. 응답 단위×단가로 계산한 비용은 세금·청구서 확정 금액이 아니다.
사용량/단가를 받지 못하면 `provider_billed_unreported`로 남기며 무료라고 해석하지 않는다.

영상·음성 범위 오류는 non-retryable이다. FAL 요청 전 pending checkpoint를 남기고,
알려진 request ID는 재제출 없이 polling/download로 재개한다. 불명확한 submit 실패는
자동 재제출하지 않는다. Local 실행과 Temporal Activity는 같은 Executor를 사용한다.

Canvas의 타임라인 경계는 24fps 기준 frame `[0, 78, 156, 245, 325, 391, 453]`이다.
첫 컷 이후 각각 3.25, 3.708333, 3.333333, 2.75, 2.583333초이며 발화는 자르지 않고
긴 쉼 안에 경계를 둔다. 최종 영상의 프레임 시간은 18.875초, 원본 음성은 약 18.879초다.
마지막 구간의 영상 끝 부족분은 약 한 프레임의 hold만 허용한다.

완료 순서: 문장별 입모양 보정 → 순서대로 연결 → 전체 자막 → 고정된 Tsuki 음성 합성.
영상 생성 모델의 음성을 다시 합성하지 않는다. `source_performance`와 `target_speech`를
구분해 기록하므로 어느 영상에 어떤 발화가 적용됐는지 추적할 수 있다.

검증은 기존 pilot과 같은 SyncNet 상대 지표 및 프레임 검수로 한다. 자동 점수는 언어별
절대 통과 기준이나 0ms의 완벽한 동기화를 증명하지 않는다. 얼굴이 가려지는 구간은
별도 확인해야 한다. Source Video/Audio 길이가 한 프레임보다 크게 다르면 실행을 거부한다.

검증 범위: Manifest/digest/default/binding/Port, 구간별 프레임·샘플 수, padding 제한,
정규화된 Provider request, 중복 submit 방지와 resume, 실제 Artifact/Lineage/비용 metadata,
cache replay, Local/Temporal parity, Publish 도달성 및 Annotation 제외.

## 2026-10-01 실제 6문장 실행

`canvas_13dbb3e95ecc48d79a`의 `lipsync-final-video`에 전체 결과를 저장했다.
사용자가 확인한 첫 컷은 재사용했고, 나머지 다섯 컷의 Provider 사용량×단가 합계는
$1.50이다. 첫 pilot $0.3333까지 포함하면 약 $1.83이며 Veo·음성 재생성 비용은 없다.

SyncNet 상대 평가의 최적 시차는 컷 순서대로 보정 전 `[440, 480, -440, -320,
-280, -360]ms`, 보정 후 `[0, 0, 0, -40, 40, 40]ms`였다. 평가 해상도는 40ms이며
언어별 절대 통과 판정은 아니다. 컷 5의 첫 프레임에서 얼굴 검출이 누락되어 다음
프레임의 crop을 같은 before/after에 적용했다. 68프레임 중 1프레임이었다.

기존 연결 실행기가 생성한 무음 AAC 트랙과 컨테이너 시작 시각 때문에 자막 합성 후
영상이 음성보다 약 41ms 늦게 시작했다. 연결 다음에 `video.segment@1`로 전체
453프레임을 0초 기준 무음 영상으로 정렬하는 `lipsync-clock-aligned`를 두고 자막과
고정 음성을 다시 합성했다. 기존 계약/과거 Artifact는 수정하지 않았으며 유료 립싱크도
다시 호출하지 않았다. 이후에도 연결·자막·mux 결과의 stream 시작 시각을 검사해야 한다.

재현 자료: `output/lipsync-full/results.json`, `assessment.json`, `final-probe.json`,
`report.md`. 영상의 기존 Veo 질감/배경 노이즈는 이번 입모양 보정의 수정 범위에 포함하지 않았다.
