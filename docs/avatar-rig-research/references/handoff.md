# 다음 세션 인계 — 2026-09-09

## 최신 추가 — E14 (2026-09-09)

**0° 앞뒤 표시 순서 검사: 피부 연결 실패 유지.** 고정 팔/몸통 영역을 팔 앞과 몸통 앞 두 순서로 그려도 작은 틈은 남는다. 겹침 약 382.25px², 순서별 포함 영역 차이 0. 두 표면 모두 포함하지 않는 닫힌 빈 영역 약 2px²가 `[611.19,397.88]` 근처에 있다. 수치는 고정 격자 근사다.

- 화면: **http://localhost:3002/live-avatar/2d/shoulder/e14**. 기존 서버 사용/3000 배포 없음.
- A는 기존 단일 경계. B/C 공통 분할에는 진단용 내부 닫힘선이 추가됨. 통제 비교는 **B/C 순서만 변경**. 원래 외곽 곡선은 보존.
- 소스: `shoulder-occlusion-e14.ts`, `shoulder-occlusion-study.tsx`, 독립 route `shoulder/e14/page.tsx`. E09~E13/원화/얼굴 변경 없음.
- 검사: `node apps/web/scripts/test-shoulder-occlusion-e14.mjs` (`--record` 증거 갱신), typecheck/새 TS/TSX lint/ui:check 통과. 이것은 진단 검사 통과이며 피부 실패를 명시한다.
- 자료: 실험 노트 E14, `evidence/E14/` 단색/전체/소유권/숨은 경계/수치/해시.
- 다음 E15: **0° 위팔 안쪽–겨드랑이–옆구리의 경계 곡선 자체 수정**. 가림이나 색 채우기로 해결하지 않는다. 정지 실패로 인접 각도/왕복/의상/물리 미평가.

## 최신 추가 — E13 (2026-09-09)

**160° 목 옆 고리형 결함 개선 / 전체 어깨·겨드랑이 미검증.** 기존 외곽점의 목 대비 x 간격 -0.200466px로 E12 적용 불가를 먼저 기록했다. 별도 후보 `[585,305]`에 동일 접선/길이 정책을 적용해 국소 결함을 제거했다. 위치만 독립 변수이며 접선/길이는 규칙에 따라 재계산된 종속 결과다.

- 화면: **http://localhost:3002/live-avatar/2d/shoulder/e13**. 3000/본 화면 배포 없음.
- 신규 `shoulder-base-e13.ts`, `shoulder-attachment-e13.ts`, `shoulder-attachment-study.tsx`, route `shoulder/e13/page.tsx`. E09~E12 변경 없음.
- 검사 `node apps/web/scripts/test-shoulder-attachment-e13.mjs` (`--record` 증거 갱신), typecheck/새 TS/TSX lint/ui:check 통과. 비대상 9곡선/축/단면폭 동일, 목 구간 역행 제거.
- 자료: 실험 노트 E13, `evidence/E13/`의 소스/포즈/수치/확대/전체/제어점/해시.
- 160° 겨드랑이의 긴 전환과 전체 부피는 검증되지 않았다. 160° 전체 피부 통과 아님.
- 다음 큰 항목: **0° 팔·몸통 겹침의 경계 소유권/앞뒤 가림**. 높은 각도 겨드랑이도 추가 검토. 중간 각도·왕복·의상·물리는 아직 미평가.

## 최신 추가 — E12 (2026-09-09)

**135° 관찰된 국소 돌출 제거 확인.** E11을 보존하고 목→어깨 구간의 두 핸들 길이만 0.124957924배로 줄였다. 배율은 가로 여유/(두 핸들의 양의 x 투영 합)으로 정한다. 끝점·접선 방향·나머지 10곡선은 동일하다. 45°·90°는 배율 1로 전체 좌표가 보존된다.

