# Single-responsibility 이미지 영상 Pipeline

Status: Implemented

기존 `video.media_story@1`은 이미지 Motion, Frame, 장면 연결, 자막 배치와 음성 합성을 한 계약에서 처리한다. 과거 Canvas와 WorkflowVersion 실행을 위해 이 계약은 유지하지만, 신규 이미지 스토리는 아래의 독립 Node 계약을 사용한다.

```text
Image ──> image.motion@1 ──> video.frame_apply@2 ──┐
Image ──> image.motion@1 ──> video.frame_apply@2 ──┼─> video.concatenate@1 ──┐
Image ──> image.motion@1 ──> video.frame_apply@2 ──┘                         │
                                   ▲                                          ├─> video.compose@1 ──> FinalVideo
                 layout.media_frame@1 (shared)                                │
                                                                              │
Subtitle ──> subtitle.layout@1 ────────────────────────────────────────────────┤
Audio ─────────────────────────────────────────────────────────────────────────┘
```

## 책임 경계

| 계약 | 한 가지 책임 | 입력 | 출력 |
| --- | --- | --- | --- |
| `image.motion@1` | 한 이미지의 시작·종료 카메라 Transform을 저장 | Image | MediaMotion |
| `layout.media_frame@1` | 여러 장면이 공유하는 Canvas Frame을 불변 Layout Artifact로 저장 | 없음 | MediaFrame |
| `video.frame_apply@2` | Motion을 연결된 공유 Frame에 Clip하고 Video Clip으로 렌더 | MediaMotion + MediaFrame | Video |
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

## Final Compose

`video.compose@1`은 이미 연결된 Video를 변경하거나 장면을 재배치하지 않는다. CaptionLayout에 고정된 Subtitle를 지정 영역 안에 렌더하고, Narration Audio를 Video 길이에 맞춰 결합하는 일만 수행한다.

## 호환과 Migration

- `video.media_story@1` WorkflowVersion과 Run Snapshot은 변경하지 않는다.
- 기존 Draft는 자동으로 in-place 변환하지 않는다.
- Draft에서 수동 교체할 때 하나의 `layout.media_frame@1`을 만들고, 각 기존 Image Edge마다 `image.motion@1`과 `video.frame_apply@2`를 만든다. 같은 MediaFrame 출력을 모든 Frame Apply에 연결한 뒤 결과를 하나의 `video.concatenate@1`에 순서대로 연결한다.
- 기존 Subtitle와 Audio Edge는 각각 `subtitle.layout@1`, `video.compose@1`로 연결한다.
- 교체 결과는 새 Canvas revision으로 저장하고 새 WorkflowVersion Publish가 필요하다.
