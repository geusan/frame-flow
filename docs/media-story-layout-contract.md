# Media Story 레이아웃 계약

`video.media_story@1`은 이미지와 영상의 화면 배치·Crop·Clip·Motion을 Node Config에서 직접 관리한다. 좌표는 해상도와 무관한 0–1 정규화 값이며 WorkflowVersion에 materialize된다.

## 좌표계

Canvas의 왼쪽 위가 `(0, 0)`, 오른쪽 아래가 `(1, 1)`이다.

```text
(0,0) ┌────────────────────────────────────┐
      │  media frame                       │
      │  x / y / width / height            │
      │                                    │
      ├────────────────────────────────────┤
      │  caption frame                     │
      │  x / y / width / height            │
(1,1) └────────────────────────────────────┘
```

| Config | 의미 | 기본값 |
| --- | --- | --- |
| `frame_x`, `frame_y` | 미디어 Clip 사각형의 왼쪽·위쪽 위치 | `0.04`, `0.02` |
| `frame_width`, `frame_height` | 미디어 Clip 사각형의 크기 | `0.92`, `0.62` |
| `caption_frame_x`, `caption_frame_y` | 자막 사각형의 왼쪽·위쪽 위치 | `0.06`, `0.68` |
| `caption_frame_width`, `caption_frame_height` | 자막 사각형의 크기 | `0.88`, `0.28` |

두 사각형은 Canvas 내부에 있어야 하고 서로 겹칠 수 없다. 렌더 시 좌표와 크기는 H.264가 처리할 수 있는 짝수 픽셀로 결정된다.

## Crop과 Clip

`media_fit`은 원본 종횡비를 항상 유지한다.

- `cover`: 미디어 프레임을 가득 채우고 넘치는 부분을 Crop한다.
- `contain`: 원본 전체를 보이고 남는 영역을 Canvas 배경색으로 채운다.

`crop_focus_x`, `crop_focus_y`는 `cover` Crop의 기준점이다. `(0.5, 0.5)`는 중앙, `(0, 0)`은 왼쪽 위, `(1, 1)`은 오른쪽 아래를 우선 보존한다.

Crop과 Motion 계산이 끝난 결과는 `frame_x/y/width/height` 사각형으로 Clip된다. 이미지나 영상 픽셀이 자막 프레임으로 넘어가지 않는다.

## Motion

`motion_preset`은 다음 값을 지원한다.

| 값 | 동작 |
| --- | --- |
| `alternate` | 장면마다 zoom in, pan right, zoom out, pan left 반복 |
| `zoom_in`, `zoom_out` | 중앙 기준 확대·축소 |
| `pan_left`, `pan_right` | 확대된 미디어를 수평 이동 |
| `pan_up`, `pan_down` | 확대된 미디어를 수직 이동 |
| `still` | 이동 없음 |
| `custom` | 아래 시작·종료 Transform을 선형 보간 |

Custom Motion은 다음 Config를 사용한다.

- `motion_start_scale`, `motion_end_scale`: `1.0`–`2.0`
- `motion_start_x`, `motion_start_y`: 시작 초점
- `motion_end_x`, `motion_end_y`: 종료 초점

Preset에서는 `motion_amount`가 최대 확대·이동량을 결정한다. 이미지와 영상 모두 같은 Motion 계약을 사용한다. 영상이 장면 길이보다 짧으면 반복하고, 할당된 장면 프레임 수에서 정확히 자른다. 입력 영상의 원본 오디오는 사용하지 않고 선택적 Narration Audio를 최종 트랙으로 사용한다.

## 입력 순서와 장면 길이

연결된 Image와 Video의 Edge 순서가 장면 순서다.

- `scene_timing=equal`: Subtitle 또는 Audio의 전체 길이를 미디어 수로 균등 분할한다.
- `scene_timing=subtitle_cues`: 미디어 수와 SRT cue 수가 같아야 하며 각 cue 시작점에서 장면을 바꾼다.

## 9:16 기본 레이아웃

```json
{
  "aspect_ratio": "9:16",
  "frame_x": 0.04,
  "frame_y": 0.02,
  "frame_width": 0.92,
  "frame_height": 0.62,
  "media_fit": "cover",
  "crop_focus_x": 0.5,
  "crop_focus_y": 0.5,
  "caption_frame_x": 0.06,
  "caption_frame_y": 0.68,
  "caption_frame_width": 0.88,
  "caption_frame_height": 0.28,
  "motion_preset": "alternate",
  "motion_amount": 0.12
}
```

이 설정은 중앙 기준 Crop으로 원본 비율을 보존하면서 상단 62% 영역에 미디어를 배치하고, 하단의 독립된 28% 영역에 줄바꿈된 자막을 배치한다.

## 재현성 Snapshot

같은 Node를 다시 실행할 수 있도록 다음 값을 고정한다.

- Workflow/Canvas Node: `type_key`, `contract_version`, `definition_digest`, materialized Config
- 입력: 순서가 보존된 Image/Video/Subtitle/Audio Artifact ID와 immutable content hash
- 장면: 각 입력 Artifact에 대응하는 frame count와 resolved motion start/end scale·focus
- Layout: 렌더 픽셀로 해석된 media frame, caption frame, fit과 crop focus
- Renderer: Executor revision, FFmpeg/libass version, 실제 선택된 caption font file hash
- 결과: `FinalVideo`, `video.media_story.v1`, output Artifact SHA-256와 lineage roles

`alternate`도 실행 결과에 단순 문자열로만 남기지 않는다. 장면별 `zoom_in`, `pan_right`, `zoom_out`, `pan_left`와 실제 시작·종료 Transform을 `resolved_motion_plan`으로 Artifact metadata에 기록한다.

FFmpeg 또는 글꼴 파일이 달라지면 `renderer_environment.fingerprint`와 Runtime executor revision이 바뀐다. 이 값은 request hash에 포함되므로 다른 렌더 환경에서 과거 cache를 동일 결과로 잘못 취급하지 않는다. 동일 입력·Config·renderer fingerprint의 테스트 fixture는 byte-identical MP4 SHA-256을 요구한다.
