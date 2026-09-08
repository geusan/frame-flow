# Single-responsibility 이미지 영상 Pipeline

Status: Implemented

기존 `video.media_story@1`은 이미지 Motion, Frame, 장면 연결, 자막 배치와 음성 합성을 한 계약에서 처리한다. 과거 Canvas와 WorkflowVersion 실행을 위해 이 계약은 유지하지만, 신규 이미지 스토리는 아래의 독립 Node 계약을 사용한다.

```text
Image ──> image.motion@4 ──> video.frame_apply@5 ──┐
Image ──> image.motion@4 ──> video.frame_apply@5 ──┼─> video.concatenate@1 ──┐
Image ──> image.motion@4 ──> video.frame_apply@5 ──┘                         │
                                   ▲                                          ├─> video.compose@1 ──> FinalVideo
                 layout.media_frame@1 (shared)                                │
                                                                              │
Subtitle ──> subtitle.layout@1 ────────────────────────────────────────────────┤
Audio ─────────────────────────────────────────────────────────────────────────┘
```

## 책임 경계

| 계약 | 한 가지 책임 | 입력 | 출력 |
| --- | --- | --- | --- |
| `image.motion@4` | 원본 전체의 View 중심 Path, 독립 timing과 Hold View를 저장 | Image | MediaMotion |
| `layout.media_frame@1` | 여러 장면이 공유하는 Canvas Frame을 불변 Layout Artifact로 저장 | 없음 | MediaFrame |
| `video.frame_apply@5` | 원본을 선행 crop하지 않고 Full-source Motion을 공유 Frame에 렌더 | MediaMotion + MediaFrame | Video |
| `video.concatenate@1` | 연결 순서의 Video Clip을 Hard Cut으로 연결 | Video × N | Video |
| `subtitle.layout@1` | Timed Subtitle의 표시 영역과 기본 Style을 저장 | Subtitle | CaptionLayout |
| `video.compose@1` | Video, CaptionLayout, Narration Audio를 최종 MP4로 결합 | Video + CaptionLayout + Audio | FinalVideo |

각 Node는 다른 단계의 설정을 가지지 않는다. 예를 들어 `video.compose@1`에는 Motion, Frame, Crop, 장면 순서 설정이 없고, `image.motion@1`에는 출력 해상도나 자막 설정이 없다.

## Image Motion

`image.motion@1`은 원본 Image Artifact hash와 다음 값을 `image.motion.v1`에 Snapshot한다.

- 장면 길이와 FPS
- 시작 `scale`, `x`, `y`
- 종료 `scale`, `x`, `y`
- 보간 방식

Custom Editor는 START/END 화면을 나란히 보여주며 선택된 키프레임의 확대율과 초점을 편집한다. 한 Image마다 별도 Node를 사용하므로 모든 장면이 서로 다른 Motion을 가질 수 있다.

곡선 카메라 이동을 사용하는 신규 Draft는 `image.motion@2`와 `video.frame_apply@3`을 사용한다. `image.motion.v2`는 기존 시작·종료 Transform에 아래 경로 계약을 추가한다.

- `path.type`: `linear` 또는 `cubic_bezier`
- 정규화된 `control_1`, `control_2` 좌표
- 시작·종료 Zoom과 선형 시간 진행률

`image.motion@3`에서는 Linear와 Bézier가 별도 편집기가 아니라 같은 Path Editor의 보간 방식 선택이다. 고정된 이미지 위에 Start View와 Hold View를 테두리 사각형으로 표시하고, Bézier를 선택했을 때만 두 Control handle을 추가한다. Position과 Zoom은 각각 완료 progress를 가지며 Zoom에는 별도의 `linear`, `ease_in`, `ease_out`, `ease_in_out` 속도 곡선을 적용한다. 둘 중 늦은 완료 시점 이후부터 장면 끝까지 위치와 확대가 Hold View로 고정된다.

Preview를 누르면 경로와 핸들을 숨기고, 연결된 MediaFrame의 실제 Canvas·Frame 사각형 안에서 `cover`, focus 좌표와 Zoom timing을 설정된 장면 길이로 재생한다. 완료 또는 Stop 시 진행률을 초기화하고 편집 화면으로 돌아온다. `video.frame_apply@4`는 UI와 같은 위치·Zoom 시간 함수를 FFmpeg `zoompan`에 적용한다. 기존 `image.motion@1,@2`와 `video.frame_apply@1,@2,@3`의 렌더 의미는 유지한다.

`image.motion@4`는 Path의 S/H/Control point를 `source_image_view_center` 좌표로 저장한다. Editor의 포인터, View 테두리 중심과 미니맵 현재점이 모두 같은 좌표 의미를 가진다. `video.frame_apply@5`는 원본을 MediaFrame 화면비로 미리 중앙 crop하지 않고, cover-scale한 원본 전체에서 각 프레임의 View 중심과 Zoom으로 동적 crop한다. 따라서 세로 원본의 상단·하단도 View가 이미지 밖으로 나가지 않는 범위까지 탐색할 수 있다. 이전 `@3/@4` focus-ratio 경로는 과거 Artifact 실행을 위해 유지한다.

