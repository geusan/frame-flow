# Repository Agent Rules

이 파일은 저장소 전체에 적용된다. 하위 디렉터리에 더 구체적인 `AGENTS.md`가 있으면 이 규칙과 함께 적용한다.

## Node architecture source of truth

Node 관련 작업을 시작하기 전에 다음 문서를 읽는다.

1. 기존 Node 계약화 작업: `NODE_REFACTOR_PLAN.md`
2. Workflow/Node version 설계: `docs/workflow-management-design.md`

이 저장소에서 Node는 단순한 UI template이나 `node_key` 조건문이 아니다. 모든 production Node는 공통 Node Protocol을 따르는 버전이 있는 계약이다.

```text
common Node Protocol
  └─ type-specific immutable contract: type_key@contract_version
        ├─ manifest/config schema
        ├─ typed ports
        ├─ binding policy
        ├─ executor
        └─ editor metadata
```

## Mandatory rule for new Nodes

새 Node를 추가할 때는 아래 항목을 모두 완료한다.

1. 먼저 Workflow data/execution Node인지 Canvas-only/Authoring 요소인지 분류한다.
2. Workflow Node라면 안정적인 `type_key`를 정한다.
   - 소문자 dot notation을 사용한다. 예: `image.background_remove`.
   - UI label, Provider 이름, 정확한 모델 ID를 key에 넣지 않는다.
   - 출시 후 key를 이름 정리 목적으로 변경하지 않는다.
3. 첫 `contract_version`을 `1`로 등록한다.
4. `node.definition.v1` Manifest를 작성한다.
5. Config Schema에 모든 실행 설정, 타입, 제약과 Default를 선언한다.
6. Input/Output Port를 버전이 있는 Port type ID로 선언한다.
7. Workflow 입력으로 노출할 수 있는 필드만 `x-workflow-input`으로 선언한다.
8. 공통 Executor interface를 구현하고 Executor Registry에 등록한다.
9. Generic Inspector로 표현할 수 없는 경우에만 Custom Editor를 등록한다.
10. Artifact type/schema, lineage role, retry/error와 비용 기록 계약을 정의한다.
11. Contract, Executor, Local/Temporal parity와 Web integration 테스트를 추가한다.

Node Registry 기반이 아직 구현되지 않은 단계라면 신규 Node를 기존 하드코딩 방식으로만 추가하지 않는다. 필요한 Registry/Manifest/Adapter의 최소 vertical slice를 `NODE_REFACTOR_PLAN.md` 순서에 맞춰 먼저 구현한다. 전환 호환을 위해 기존 경로 수정이 필요하면 Manifest를 Source of Truth로 만들고 Legacy wiring은 명시적인 Adapter로 제한한다.

## Canvas-only elements and Workflow annotations

Canvas에 표시된다는 이유만으로 모든 요소를 Workflow Node로 만들지 않는다.

| 요소 | 분류 | Publish 규칙 |
| --- | --- | --- |
| Sticky/memo | WorkflowAnnotation | execution graph에서 제외하고 Annotation으로 저장 |
| Folder/group | Canvas layout | Draft에만 유지 |
| Upload UI | Authoring tool | 완료된 Typed Artifact source로 변환, 미완료 Publish 거부 |
| Drawing editor | Authoring tool | 저장된 Image Artifact source로 변환, 편집 문서는 Draft-only |
| Legacy text note | Legacy adapter | Sticky/Annotation으로 변환 |

게시된 WorkflowVersion의 Node/Edge/Config는 읽기 전용이다. Publish 후 Canvas를 잠그거나 기존 Version을 Unlock하지 않는다. Canvas는 `Based on vN`인 편집 가능한 Draft로 계속 유지하고, 변경 사항은 새 WorkflowVersion으로 Publish한다.

WorkflowAnnotation은 Definition 또는 Version에 연결된 별도 mutable record다. Annotation 변경은 다음 값에 포함하지 않는다.

- WorkflowVersion content hash
- Workflow input/binding contract
- Cache key와 비용 계산
- resolved graph와 Run payload
- NodeRun 진행률