- 화면: **http://localhost:3002/live-avatar/2d/shoulder/e12**. 기존 서버 사용; 3000 배포 변경 없음.
- 소스: `shoulder-handle-e12.ts`, `shoulder-handle-study.tsx`, 독립 route `shoulder/e12/page.tsx`. E09/E10/E11 수정 없음.
- 검사: `node apps/web/scripts/test-shoulder-handle-e12.mjs` (`--record`로 증거 갱신), typecheck/새 TS/TSX lint/ui:check 통과.
- 135° 목→어깨 최소 dx/dt -15.011→+1.228. 해당 곡선의 가로 역행 없음. 실제 브라우저 전체/확대에서 돌출 제거와 새 깊은 패임 없음 확인. 전체 피부 자연스러움/부피까지 통과 아님.
- 증거: `evidence/E12/`, 상세 기록: 실험 노트 E12. 수치·시각·조작 판정 분리.
- 다음은 **160° 정지 경계의 끝점 순서/접선 정책 적용 가능성** 확인. E12는 g<=0 또는 역방향 접선에 적용 불가를 명시적으로 보고한다. 0° 가림은 별도 실험. 주요 정지 자세 이후에 중간 각도/왕복, 피부 이후에 의상.

## 최신 추가 — E11 (2026-09-09)

**45° 국소 개선 / 135° 시각 실패.** E10의 접선 정책을 동일 조건으로 확장했다. 세 정지 자세 모두 G1 방향/연결점/핸들 길이/원위 단면폭 검사 통과지만 135° 목 옆 돌출은 남는다. 90°는 E10과 정확히 같은 좌표다.

- 화면: **http://localhost:3002/live-avatar/2d/shoulder/e11**. 기존 서버 사용, 3000 배포 변경 없음.
- 소스: `shoulder-tangent-e11.ts`, `shoulder-tangent-range-study.tsx`, 독립 route `shoulder/e11/page.tsx`. E09/E10 수정 없음.
- 검사: `node apps/web/scripts/test-shoulder-tangent-e11.mjs` (증거 갱신 `--record`), typecheck/변경 범위 ESLint/ui:check 통과. 수치 통과는 시각 통과가 아니다.
- 증거/포즈/해시: `evidence/E11/`. 상세 내용은 실험 노트 E11.
- 원인 후보 수정: 외곽점이 목 기준점 왼쪽으로 넘어간 것은 아니다. 가로 간격 +2.78px 구간에 18.26px 출발 핸들이 남아 곡선이 나갔다가 되돌아온다.
- 다음 E12: **135° 고정, 연결점·접선 방향 유지, 목→어깨 구간 핸들 길이만 제한**. 두께/패임도 검사. 중간 각도·왕복·의상·물리 평가 미실시.

## 최신 추가 — E10 (2026-09-09)

**90° 국소 연결 개선 확인 / 전체 피부 자연스러움 미검증.** E09 B의 연결점과 핸들 길이를 그대로 두고 여섯 연결점의 접선 방향만 정렬했다. 작은 어깨 돌출과 겨드랑이 모서리가 줄었다. 최대 방향 차이는 72.919°→계산 오차 이내 0°, 실제 원위 위팔 단면폭은 동일하다.

