# 캐릭터 모션 리타게팅 Workflow 설계

작성 기준: 2026-09-01  
참조 결과: `art_e957e30384d643368e`

## 목표

원본 영상의 움직임과 오디오 길이를 유지하면서 영상 구간마다 동일한 캐릭터를 적용하고, 생성된 Clip들을 다시 원본 재생 시간으로 맞춘다. Canvas Draft에는 실행에 쓰이는 Video branch와 검증 가능한 Holistic MotionTrack branch를 함께 남긴다.

```text
Original Video
  ├─ Audio Extract ───────────────────────────────────────────────┐
  ├─ Holistic Motion Extract ──> Secondary output: MotionTrack    │
  └─ Slow Retime ──> Video Split ──> Clip Select × 7              │
                                      │                            │
Prompt ───────────────────────────────┼─> Video Generate × 7       │
Character Image ──────────────────────┘          │                 │
                                                v                 │
                                  Video Edit (ordered concat)      │
                                                │                 │
                                           Fast Retime             │
                                                │                 │
                                                └─ Replace Audio <─┘
                                                        │
                                                        v
                                             Primary output: Video
```

## 길이 계산

참조 결과의 원본 실측 길이는 `35.641초`이고 기존 생성 과정은 7개 Clip을 사용했다. 생성 모델 입력/출력 길이를 8초로 고정하면서 7개 branch를 유지한다.

```text
D = 35.641초               원본 길이
N = 7                      생성 Clip 수
T = 8초                    생성 모델 Clip 길이
G = N × T = 56초           느린 참조/생성/병합 길이
S = G ÷ D = 1.5712241520   원래 속도로 복원할 가속 배율
slow_speed = 1 ÷ S
           = D ÷ G
           = 0.6364464286
```

- 느리게 만들기: `video.retime@1.speed_multiplier = 0.6364464286`
- 분할: `video.split@1.segment_duration_seconds = 8`, 예상 7개 Clip
- 생성: 각 `video.generate@1.duration_seconds = 8`
- 병합: `video.edit@1.target_duration_seconds = 56`, `hard_cut`
- 빠르게 만들기: `video.retime@1.speed_multiplier = 1.5712241520`
- 오디오: `audio.extract@1`이 원본 encoded audio packet을 stream-copy하고 마지막 `video.change_voice@1`이 최종 Video 길이에 맞춰 연결한다.

## Node 계약 결정

기존 불변 계약은 수정하지 않는다.

| 역할 | 계약 | 결정 |
| --- | --- | --- |
| 원본/캐릭터/Prompt | `asset.select@1`, `prompt.input@1` | 기존 Source 계약 재사용 |
| Holistic 분석 | `motion.extract@1` | 기존 MotionTrack 계약 재사용, Secondary output으로 선언 |
| 느리게/빠르게 | `video.retime@1` | 한 계약의 `speed_multiplier`로 두 인스턴스 사용 |
| 원본 오디오 추출 | `audio.extract@1` | 새 원자 계약, 변환 없이 demux |
| 다중 Clip 분할 | `video.split@1` | 새 `media.video_clip_list.v1` 출력 계약 |
| 정적 fan-out 선택 | `video.clip.select@1` | 새 계약, 고정 index를 `media.video.v1`로 투영 |
| 캐릭터 영상 생성 | `video.generate@1` | 7개 고정 branch로 사용 |
| 이어붙이기 | `video.edit@1` | 기존 ordered multi-input 계약 재사용 |
| 오디오 교체 | `video.change_voice@1` | 기존 Video+Audio 계약 재사용 |

`video.split@1`이 여러 Video Artifact ID를 `media.video.v1` 하나로 직접 흘리지 않고 `VideoClipList` Artifact를 만드는 이유는, 현재 Workflow V1이 동적 loop/graph expansion을 지원하지 않기 때문이다. `video.clip.select@1` 7개를 명시하면 branch 수와 순서가 WorkflowVersion에 고정되고, 각 생성 Node의 cache key와 lineage도 독립적으로 유지된다.

Audio 추출, Video 분할, Retime, 병합, Audio 교체를 하나의 다기능 Node로 합치지 않는다. 이 기능들은 출력 Port type과 cardinality가 서로 달라 한 계약으로 합치면 config 조합에 따라 출력 의미가 바뀐다. 동일 FFmpeg capability를 내부 구현에서 공유하되 외부 Node 계약은 원자적으로 유지한다.

## 실행 및 Publish 규칙

- Primary output은 마지막 `video.change_voice@1`의 `media.video.v1`이다.
- `motion.extract@1`의 `data.motion_track.v1`을 Secondary output으로 선언해 분석 branch가 Publish reverse reachability에서 제거되지 않게 한다.
- `VideoClipList`는 최대 32개로 제한한다. 요청 길이가 `max_segments`를 초과하면 부분 결과를 만들지 않고 non-retryable validation error로 실패한다.
- 마지막 remainder는 기본적으로 유지한다. 이 Canvas의 slow target은 정확히 56초라 8초 Clip 7개가 예상된다.
- 분할 Clip은 무음 H.264 MP4다. 최종 오디오는 원본에서 한 번만 추출해 마지막 단계에서 교체하므로 branch별 오디오 drift와 중복 인코딩을 피한다.
- Local Canvas와 Temporal Activity는 같은 Registry executor dispatch를 사용한다.