## Shared Media Frame과 Frame Apply

`layout.media_frame@1`은 아래 레이아웃을 `layout.media_frame.v1` Artifact로 Snapshot한다. Custom Editor에서는 Frame을 마우스로 드래그하고 네 모서리를 끌어 크기를 지정할 수 있다.

- 출력 화면비와 해상도
- 정규화된 `frame_x`, `frame_y`, `frame_width`, `frame_height`
- `cover` 또는 `contain`
- Canvas 배경색

하나의 MediaFrame 출력은 여러 `video.frame_apply@2` 입력에 fan-out할 수 있다. Frame을 이동한 뒤 다시 실행하면 연결된 모든 장면이 같은 새 Frame Artifact를 사용하므로 위치가 함께 바뀐다. 각 `video.frame_apply@2`는 한 Motion만 렌더하므로 장면별 Preview, Cache와 Retry 경계는 유지된다.

Motion 렌더 결과는 Frame 사각형 밖으로 Clip된다. 출력은 오디오가 없는 H.264 Video Clip이다. `video.frame_apply@1`은 과거 WorkflowVersion 실행을 위해 그대로 유지하며, 공유 Frame 입력은 Breaking port change이므로 `@2`에만 존재한다.

## Subtitle Layout

`subtitle.layout@1`은 Video를 입력받지 않는다. SRT Artifact hash, 정규화된 Caption Frame과 정렬·글꼴·색상을 `subtitle.layout.v1`로 저장한다. Preview의 화면비는 편집 보조 정보이며 최종 합성 시 실제 Video 크기에 정규화 좌표를 적용한다.

Rich Caption 신규 Draft는 다음의 더 작은 책임 경계를 사용한다.

```text
Subtitle ──> subtitle.design@1 ──> CaptionDocument ──┐
                                                    ├─> subtitle.layout@3 ──> CaptionLayout
layout.media_frame@1 ──> MediaFrame ────────────────┘              │
                                                                   │
Video ─────────────────────────────────────────────────────────────┴─> video.caption_burn@2 ──> Captioned Video
Audio ────────────────────────────────────────────────────────────────────────────────────────> video.change_voice@1
```

- `subtitle.design@1`은 TipTap cue/run, 색상, Bold, Italic, Font profile과 크기만 `caption.document.v1`에 저장한다.
- `subtitle.layout@3`은 CaptionDocument와 공유 MediaFrame을 받아 Media Frame과 Caption Frame을 같은 Canvas 좌표계로 `subtitle.layout.v3`에 Snapshot한다. Custom Editor에서는 Media Frame을 읽기 전용 기준선으로 보고 Caption Frame만 드래그·리사이즈한다. 글꼴이나 색상은 소유하지 않는다.
- `video.caption_burn@2`는 Video와 Frame-aware CaptionLayout을 받아 등록 Font Artifact를 materialize하고 자막만 픽셀에 렌더한다. 오디오는 교체하지 않으며, 입력 Video 크기가 MediaFrame에서 고정한 Canvas 크기와 같은지 검증한다.
- Caption Frame 안에서는 공백으로 구분된 단어를 보존하는 자동 줄바꿈을 기본으로 사용한다. CaptionDocument의 `hardBreak`는 자동 배치보다 우선하는 수동 줄바꿈으로 렌더한다.
- 내레이션 오디오 결합은 기존 `video.change_voice@1`이 담당한다.
- `subtitle.layout@2`와 `video.caption_burn@1`의 Video snapshot 경로, `subtitle.layout@1`, `video.compose@1`, `timeline.compose@2`, `video.render@2`는 과거 Draft/Version 실행을 위해 유지한다.

## Final Compose

`video.compose@1`은 이미 연결된 Video를 변경하거나 장면을 재배치하지 않는다. CaptionLayout에 고정된 Subtitle를 지정 영역 안에 렌더하고, Narration Audio를 Video 길이에 맞춰 결합하는 일만 수행한다.

## 호환과 Migration

- `video.media_story@1` WorkflowVersion과 Run Snapshot은 변경하지 않는다.
- 기존 Draft는 자동으로 in-place 변환하지 않는다.
- Draft에서 `image.motion@1,@2,@3`을 `@4`로 올릴 때는 각 Start/Hold/Control focus-ratio를 당시 Zoom과 MediaFrame·원본 화면비로 계산한 실제 View 중심 좌표로 변환해야 한다. Position/Zoom timing은 명시적으로 materialize하고, 연결된 Frame Apply는 `@5`로 함께 교체하며 기존 Motion/Video Artifact가 stale임을 경고한다.
- Draft에서 수동 교체할 때 하나의 `layout.media_frame@1`을 만들고, 각 기존 Image Edge마다 `image.motion@4`와 `video.frame_apply@5`를 만든다. 같은 MediaFrame 출력을 모든 Frame Apply에 연결한 뒤 결과를 하나의 `video.concatenate@1`에 순서대로 연결한다.
- 기존 Subtitle와 Audio Edge는 각각 `subtitle.layout@1`, `video.compose@1`로 연결한다.
- 교체 결과는 새 Canvas revision으로 저장하고 새 WorkflowVersion Publish가 필요하다.