- 화면: **http://localhost:3002/live-avatar/2d/shoulder/e10**. 3002 서버가 중지되어 새로 시작했다. 3000 Docker 배포는 변경하지 않았다.
- `shoulder-tangent-e10.ts`는 **90° 전용**이다. 각도 보간기가 아니다. E08/E09/원화/얼굴/기존 화면 코드는 변경하지 않았다.
- 노트: [실험 노트 E10](experiments.md#e10--90-연결점의-접선-방향만-정렬-2026-09-09). `evidence/E10/`에 비교군 소스, 포즈 좌표, 수치, 전체/확대/제어점 증거와 해시가 있다.
- 검사: `node apps/web/scripts/test-shoulder-tangent-e10.mjs` (증거 갱신은 `--record`), web typecheck/변경 범위 ESLint/ui:check 통과.
- 시각은 에이전트의 국소 개선 관찰이며 사용자 승인/해부학적 정답 아님. 곡률·내부 피부·앞뒤 겨드랑이·접촉·동작 성능은 미검증.
- 다음 E11: 같은 정책의 **45°·135° 정지 비교**. 연결점/핸들 길이/뼈/밀도를 동시에 바꾸지 않는다. 0° 가림은 별도 가설. 중간 각도/왕복/의상은 주요 정지 자세 이후.

## 최신 추가 — E09 (2026-09-09)

E09 단색 경계 실험을 수행했으며 **A/B/C 모두 정지 형태 실패**다. 0° 경계 교차, 90° 돌출/각짐, 135°·160° 패임/루프가 남는다. 상세 기록은 [실험 노트 E09](experiments.md#e09--단색-경계-제어의-단계별-비교-2026-09-09), 증거·소스 스냅샷은 `evidence/E09/`에 있다.

- E08/원화/얼굴/기존 본 화면 유지. E08 스냅샷은 `evidence/E09/E08-source.tar.gz`와 `baseline.json`.
- 신규 독립 route: **http://localhost:3002/live-avatar/2d/shoulder/e09**. 기존 3002 개발 서버에서 확인했다. 3000 Docker에는 배포하지 않았다.
- 코드: `shoulder-contour-e09.ts`, `shoulder-contour-study.tsx`, `.module.css`, route `shoulder/e09/page.tsx`; 검사 `node apps/web/scripts/test-shoulder-contour-e09.mjs`.
- 동일 11곡선/176경계표본에서 A 최소→B 역할 제어→C 희소 자세 보정을 비교했다. 내부 피부 메쉬는 없으며 E08와 직접적인 단일 변수 A/B가 아니다.
- 수치 프로토콜 검사/typecheck/변경 범위 ESLint/ui:check 통과. 기하/시각 실패는 그대로 보고한다. 정지 실패로 중간 각도/왕복/조작 성능/의상/물리는 평가하지 않았다.
- 다음은 검수된 90° 기준 곡선과 접선 연결을 먼저 만드는 E10 제안. E09 키는 정답이 아니며 C의 실패를 자세별 보정 기법 일반의 실패로 확대하지 않는다.

아래는 E09 이전 인계 기록이다. 마지막의 세션 종료 지시는 그 문서 작성 세션에만 해당한다.

## 먼저 읽을 것

1. [SKILL.md](../SKILL.md): 재사용할 연구 절차. 설치되지 않은 문서 초안이다.
2. [실험 노트](experiments.md): 실패 이력, 사용자 증거, 미검증 가설, 다음 실험.
3. [최신 사용자 실패 이미지](evidence/03-stretched-armpit.png).
4. 저장소 루트 `AGENTS.md`, 작업 경로 하위 규칙. `apps/web/AGENTS.md`는 관련 Next.js 로컬 문서를 먼저 읽도록 요구한다.

## 현재 상태를 오해하지 말 것

- 사용자는 최신 결과를 부자연스럽다고 판정했다. 어깨/겨드랑이 시각 품질은 **실패** 상태다.
- 어깨와 옷의 수치 검사를 통과했어도 자연스러움은 확보하지 못했다.
- 최신 분석의 제안(역할별 보조 제어, 검수된 자세별 보정, 의상 접촉, 내부 3D 형태, 물리)은 대부분 미구현·미검증이다.
- 다음 목표는 왼쪽 어깨의 단색 기준 형태와 최소 리그 비교 실험이다. 또 다른 틈 메우기/색 채우기 보정부터 시작하지 않는다.
- 이 정리 세션에서는 문서와 증거만 작성했다. 앱 코드를 새로 수정하거나 배포하지 않았다. 이전 결과를 새로 통과 판정하지 않았다.

## 저장소 및 작업 트리

문서 작성 시 실제 조회 값:

- 경로: `/Users/geusan/workspaces/projects/video-canvas`
- 브랜치: `main`
- HEAD: `e18ed2d5d17fbb0612290796d827299ff2ff67b9`
- 다수의 tracked 수정과 untracked 파일이 있다. 현재 실험 코드는 HEAD만 체크아웃해서 재현되지 않는다.
- `apps/web/src/features/avatar-2d/`, 관련 route, public assets, 여러 테스트/문서는 untracked 상태였다.
- Node/Tripo/Canvas/얼굴 리그 관련 다른 작업도 섞여 있다. 전체 reset, clean, checkout, 무차별 커밋을 하지 않는다. 다음 세션에서 상태를 다시 확인하고 대상 변경을 분리한다.

문서 작성 시 SHA-256:

| 파일 | 해시 |
| --- | --- |
| `apps/web/public/avatars/cat-2d-v1/base.png` | `cf8192ed7f3be78f1a22022fc0bb173c842cfc3b7eeb4592c4387515c563b42b` |
| `apps/web/src/features/avatar-2d/shoulder-surface.ts` | `e5c7a9619b9aa5f258d0bfbfc71f7abdc8e52a8efe88f5c5725e88cde0408656` |
| `apps/web/src/features/avatar-2d/shoulder-garment.ts` | `333764dc0da338d46650b94654f56d50c529d3dba29f266a57bd2af9666fd5cf` |
| `apps/web/src/features/avatar-2d/shoulder-lab-model.ts` | `c6d8fc3254c78dca23a37d8bd4aa1a436fb4a3264bbcf82c337475136b8da59a` |

해시는 비교를 위한 것이며 파일이 이후 바뀌면 최신 사용자 작업을 우선한다.

## 주요 코드와 자료

저장소 루트 기준 경로:

| 경로 | 역할 |
| --- | --- |
| `apps/web/src/features/avatar-2d/rig.ts` | 기준 관절, pose, 입력 처리, 목 변형 |
| `apps/web/src/features/avatar-2d/parts.ts` | 원화 영역 마스크 |
| `apps/web/src/features/avatar-2d/artwork-partition.ts` | 원본 머리/몸 픽셀 분리 |
| `apps/web/src/features/avatar-2d/puppet-scene.ts` | Three.js 렌더링, 레이어, 조명, 연결 실험 옵션 |
| `apps/web/src/features/avatar-2d/shoulder-lab-model.ts` | 한 축 수동 입력과 어깨 상승 규칙 |
| `apps/web/src/features/avatar-2d/shoulder-surface.ts` | ARAP, 삼각형 처리, 겨드랑이 보정, 의상 이동 함수 |
| `apps/web/src/features/avatar-2d/shoulder-garment.ts` | 옷 표면 분리와 피부색 underpaint |
| `apps/web/src/features/avatar-2d/shoulder-lab.tsx` | 수동 실험 UI, 확대/단색/메쉬/메모 |
| `apps/web/src/features/avatar-2d/avatar-studio.tsx` | 본 2D 스튜디오; 얼굴 작업이 함께 진행되었으므로 보존 |
| `apps/web/scripts/test-shoulder-lab.mjs` | 실제 TS 모델·메쉬 검사 |
| `apps/web/scripts/test-avatar-2d.mjs` | 기존 854프레임 검사 |
| `docs/left-shoulder-lab.md` | 기존 구현 설명; 최신 실패 판정은 본 연구 노트를 우선 |
| `docs/avatar-2d.md` | 기존 2D 파이프라인 설명 |
| `apps/web/public/avatars/cat-2d-v1/base.png` | 원래 1024×1536 캐릭터 원화 |
| `apps/web/public/avatars/cat-2d-v1/body-underpaint-v2.png` | 기존 몸통 보충 이미지 |
| `apps/web/public/avatars/cat-2d-v1/head-isolated-v2.png` | 과거 볼륨 증가 문제가 있던 생성 머리; 다시 사용하지 않음 |
| `apps/web/public/avatars/cat-2d-v1/reference-motion.json` | 참고 영상에서 추출된 854프레임 입력 자료 |

기준 관절(원화 좌표, x 오른쪽/y 아래): chest `[512,421]`, neck `[512,311]`, leftShoulder `[623,346]`, leftElbow `[687,526]`, leftWrist `[763,732]`. 현재 좌표 역시 검증 대상이다.

## 실행 표면과 로컬 데이터

- 사용자 표면: `http://localhost:3000/live-avatar/2d/shoulder`
- 본 스튜디오: `http://localhost:3000/live-avatar/2d`
- 기존 개발 서버: `http://localhost:3002/live-avatar/2d/shoulder` — 이전 턴에서 사용했다. 다음 세션에서 가용성을 재확인하고 임의로 종료하지 않는다.
- API: `http://localhost:8000`
- 참고 영상: `http://localhost:3000/asset/videos/art_d78356242bc4494495`
- 과거 3D Canvas: `canvas_ba7bd9338370426d9a`; 현재 한 축 2D 실험과 혼동하지 않는다.
- `connectedLeftShoulder` 옵션은 실험실에서만 켠다. 본 스튜디오 전체에 일반화하지 않았다.
- 메모 localStorage: `frameflow.shoulder-lab.left.v1`; 형식 `avatar.shoulder_review.v1`. 같은 브라우저/오리진에 종속되므로 자동으로 다른 환경에 이전되지 않는다.
- 사용자 제공 이미지 3장은 `evidence/`에 보존했다. 브라우저에서 만든 모든 중간 결과/영상이 보존된 것은 아니다.

## 검사 명령과 한계

루트에서 필요한 범위만 실행한다.

```sh
npm run test:shoulder-lab --workspace apps/web
npm run test:avatar-2d --workspace apps/web
npm run typecheck --workspace apps/web
npm run lint --workspace apps/web
npm run ui:check --workspace apps/web
npm run build --workspace apps/web
```

마지막 앱 수정 턴에서 통과했다. 문서 정리 중에는 재실행하지 않았다. 세부 한계는 실험 노트의 검사 절을 읽는다. 새 실험에서는 시각 평가와 조작 성능을 별도로 검증한다.

## 로컬 배포 주의 사항

현재 조회한 `video-canvas-web-1` 이미지:
`sha256:bfb66e4befe45f600db772759f6b84a645f21ba1ca0b8d33561f5c72288aab0c`

Docker 내부 파일시스템은 58.4GB 중 약 54.6GB 사용, 일반 가용 공간 약 763.8MB로 표시됐다. 과거 대규모 빌드로 디스크 부족 문제가 있었다. 다음 세션에서 공간과 현재 이미지부터 다시 확인한다. DB 볼륨이나 사용 중인 서비스를 정리 대상으로 삼지 않는다.

이전 배포는 호스트에서 Next 빌드 후 현재 web 이미지 위에 `.next`와 `src`만 추가하는 약 30MB 증분 빌드였다. `.next/dev`, `cache`, `types`는 제외했다. 전체 `docker compose build web`을 습관적으로 실행하지 않는다. 이 문서는 배포를 새로 요청하는 것이 아니다.

이전 임시 컨텍스트는 루트 `output/shoulder-connection/deploy/`, `output/shoulder-garment/deploy/`에 있다. 재사용한다면 오래된 빌드 산출물/소스가 섞이지 않도록 새 컨텍스트를 만들거나 정확히 동기화한다. 새 코드가 새 public asset을 참조하면 해당 자산도 포함해야 한다.

## 다음 세션의 첫 산출물

1. 최신 실패 이미지와 코드를 읽고 “관찰된 실패 / 원인 가설 / 이번에 바꿀 변수”를 짧게 정리한다.
2. 현 상태를 비교군으로 보존하고, 옷·음영을 숨긴 왼쪽 어깨의 기준 윤곽/접힘을 정의한다.
3. 첫 후보의 최소 리그와 영향 영역을 설명하고, 비교 가능한 한 가지 실험을 수행한다.
4. 연구 노트에 별도 실험 ID와 근거를 추가한다. 기존 실패를 성공으로 덮어쓰지 않는다.

사용자는 이 문서 작성 후 세션을 마무리하고 다음 세션에서 연구를 재개하기를 요청했다. 이 세션에서 추가 구현·리깅·물리 도입 작업을 시작하지 않는다.
