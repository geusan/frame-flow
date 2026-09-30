# 플랫폼 계약화 마무리 — 2026-09-18

범위: Node 전환 Phase 3~7과 Workflow 설계 Phase 1~4의 작성·게시·실행 흐름.
멀티사용자 인증, Workspace 격리, 암호화된 사용자별 BYOK, Hosted 운영은 별도 M2/M5 범위다.

## 구현 결과

| 항목 | 구현 및 검증 |
| --- | --- |
| Canonical 저장·조회 | `canvas.document.v1`을 직접 Schema/Config/Digest 검증한다. API `document`와 Web projection을 연결했다. Runtime/editor 값이 Config를 덮어쓸 수 없다. |
| 과거 Canvas | 버전 미지정 Legacy Node는 @1로 읽는다. Unknown Node, 삭제된 plugin key, 연결과 Port ID를 로드 중 삭제하거나 바꾸지 않는다. |
| Library | production 수동 `legacyNodeTemplates`를 제거했다. ACTIVE Manifest만 새 Library에 노출하고 조회에는 과거 lifecycle/version도 사용할 수 있다. |
| Executor | 사용되지 않는 중앙 `execute_canvas_operation`과 `LOCAL_MODELS`를 제거했다. 실제 실행은 공통 Registry를 사용하며 media helper는 infrastructure에서 사용한다. |
| Workflow 입력 | 입력 추가·이름 변경·재사용, 여러 입력을 포함한 문자열 템플릿과 binding 대상 선택을 제공한다. 이름 변경 시 token도 같이 변경한다. |
| Binding 검증 | 허용된 Config 필드, 타입, 중복 target, token 선언을 검증한다. 입력값 속 token은 재해석하지 않는다. 값 없는 optional binding은 명확한 오류다. |
| Workflow 출력 | Primary 하나와 여러 Secondary 결과를 Node/Port 단위로 선택한다. 결과에서 역방향 도달 가능한 graph만 검증·게시한다. 미사용 가지의 cycle/Unknown Node는 Draft에 보존하고 게시에서 제외한다. |
| Typed output | Manifest의 보조 output handle을 표시한다. 명시적 source/output Port 선택은 해당 타입 Artifact만 전달·반환한다. 구버전의 암묵적 output bundle 의미는 유지한다. |
| 게시 UX | 게시 검토, Release notes, 서버 검증 오류를 제공한다. 게시 후에도 Draft를 계속 편집한다. |
| Version 관리 | 저장된 Version 간 Node/Config/Edge/Input/Binding/Output diff를 표시한다. mutable Annotation은 비교 대상에서 제외한다. |
| Edit as draft | 선택한 Version으로 새 Canvas Draft를 생성한다. 기존 Draft는 별도 Canvas로 보존한다. optimistic revision과 Canvas ID를 검사하고 기존 Version/Run/Artifact는 변경하지 않는다. |
| Lifecycle | BLOCKED와 실행 정책이 없는 RETIRED 실행은 거부한다. DEPRECATED 조회·기존 실행은 유지한다. |
| 회귀 방지 | production 수동 목록, destructive load, 중앙 legacy dispatch 재도입을 검사한다. Workflow Web 로직 테스트를 CI에 추가했다. |

## 유지하는 호환 경계

- `legacy-compatibility`는 기존 Manifest에 고정된 Executor 이름이다. 이름을 삭제하거나 Definition digest를 변경하지 않고 capability Registry에 연결한다.
- 구버전 HTTP의 `nodes/edges` 요청은 입력 Adapter에서 Canonical 문서로 전환한다. 현재 Web의 조회·저장은 Canonical 문서를 사용한다.
- 기존 Temporal/Run snapshot은 React Flow 형태다. 실행 DTO projection과 과거 Signal Adapter를 유지한다. 저장된 Run/Artifact를 일괄 migration하지 않는다.
- 기존 Custom Editor의 camelCase 필드는 명시적인 read/write projection에서만 유지한다. 새 Generic Node의 설정은 Manifest Config Schema가 기준이다.
- 전체 사용자 Canvas와 외부 클라이언트의 전환 여부를 확인하지 않고 Legacy API를 제거하지 않는다. 호환 지원 종료는 별도 release/deprecation 작업이다.

## 검증

- API 전체 pytest 317개 통과 (다중 Port 실행 입력 회귀 포함)
- Worker 전체 pytest 5개 통과
- Web typecheck, ESLint, UI architecture guard, production build
- `npm run test:workflow-contract --workspace apps/web`
- 격리된 SQLite/memory/fixture API와 개발 Web에서 브라우저 확인:
  - 두 입력의 Prompt template, 입력 rename에 따른 token 변경
  - Primary/Secondary output과 제외 Node 표시
  - Release notes를 포함한 게시 성공
  - Frozen Version → 새 Draft, 기존 Draft 별도 보존

테스트의 Provider는 fixture/mock이다. 이 작업으로 실제 유료 Provider 호출이나 장시간 Temporal/Blender 운영 검증을 추가했다고 주장하지 않는다.

## 다음 제품화 단계

`open-source-requirements.md`의 M2(인증/Workspace/BYOK), M3의 browser batch upload·Skill sandbox,
M5(Hosted stack/Quota/백업·복구)를 별도 범위로 진행한다. 아바타의 시각 품질 연구도 이 완료 범위에 포함하지 않는다.