Version Viewer에서는 Frozen graph와 editable Annotation Layer를 겹쳐 표시한다. 그래프 설정 변경은 `Edit as draft`를 통해서만 수행한다.

Workflow Publish 시 선언된 Primary/Secondary output에서 역방향으로 도달 가능한 Node만 execution graph에 포함한다. 연결되지 않은 Node와 미선언 Side branch는 경고 후 제외한다. 의도적인 추가 결과는 Secondary output 또는 명시적으로 허용된 side effect contract로 선언한다.

## Node Manifest requirements

Manifest에는 최소한 다음 정보가 있어야 한다.

```text
schema_version
type_key
contract_version
lifecycle
display
ports
config_schema
binding_policy
execution
editor
artifact_contract
```

Registry는 애플리케이션 시작 또는 테스트 시 다음을 검증해야 한다.

- `(type_key, contract_version)` 유일성
- Config Schema 유효성
- 모든 Port type 등록 여부
- Executor와 Custom Editor 참조 존재 여부
- `x-workflow-input`과 대상 Config type 호환성
- Human gate의 approval schema 존재 여부

Manifest Default는 새 Node 생성 시에만 사용한다. Canvas 저장 및 Workflow Publish 시에는 모든 실행 관련 Default를 Config에 명시적으로 Materialize한다.

## Common protocol versus individual contracts

모든 Node는 같은 공통 Protocol과 Executor envelope를 사용하지만 같은 Config/Port 계약을 공유하는 것은 아니다.

```text
video.generate@1
video.generate@2
subtitle.align@1
image.background_remove@1
```

WorkflowVersion은 각 Node의 `type_key`, `contract_version`, `definition_digest`를 고정한다. 새 Node나 새 contract version을 Registry에 추가해도 기존 WorkflowVersion을 다시 해석하거나 수정해서는 안 된다.

WorkflowRun은 다음 Runtime 값을 별도로 Snapshot한다.

- Executor revision
- Node Definition digest
- Provider와 exact model ID
- Renderer/FFmpeg revision
- normalized config

## Single-responsibility Node rule

모든 production Node는 사용자 관점에서 하나의 명확한 변환 책임만 가진다. 서로 독립적으로 편집·재사용·검증할 수 있는 단계는 Typed Artifact와 Edge로 분리한다.

- Motion 편집, Frame/Clip 적용, 장면 연결, 자막 영역, Audio mux를 한 Node Config나 Executor에 함께 넣지 않는다.
- Node의 Config에는 그 Node 출력 의미를 결정하는 설정만 둔다.
- 중간 결과가 독립적으로 미리보기·재실행·Cache될 가치가 있으면 별도 versioned Port type과 Artifact 계약으로 출력한다.
- 최종 합성 Node는 이미 준비된 Video, Caption/Layout, Audio Track을 결합하는 책임만 가지며 상위 단계의 Motion, Crop, 장면 순서를 다시 해석하지 않는다.
- `execution.kind=composite`는 외부에서 하나의 원자적 capability로 취급해야 하고 부분 결과를 독립적으로 편집하거나 재사용할 수 없는 경우에만 사용한다.

이미 여러 책임을 가진 기존 계약은 in-place로 의미를 변경하지 않는다. 기존 Version 실행을 유지하고, 책임별 새 `type_key@contract_version`과 명시적인 Draft migration 경로를 제공한다.

## Changing an existing Node

기존 Node를 변경하기 전에 변경을 호환 또는 Breaking으로 분류한다.

같은 contract version에서 허용되는 변경:

- 설명, 아이콘, 도움말과 검색 keyword
- 계약상 동작을 바꾸지 않는 Executor 버그 수정
- 비계약 metadata나 관측성 추가

새 contract version이 필요한 변경:

- 필수 Config 추가
- Config type, 범위, Default 적용 의미 변경
- 기존 Config 또는 Binding path 제거/이름 변경
- Input/Output Port 추가, 제거, type 또는 cardinality 변경
- 다중 입력 순서 의미 변경
- Artifact type/schema 또는 출력 의미 변경
- Human gate/실행 의미 변경

