# Image Story Video 예제: 은혜 갚은 까치

`video.image_story@1`은 여러 장의 `Image`, 타임스탬프가 있는 `Subtitle`, 선택적인 `Audio`를 받아 세로형 이야기 영상을 만든다. 이미지는 상단의 고정된 클립 영역 안에서만 팬·줌하고, 자막은 이미지가 끝난 뒤의 하단 패널에 렌더된다.

이 예제의 줄거리는 과거 시험을 보러 가던 선비가 구렁이에게서 까치 가족을 구하고, 이후 까치가 목숨을 다해 선비에게 은혜를 갚는 판본을 사용한다. 경기도어린이박물관의 공연 소개와 주일한국문화원의 전래동화 소개를 바탕으로 짧은 영상용 문장으로 다시 구성했다.

- 경기도어린이박물관 줄거리: <https://gcm.ggcf.kr/events/40>
- 주일한국문화원 전래동화 소개: <https://koreanculture.jp/korean/search_news_view.php?number=7570&page=15>

## Canvas 구조

```text
Narration Prompt → Voiceover ───────────────┬→ Speech subtitles → Subtitle ─┐
                                            └→ Audio ───────────────────────┤
Scene 1 Prompt → Image Generator 1 → Image ─────────────────────────────────┤
Scene 2 Prompt → Image Generator 2 → Image ─────────────────────────────────┤
Scene 3 Prompt → Image Generator 3 → Image ─────────────────────────────────┤
Scene 4 Prompt → Image Generator 4 → Image ─────────────────────────────────┤
Scene 5 Prompt → Image Generator 5 → Image ─────────────────────────────────┤
Scene 6 Prompt → Image Generator 6 → Image ─────────────────────────────────┤
Scene 7 Prompt → Image Generator 7 → Image ─────────────────────────────────┤
                                                                            ↓
                                                              Image Story Video
                                                                            ↓
                                                                       FinalVideo
```

Image 연결 순서가 장면 순서다. `Speech subtitles`처럼 cue 개수가 실행마다 달라질 수 있는 입력은 `scene_timing=equal`을 사용한다. 자막 cue를 직접 검수해 이미지와 정확히 1:1로 맞춘 경우에는 `scene_timing=subtitle_cues`로 바꾸면 각 cue 시작점에서 다음 이미지로 전환된다.

## 첫 영상 설정

| 설정 | 값 |
| --- | --- |
| `aspect_ratio` | `9:16` |
| `resolution` | `1080p` |
| `fps` | `24` |
| `scene_timing` | `equal` |
| `motion_preset` | `alternate` |
| `motion_amount` | `0.12` |
| `image_region_height_ratio` | `0.62` |
| `image_margin_ratio` | `0.04` |
| `background_color` | `#11100E` |
| `caption_font_family` | `Noto Sans CJK KR` |
| `caption_font_size` | `58` |
| `caption_color` | `#F7F3E8` |
| `caption_outline_color` | `#000000` |
| `caption_align` | `center` |

## 내레이션 Prompt

아래 일곱 문단을 하나의 `Prompt` 노드에 넣어 Voiceover에 연결한다.

```text
옛날, 한 선비가 과거 시험을 보러 깊은 산길을 걷고 있었습니다.

그때 다급한 까치 울음이 들렸습니다. 커다란 구렁이가 둥지의 새끼 까치들을 노리고 있었습니다.

선비는 위험을 무릅쓰고 구렁이를 쫓아냈고, 까치 가족은 무사히 목숨을 건졌습니다.

날이 저문 뒤 길을 잃은 선비는 산속 외딴집을 발견하고, 그곳에서 하룻밤을 묵게 되었습니다.

한밤중 집주인은 무서운 구렁이로 변했습니다. 낮에 죽은 구렁이의 짝이라며 선비를 단단히 휘감았습니다.

구렁이는 새벽 전에 절의 종이 세 번 울리면 살려 주겠다고 했습니다. 바로 그때, 종소리가 어둠을 가르며 세 번 울렸습니다.

선비를 살리려고 까치들이 온몸으로 종을 울린 것이었습니다. 선비는 작은 생명에게 베푼 마음과 목숨으로 돌아온 은혜를 오래도록 기억했습니다.
```

## 장면 이미지 Prompt

모든 Prompt 앞에 다음 공통 스타일을 붙인다.

```text
조선 시대 한국 전래동화 삽화, 절제된 수묵담채와 종이 질감, 따뜻한 달빛과 안개, 같은 푸른 도포의 젊은 선비, 세로 9:16 구도, 글자와 워터마크 없음, 어린이도 볼 수 있는 비폭력적 표현
```

1. 새벽 안개가 흐르는 깊은 산길을 따라 과거 시험을 보러 걷는 선비, 멀리 산봉우리와 소나무.
2. 높은 소나무 둥지에서 겁먹은 새끼 까치들, 나무를 오르는 큰 구렁이, 아래에서 놀라 올려다보는 선비.
3. 선비가 긴 지팡이로 구렁이를 멀리 쫓아내고, 부모 까치가 둥지 주위를 날며 새끼를 지키는 장면.
4. 해가 진 산속, 희미한 등불이 켜진 외딴 초가집 문 앞에 선비가 서 있고 집주인 여인이 맞이하는 장면.
5. 달빛이 스미는 방 안, 거대한 구렁이가 선비를 휘감고 있고 선비가 멀리 산사의 종을 바라보는 긴장된 장면, 잔혹한 묘사 없음.
6. 새벽 직전의 푸른 하늘, 부모 까치들이 온힘을 다해 커다란 절 종을 울리고 종이 크게 흔들리는 역동적인 장면.
7. 동이 트는 산사, 살아난 선비가 종 앞에서 까치들에게 깊이 고개 숙여 감사하고 햇빛이 구름 사이로 비치는 여운 있는 장면.

## 실행 계약

- `video.image_story@1`은 최대 32개의 이미지를 입력 순서대로 처리한다.
- `subtitle_cues` 모드에서는 이미지 수와 SRT cue 수가 다르면 실행을 거부한다.
- 출력은 H.264/yuv420p MP4이며 Audio 입력이 있으면 AAC로 정규화한다.
- 결과 Artifact는 `FinalVideo` / `video.image_story.v1`이고, 각 입력은 `story_image`, `timed_caption`, `narration_audio` lineage role로 기록된다.
- 이미지가 움직이는 범위는 계산된 클립 영역으로 제한되며 자막 좌표는 항상 그 영역 아래의 패널 안에서 계산된다.
