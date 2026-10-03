# 레퍼런스 시작 상태 이미지 → Vertex 영상

기존 캐릭터 Image와 새 레퍼런스 Video를 받아 다음 Draft 경로를 구성한다.

```text
Video → video.frame_extract@1 → 첫 프레임 Image ─┐
Character Image ────────────────────────────────┴→ prompt.input@1 → image.generate@1 → 시작 Image
시작 Image + motion Prompt → video.animate_image@1 → Video
```

프레임 추출과 이미지 생성은 독립적으로 미리보기·재실행할 수 있는 변환이므로 별도
Workflow Node다. 기존 Node를 바꾸지 않고 두 신규 계약을 등록했다.

| 계약 | 의미 |
| --- | --- |
| `video.frame_extract@1` | Video의 `timestamp_seconds`(기본 0) 시점 이후 첫 표시 프레임을 PNG로 추출한다. FFmpeg가 표시 회전과 sample aspect ratio를 적용하며 별도 crop은 하지 않는다. |
| `video.animate_image@1` | 정확히 한 Image를 Google Veo의 `source.image`에 보내 실제 시작 프레임으로 사용한다. 별도 Motion Prompt와 4/6/8초·비율·해상도를 설정한다. 1080p는 8초를 요구한다. |

두 계약은 Manifest, Registry, Generic Inspector, versioned media Port를 사용한다.
Local과 Temporal이 같은 Executor를 호출한다. frame Artifact는 `image.video_frame.v1`,
animation Artifact는 `video.image_animation.v1`이며 source_video/first_frame lineage,
normalized config, Definition digest와 Executor revision을 기록한다. 프레임 추출은
FFmpeg revision도 snapshot한다. Vertex 결과는 exact model ID를 저장한다.

프레임 범위 초과·잘못된 입력은 non-retryable이다. 새 영상 Node는 유료 호출 전에
Provider checkpoint를 기록해 불명확한 네트워크 실패를 자동 재제출하지 않는다.
현재 Google operation의 자동 재개는 지원하지 않으므로 중단 시 Provider 작업 이력을
확인해야 한다. Provider 실청구액을 받지 못하면 0달러가 아닌 미집계로 취급하고,
`cost_status=provider_billed_unreported` 및 Library의 Provider billed로 표시한다.

## 기존 계약과 Draft 교체

`video.generate@1`의 Image는 기존대로 reference_images(외형 참조)에 전달된다.
동일 contract version에서 이를 첫 프레임으로 재해석하지 않는다. 게시 Version과
과거 Run/Artifact는 변경하지 않는다.

수동 Draft 교체: Video generator를 Animate starting image로 교체하고, 생성된 시작
이미지의 `image` output을 새 Node의 `image` input에 연결한다. Prompt와 Video output
edge, 호환되는 비율·길이·해상도·seed는 옮길 수 있다. Character/Reference Video input은
새 계약에 없으므로 먼저 단일 시작 Image로 변환해야 한다. 이 의미 차이가 교체 경고다.
이번 Canvas 변경의 before/after와 diff는 `output/vertex-video-comparison/`에 저장한다.

Canvas: `canvas_13dbb3e95ecc48d79a`. 사용자가 새로 올린 Video를 추출·분석·음성 경로에
연결한다. 이미지 생성에는 사용자가 현재 선택한 Character Image를 identity/anatomy
참조로, 추출 프레임을 pose/composition 참조로 순서 있게 연결한다. 노딸깍 프롬프트는
Reference 인물의 얼굴이나 더 작은 바스트가 Character 체형을 덮어쓰지 않도록 명시한다.

검증: Manifest/digest/default/binding/Port, 실제 두 색 Video의 프레임 선택과 범위 오류,
Local/Temporal parity, cache replay, Google source.image request, 기존 reference_images
호환, fixture result 계약, 중복 과금 방지, Publish 도달성·Annotation 제외 및 Web 계약 검사.

로컬 검증: 실제 레퍼런스에서 첫 프레임 `art_81f0e1fe359a4a078b` (1080×1920 PNG)를 생성했다.
이미지/영상 Provider는 이 Canvas에서 실행하지 않았으며 시작 이미지 Node는 READY다.
API 관련 검증 86건 및 추가 이미지 fingerprint 회귀가 통과했고 Web typecheck,
contract/architecture 검사, 해당 Inspector ESLint와 production build를 확인했다.
실행 Web이 별도 `output/local-web-mouth-runtime`을 mount하므로 기존 런타임을
`output/vertex-video-comparison/web-before-start-frame`에 보관한 뒤 새 build와
연결된 Prompt 표시 수정을 반영했다.