Breaking 변경 시 다음을 모두 수행한다.

1. 기존 Definition을 수정하지 않고 새 `contract_version`을 등록한다.
2. Draft용 Config/Binding migration을 제공하거나 수동 교체가 필요함을 명시한다.
3. Migration 전후 Diff와 warning을 반환한다.
4. 기존 contract version의 조회와 실행 테스트를 유지한다.
5. Upgrade는 Draft에만 적용하고 새 WorkflowVersion Publish를 요구한다.

게시된 WorkflowVersion, 기존 Run Snapshot 또는 과거 Artifact를 in-place migration하지 않는다.

## Node lifecycle

Node lifecycle은 다음 의미를 지킨다.

| 상태 | 규칙 |
| --- | --- |
| `ACTIVE` | 새 Canvas, Publish와 Run 허용 |
| `DEPRECATED` | 새 Library에서 기본 숨김, 기존 Workflow Run 허용, 대체 경로 제공 |
| `RETIRED` | 신규 사용/Publish 금지, 기존 조회 유지, Run은 명시된 정책 적용 |
| `BLOCKED` | 보안·권리 문제로 신규/기존 Run 금지, 과거 조회 유지 |

사용 중인 Node Definition이나 Executor를 파일에서 바로 삭제하지 않는다. 사용 현황, 대체 Node, Migration과 lifecycle 변경을 먼저 제공한다.

## Executor rules

모든 Atomic Node Executor는 공통 호출 계약을 지킨다.

```text
execute(execution_context, resolved_node_config, typed_inputs)
  -> NodeExecutionResult
```

Local engine과 Temporal Activity는 같은 Executor Registry와 dispatch 함수를 사용한다.

Provider Adapter는 UI Node key를 기준으로 분기하지 않는다. Provider Adapter는 image generation, text generation, speech synthesis 같은 capability를 구현한다. Node Executor가 Node Config를 Provider request로 변환하고 Provider 결과를 Node output/Artifact 계약으로 변환한다.

Human input이 필요한 Node는 특정 `node_key` 조건문 대신 Manifest의 `execution.kind=human_gate`와 versioned approval schema를 사용한다.

## Web rules for Nodes

- Node Library의 Source of Truth를 `nodeTemplates` 같은 별도 수동 목록에 추가하지 않는다.
- Canvas Node 카드에는 직렬화된 JSON/Raw payload를 직접 표시하지 않는다. Image, Video, Audio, Motion, Layout 등 타입에 맞는 시각 Preview를 우선하고, 알 수 없는 구조화 데이터는 Schema와 상태를 요약한다.
- Node Detail은 공통 `UI`와 `Raw data` 탭을 제공한다. `UI` 탭이 Custom/Generic Editor를 포함하는 유일한 수정 Surface이며 `Raw data` 탭은 Config, Runtime Snapshot과 Output을 읽기 전용으로 표시한다.
- Raw payload를 확인하기 위해 Node별 별도 JSON UI를 추가하지 않는다. 공통 `Raw data` 탭을 사용한다.
- 일반 Config UI는 Manifest Config Schema에서 생성한다.
- Workflow input UI는 `x-workflow-input`에서 생성한다.
- Port handle과 연결 검증은 Registry Port 계약을 사용한다.
- Provider/model 선택지는 Node key 분기가 아니라 capability metadata에서 생성한다.
- Asset picker, Drawing Canvas, Caption layout처럼 복잡한 상호작용만 Custom Editor를 사용한다.
- Custom Editor가 없거나 로드되지 않아도 Generic 또는 read-only Fallback으로 Canvas/Workflow를 열 수 있어야 한다.
- Custom Editor map 이외에 신규 Node key 조건문을 UI에 추가하지 않는다.
- Published Version Viewer의 graph는 read-only이고 Annotation overlay만 편집 가능해야 한다.

전환 기간에 Legacy `nodeTemplates` 또는 Inspector 분기를 수정해야 한다면 같은 PR에서 Manifest를 추가하고, Legacy 수정 이유와 제거 Phase를 명시한다.

## Port and binding rules

- Canonical Port type은 `media.video.v1`, `prompt.text.v1`처럼 버전이 있는 ID를 사용한다.
- 서로 다른 Port type을 암묵적으로 연결하지 않는다.
- 변환이 필요하면 명시적인 Adapter Node를 사용한다.
- Workflow variable binding은 Manifest의 `x-workflow-input` 허용 필드만 대상으로 한다.
- Node ID/type, Edge, execution kind, credentials와 Runtime state는 변수화하지 않는다.
- 임의 JavaScript/Python/JSONPath 실행을 Binding 기능으로 추가하지 않는다.

## Required tests for Node work

신규 또는 변경 Node PR에는 영향 범위에 따라 다음 테스트가 있어야 한다.

- Manifest Schema와 digest Snapshot
- Config Default/validation/binding
- Port compatibility
- Executor normalized request와 result contract
- Artifact type/schema/lineage
- Cache key와 request hash
- Retryable/non-retryable error
- Local/Temporal parity
- Registry 기반 Library/Inspector
- 기존 contract version compatibility
- Legacy Canvas load가 영향을 받는 경우 round-trip fixture
- Canvas-only 요소의 Publish normalization
- Output reverse reachability와 unused branch 제외
- Annotation 수정 전후 Version hash/Run payload 불변
- Frozen Version Viewer와 editable Annotation overlay

Fixture executor도 production executor와 같은 `NodeExecutionResult` 계약을 사용한다. 테스트 편의를 위해 별도 의미를 가진 결과 계약을 만들지 않는다.

## Prohibited patterns

Node 작업에서 다음 패턴을 새로 도입하지 않는다.

- Manifest 없는 production Node key
- 중앙 `if/elif` 또는 `switch`에 Node key를 추가하는 실행 dispatch
- Web과 API에 복제된 Node Default/Port 목록
- 모든 Node 설정을 한 개의 Optional field interface에 계속 추가하는 방식
- Provider layer가 Canvas Node UI 의미를 직접 해석하는 방식
- 게시된 WorkflowVersion에 Registry 최신 Default를 다시 적용하는 방식
- 기존 Node contract를 덮어쓰고 버전만 유지하는 방식
- Unknown Node를 로드 중 삭제하거나 Edge를 자동 유실하는 방식
- 기존 Artifact 또는 Run Snapshot을 새 Node 계약으로 덮어쓰는 방식
- Sticky, Folder, Upload UI 또는 Drawing editor를 실행 NodeRun으로 취급하는 방식
- Annotation을 WorkflowVersion graph/content hash/Cache key에 저장하는 방식
- Publish 후 Canvas를 잠그고 Unlock으로 기존 Version을 수정하는 방식
- 선언된 Output과 무관한 모든 Canvas Node를 Workflow Run에 복사하는 방식

## Definition of done for a new Node

새 Node 작업은 아래 조건을 모두 만족해야 완료다.

- Manifest와 `type_key@contract_version`이 Registry에 등록됐다.
- Generic Inspector 또는 명시적인 Custom Editor로 편집할 수 있다.
- Config와 Port가 Schema로 검증된다.
- 허용된 필드는 Workflow input으로 노출할 수 있다.
- Local과 Temporal이 같은 Executor를 사용한다.
- Run이 Definition/Executor/Model revision을 Snapshot한다.
- Artifact와 Lineage 계약이 기록된다.
- 기존 WorkflowVersion과 기존 Node contract 테스트가 통과한다.
- 선언된 Workflow output에 도달하는 경우에만 execution graph에 포함된다.
- Canvas-only/Authoring 요소라면 Annotation/layout/Artifact normalization 경로가 구현됐다.
- 관련 문서와 `NODE_REFACTOR_PLAN.md` 진행 상태가 필요하면 갱신됐다.
