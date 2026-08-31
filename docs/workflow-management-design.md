# Canvas 변수화와 Workflow 관리 설계

Status: Proposed
작성 기준: 2026-08-31
범위: 설계만 포함하며 Migration, API, UI 구현은 포함하지 않는다.

## 1. 결론

Frameflow에서는 다음 다섯 개념을 분리한다.

| 개념 | 역할 | 변경 가능 여부 |
| --- | --- | --- |
| Canvas | 그래프를 만들고 실험하는 작업 초안 | 가능 |
| Workflow | 이름, 설명, 상태를 가지는 재사용 가능한 논리 단위 | 메타데이터만 가능 |
| WorkflowVersion | 그래프, 입력 계약, 출력 계약을 함께 게시한 버전 | 불가능 |
| WorkflowRun | 특정 WorkflowVersion에 입력값을 적용해 실행한 기록 | 불가능 |
| WorkflowAnnotation | 게시된 Version 위에 표시하는 운영 메모 | 가능 |

핵심 실행식은 다음과 같다.

```text
WorkflowRun = immutable WorkflowVersion + validated inputs + runtime snapshots
```

Canvas를 그대로 Workflow로 이름만 바꾸거나, 실행할 때마다 브라우저가 그래프 전체를 보내는 방식은 사용하지 않는다. Canvas에서 `Publish`할 때 서버가 실행 상태와 Canvas 전용 요소를 제거한 정규 WorkflowVersion을 만들고, 이후 실행은 반드시 서버에 저장된 버전을 기준으로 한다.

Canvas는 Publish 후에도 잠그지 않는다. 게시 시점의 WorkflowVersion만 불변이며 Canvas는 해당 Version을 기반으로 계속 편집할 수 있다. 게시된 그래프는 읽기 전용으로 보되 메모는 WorkflowAnnotation이라는 별도 Layer에서 수정한다.

## 2. 현재 구조와 해결해야 할 문제

현재는 다음과 같이 동작한다.

```text
canvases.graph_json
  └─ React Flow 노드 + 설정 + 실행 상태 + 최근 결과
          │
          └─ POST /canvas-runs로 브라우저가 전체 그래프 전달
                         │
                         └─ canvas_runs.graph_snapshot
```

현재 구조는 Canvas 편집과 실행에는 적합하지만 재사용 Workflow 관리에는 다음 한계가 있다.

1. 노드 정의와 `status`, `output`, 로그, 최근 Artifact 같은 실행 상태가 같은 문서에 들어 있다.
2. 어떤 설정을 실행 시 입력받아야 하는지 표현하는 계약이 없다.
3. 게시된 버전이 없어 Canvas 편집이 향후 실행 내용까지 바꿀 수 있다.
4. 실행 요청이 서버 저장 버전이 아니라 클라이언트가 보낸 그래프를 신뢰한다.
5. 이전 실행이 어떤 Workflow 버전과 입력으로 만들어졌는지 직접 조회할 수 없다.
6. 현재 `/workflows` 화면은 실제로는 Canvas 문서 목록이어서 제품 용어가 섞여 있다.

이미 채택된 원칙은 유지한다.

- PostgreSQL이 Workflow, Version, Run의 기준이다.
- Temporal은 정의 저장소가 아니라 실행 내구성 계층이다.
- Artifact와 Run Snapshot은 불변이다.
- Workflow에는 논리 모델 별칭을 저장하고 정확한 모델 ID는 Run에 Snapshot한다.

## 3. 목표와 비목표

### 목표

- Canvas의 Prompt, Asset, 모델 별칭, 영상 길이 같은 일부 설정을 Workflow 입력으로 노출한다.
- 입력 타입과 제약으로 실행 전 값을 검증한다.
- 게시된 WorkflowVersion을 불변으로 보관한다.
- 같은 버전을 서로 다른 입력으로 반복 실행한다.
- Draft, Version, Run, 성공률과 비용을 한곳에서 관리한다.
- 기존 Canvas DAG와 Local/Temporal 실행기를 재사용한다.
- 과거 실행을 정확히 재현하고 감사할 수 있게 한다.
- 게시된 WorkflowVersion의 그래프를 당시 상태 그대로 조회한다.
- 게시된 그래프를 바꾸지 않고 Version/Node별 메모를 계속 관리한다.

### V1 비목표

- 입력값으로 노드나 Edge를 추가·삭제하는 동적 그래프
- 조건 분기, 반복문, 서브 Workflow
- JavaScript, Python, JSONPath 같은 임의 표현식 실행
- Provider API Key와 같은 Secret의 Workflow 입력화
- 여러 사용자의 동시 Canvas 편집과 그래프 Merge
- Scheduler, Webhook, 외부 공개 API Key 관리
- Workflow 간 Package import/export

## 4. 도메인 모델

### 4.1 Canvas

Canvas는 계속 자동 저장되는 편집 문서다. 독립 실험용 Canvas일 수도 있고 특정 Workflow의 Draft일 수도 있다.

추가할 속성은 다음과 같다.

- `workflow_definition_id`: 연결된 Workflow, 없으면 독립 Canvas
- `base_version_id`: 이 Draft를 시작한 Version
- `revision`: 그래프, 설정, 계약 변경의 자동 저장 충돌 감지를 위한 증가값
- `draft_contract_json`: 아직 게시하지 않은 입력, 바인딩, 출력 계약

V1에서는 하나의 Workflow에 하나의 활성 Draft Canvas만 둔다. 게시 후에도 같은 Canvas에서 편집을 이어가며, 다시 게시하면 다음 Version이 만들어진다.

Publish는 Canvas를 잠그지 않는다. Canvas에는 `Based on vN`과 `Unpublished changes` 상태만 표시한다. 사용자가 Lock/Unlock을 수행하는 UX는 만들지 않는다.

### 4.2 WorkflowDefinition

사용자가 목록에서 관리하는 논리 Workflow다.

```text
WorkflowDefinition
- id
- name
- description
- status: ACTIVE | ARCHIVED
- draft_canvas_id
- current_version_id
- tags
- created_at / updated_at
```

Definition 자체에는 실행 그래프를 저장하지 않는다. 실행 가능한 내용은 항상 Version에 있다.

### 4.3 WorkflowVersion

Publish 시 한 번 생성되는 불변 레코드다.

```text
WorkflowVersion
- id
- workflow_definition_id
- version_number
- schema_version
- graph_json
- input_schema_json
- bindings_json
- output_schema_json
- content_hash
- source_canvas_id
- source_canvas_revision
- release_notes
- published_by
- published_at
```

`(workflow_definition_id, version_number)`와 `(workflow_definition_id, source_canvas_id, source_canvas_revision)`에는 Unique Constraint를 둔다. 같은 Canvas revision의 Publish 재시도는 기존 결과를 반환한다. `content_hash`는 검색용 Index로 두되 Unique로 만들지 않는다. 과거 내용으로 복구해 새 Version을 게시하는 경우 같은 hash가 다시 나타날 수 있기 때문이다.

### 4.4 WorkflowRun

기존 `CanvasRunRecord` 실행 계약을 확장해 아래 출처를 구분한다.

```text
WorkflowRun
- source_type: CANVAS_DRAFT | WORKFLOW_VERSION
- canvas_id: nullable
- workflow_definition_id: nullable
- workflow_version_id: nullable
- input_snapshot
- resolved_graph_snapshot
- model_snapshot
- compiler_version
- status / progress / cost / timestamps
```

기존 `graph_snapshot`은 `resolved_graph_snapshot` 역할로 유지할 수 있다. 단, 게시 Workflow Run에는 `workflow_version_id`와 `input_snapshot`이 반드시 있어야 한다.

Run 생성 이후 Canvas, Definition의 현재 버전, Model Registry가 변경되어도 해당 Run 내용은 바뀌지 않는다.

### 4.5 WorkflowAnnotation

게시된 WorkflowVersion 위에서 수정할 수 있는 메모다. 실행 정의와 분리해 메모 수정이 Version hash, Cache와 Run 재현성에 영향을 주지 않게 한다.

```text
WorkflowAnnotation
- id
- workflow_definition_id
- workflow_version_id: nullable
- node_id: nullable
- body
- position: nullable
- color
- revision
- created_by / updated_by
- created_at / updated_at
```

- `workflow_version_id`가 있으면 특정 Frozen Version에 대한 메모다.
- `workflow_version_id`가 없으면 Definition Overview에 표시하는 공통 메모다.
- `node_id`가 있으면 Frozen graph의 특정 Node에 연결한다.
- `node_id`가 없고 `position`이 있으면 Canvas 좌표에 배치한다.
- Annotation의 추가, 수정, 이동, 삭제는 Audit Event를 남긴다.
- Annotation은 WorkflowVersion content hash, Binding, 비용 계산, Cache key와 실행 payload에 포함하지 않는다.

### 4.6 관계

```text
WorkflowDefinition 1 ─── N WorkflowVersion
        │                       │
        │                       └── N WorkflowRun ─── N NodeRun
        │                       └── N WorkflowAnnotation
        │
        └── 1 active Draft Canvas

Canvas ── Publish ──> immutable WorkflowVersion
```

## 5. 변수 모델

제품 UI에서는 `Variable`보다 `Workflow input`을 기본 용어로 사용한다. 내부 모델은 입력 선언과 설정 바인딩을 분리한다.

### 5.1 입력 선언

V1 지원 타입은 다음으로 제한한다.

| 타입 | 용도 | 주요 제약 |
| --- | --- | --- |
| `string` | 제목, 주제, 언어 코드, 일반 텍스트 | min/max length, pattern |
| `prompt` | 긴 Prompt | max length |
| `integer` / `number` | 길이, 개수, 위치, 강도 | min/max/step |
| `boolean` | 음악 분리 등 Toggle | default |
| `enum` | 화면비, Transition, Voice | options |
| `artifact` | Image, Video, Audio 입력 | 허용 Artifact type, MIME, duration |
| `character` | Character Library 항목 | 존재 여부 |
| `model_alias` | 실행 모델 선택 | capability, provider allowlist |

Secret과 정확한 Provider 모델 ID는 입력 타입으로 허용하지 않는다.

입력 계약 예시는 다음과 같다.

```json
{
  "schema_version": "workflow.inputs.v1",
  "inputs": [
    {
      "key": "topic",
      "label": "영상 주제",
      "type": "prompt",
      "required": true,
      "validation": { "max_length": 4000 }
    },
    {
      "key": "reference_video",
      "label": "모션 레퍼런스",
      "type": "artifact",
      "required": true,
      "validation": { "artifact_types": ["Video"] }
    },
    {
      "key": "duration_seconds",
      "label": "클립 길이",
      "type": "integer",
      "required": false,
      "default": 6,
      "validation": { "minimum": 4, "maximum": 8 }
    }
  ]
}
```

`key`는 Version 안에서 고유하고 `^[a-z][a-z0-9_]{0,63}$`를 만족해야 한다. UI label 변경은 새 Version에서만 반영한다.

### 5.2 바인딩

바인딩은 입력값을 어느 노드 설정에 적용할지 정의한다. 대상 경로는 JSON Pointer로 표현한다. 허용 경로와 타입은 코드 여러 곳에 하드코딩하지 않고, 버전이 고정된 Node Definition의 Config Schema에서 가져온다.

```json
{
  "schema_version": "workflow.bindings.v1",
  "bindings": [
    {
      "target": { "node_id": "prompt-1", "path": "/config/text" },
      "value": {
        "kind": "template",
        "template": "{{topic}}을 세로형 숏폼으로 만들어줘",
        "input_keys": ["topic"]
      }
    },
    {
      "target": { "node_id": "motion-reference", "path": "/config/artifact_id" },
      "value": { "kind": "input", "key": "reference_video" }
    },
    {
      "target": { "node_id": "video-generator", "path": "/config/duration_seconds" },
      "value": { "kind": "input", "key": "duration_seconds" }
    }
  ]
}
```

지원하는 바인딩 연산은 두 가지뿐이다.

1. `input`: 입력값으로 필드 전체를 교체한다.
2. `template`: 문자열 필드에서 선언된 `{{key}}` Token만 치환한다.

일반 수식, 함수 호출, 중첩 객체 Merge는 V1에서 지원하지 않는다. Template은 Prompt 구성용 문자열 포맷터일 뿐 실행 코드가 아니다.

다음 대상은 바인딩할 수 없다.

- Node ID, Node type, `node_key`
- Edge source/target와 그래프 구조
- `executable`, `waitForInput` 같은 Control 설정
- Provider Credential
- Status, 결과, 로그, 비용 필드

### 5.3 상수와 기본값

- 변수화하지 않은 설정은 Version의 상수다.
- 필드를 입력으로 노출할 때 현재 Canvas 값을 기본값으로 가져오는 것이 기본 동작이다. 이 경우 `required=false`로 저장한다.
- 사용자가 `실행할 때 반드시 입력`을 선택하면 기본값 없이 `required=true`로 저장한다.
- `required=true`와 `default`를 함께 선언하는 계약은 Publish 시 거부해 의미를 하나로 유지한다.
- 불변 Artifact ID를 상수로 저장할 수 있지만 Publish와 Run 시점에 존재 및 접근 권한을 검사한다.
- Default도 Version의 일부이므로 변경하면 새 Version이 필요하다.

### 5.4 출력 계약

관리형 Workflow에는 결과를 찾기 위한 출력 선언도 함께 둔다.

```json
{
  "schema_version": "workflow.outputs.v1",
  "outputs": [
    {
      "key": "final_video",
      "label": "완성 영상",
      "node_id": "render-final",
      "port_type": "Video",
      "primary": true
    }
  ]
}
```

초기값은 실행 가능한 Terminal Node를 자동 감지해 제안하고, Publish 전에 Primary output을 한 개 선택하게 한다.

Compiler는 선언된 Primary/Secondary output에서 Edge를 역방향으로 탐색한다. 이 Output들에 도달하는 Node만 Workflow execution graph에 포함한다. 도달하지 않는 실행 Node는 `Unused branch`로 경고하고, 사용자가 Secondary output 또는 명시적 side effect로 선언하지 않으면 Publish graph에서 제외한다.

## 6. 게시용 그래프와 실행용 그래프

현재 React Flow 문서를 그대로 Version에 저장하지 않고 서버가 `workflow.graph.v1`로 정규화한다.

### 6.1 게시할 정보

- 안정적인 Node ID와 `node_key`
- `node_contract_version`과 Node Definition digest
- Node label과 설명
- 실행 설정과 논리 모델 별칭
- 입력/출력 Port 계약
- Edge와 다중 입력 순서
- 편집 화면 복원을 위한 Node position 등 최소 UI metadata
- 상수 Prompt와 상수 Artifact 참조

### 6.2 제거할 정보

- `status`, `runProgress`, `attemptCount`
- `output`, `outputArtifactIds`, `preview`
- `lastExperimentId`, `lastRequestHash`, `lastRunAt`
- `logs`, 실행 시간, 비용
- React Flow 선택 상태와 일시적인 Dimensions
- 만료 가능한 Signed URL과 `blob:` URL
- `utility.sticky`, `folder.group` 같은 Canvas 전용 요소
- 실행 Output에 도달하지 않는 연결되지 않은 Node와 Side branch

Sanitizer는 클라이언트 구현과 별도로 서버에 있어야 한다. Publish API가 정규화하지 않은 Canvas payload를 그대로 Version으로 저장해서는 안 된다.

### 6.3 Canvas 전용 요소 정규화

Canvas에 보이는 모든 요소를 Workflow Node로 취급하지 않는다.

| Canvas 요소 | Publish 처리 |
| --- | --- |
| `utility.sticky` | WorkflowAnnotation으로 복사하고 execution graph에서 제외 |
| `folder.group` | Canvas Draft의 UI layout으로만 유지하고 제외 |
| `utility.text` | Legacy loader에서 Sticky로 변환한 후 Annotation 처리 |
| `asset.upload` | 완료된 Artifact input으로 변환, 미완료 상태면 Publish 거부 |
| `utility.drawing` | 저장된 Image Artifact input으로 변환, Drawing document는 Draft에만 유지 |

`prompt.input`, 타입이 고정된 Asset input과 `character.select`는 Worker가 실행하지 않아도 Workflow의 상수/입력값을 전달하는 Source Node이므로 execution definition에 남긴다.

### 6.4 실행 그래프 선택

Publish graph는 아래 순서로 계산한다.

```text
Declared Primary/Secondary Outputs
              │
              └─ reverse reachability
                      │
                      ├─ 필요한 Source/Executor/Human gate Node 포함
                      ├─ Canvas annotation/layout 제외
                      └─ 연결되지 않은 Node와 사용되지 않는 branch 제외
```

Artifact 생성처럼 외부 상태를 남기는 Node도 암묵적 Side effect로 보존하지 않는다. 의도한 결과라면 Secondary output으로 선언하거나 Manifest가 허용하는 명시적 side effect contract를 사용해야 한다.

### 6.5 기존 실행기 호환 Adapter

현재 Canvas Run 엔진은 `data.configText`, `data.outputArtifactIds`, `data.output`을 읽어 비실행 입력 노드의 값을 다음 노드로 전달한다. 초기 구현에서는 Compiler가 정규 WorkflowVersion을 아래처럼 기존 실행 그래프로 변환한다.

```text
WorkflowVersion graph
  + validated input values
  + immutable Artifact metadata
        │
        └─ Binding resolver
             └─ Legacy Canvas execution graph
                    └─ existing CanvasRun/Temporal engine
```

예를 들어 `artifact` 입력은 해당 Asset 입력 노드의 `configText`, `outputArtifactIds`, 최소 `output` metadata로 Hydrate한다. 실행 엔진은 Canvas를 다시 읽지 않고 이 resolved graph snapshot만 사용한다.

장기적으로 실행 엔진이 정규 그래프를 직접 읽게 할 수 있지만 V1의 선행 조건은 아니다.

## 7. Workflow 생명주기

### 7.1 생성

두 진입점을 제공한다.

1. 새 Workflow를 만들면 빈 Definition과 Draft Canvas를 함께 생성한다.
2. 기존 Canvas의 `Convert to workflow`로 Definition을 만들고 해당 Canvas를 Draft로 연결한다.

기존 Canvas는 자동으로 Publish하지 않는다.

### 7.2 Publish

Publish는 다음 순서로 수행한다.

1. `expected_canvas_revision`으로 편집 충돌을 검사한다.
2. Canvas 그래프, Draft contract와 Canvas 메모를 읽는다.
3. Upload/Drawing을 Artifact source로 정규화하고 Sticky를 Annotation으로 분리한다.
4. 선언된 Output의 역방향 도달 그래프로 필요한 Node만 선택한다.
5. 실행 상태와 Canvas 전용 요소를 제거하고 Canonical graph를 만든다.
6. DAG, Port, 필수 입력, 바인딩 대상, 타입 호환성을 검사한다.
7. Template의 미선언 Token과 사용되지 않는 필수 입력을 검사한다.
8. 논리 모델 별칭과 상수 Artifact의 유효성을 검사한다.
9. Dry compile로 실행 가능 여부와 예상 비용을 계산한다.
10. Canonical JSON의 SHA-256 content hash를 만든다.
11. Definition을 Transaction lock하고 다음 version number를 발급한다.
12. Version과 초기 Annotation을 저장하고 `current_version_id`를 변경한 뒤 Audit Event를 기록한다.

한 단계라도 실패하면 Version을 만들지 않는다.

### 7.3 편집과 다음 Version

게시된 Version은 편집하지 않는다. Canvas에는 `based on vN`을 표시하고, 변경 사항이 생기면 `Unpublished changes` 상태가 된다. 다시 Publish하면 vN+1이 생성된다.

Canvas 자체는 Publish 전후 모두 편집 가능하다. Lock을 해제해 vN을 수정하는 동작은 없다. 그래프나 Node 설정을 변경하면 Draft만 바뀌고, 새 Publish 전까지 현재 WorkflowVersion과 그 Run에는 영향을 주지 않는다.

Version 복구는 과거 Version을 수정하는 방식이 아니라 다음 둘 중 하나로 처리한다.

- 과거 Version을 새 Draft에 복사한 뒤 새 Version으로 Publish
- 운영상 긴급한 경우 감사 로그를 남기고 `current_version_id`만 과거 Version으로 변경

### 7.4 Frozen Version 조회와 메모

현재 Workflow 상태는 Definition의 `current_version_id`가 가리키는 Frozen graph로 조회한다. Node, Edge, 입력/출력 계약과 설정은 읽기 전용이다.

WorkflowAnnotation Layer는 별도로 편집할 수 있다. 메모를 추가·수정·이동·삭제해도 WorkflowVersion을 Unlock하거나 새 Version을 Publish하지 않는다. 그래프 설정을 바꾸려면 `Edit as draft`를 사용한다.

### 7.5 Archive와 Delete

- `ARCHIVED` Workflow는 새 Run과 Publish를 막고 기존 Version, Run, Artifact는 읽을 수 있다.
- 한 번이라도 Publish한 Definition과 Version은 물리 삭제하지 않는다.
- Publish하지 않은 빈 Definition/Draft만 삭제할 수 있다.

## 8. Run 생성과 실행

게시 Workflow 실행 요청에는 Raw graph를 받지 않는다.

```http
POST /workflows/{workflow_id}/runs
Content-Type: application/json
Idempotency-Key: optional-client-key

{
  "version": 3,
  "inputs": {
    "topic": "퇴근 후 10분 저녁",
    "reference_video": "artifact_abc",
    "duration_seconds": 8
  },
  "budget_limit_usd": 3.0
}
```

서버 처리 순서는 다음과 같다.

1. 요청한 Version을 읽는다. 생략 시 요청 시점의 `current_version_id`를 고정한다.
2. 알 수 없는 입력은 거부하고 누락값에는 Default를 적용한다.
3. 타입, 범위, Enum, Artifact type과 접근 권한을 검증한다.
4. Binding을 적용해 resolved graph를 만든다.
5. 모델 별칭을 정확한 모델 ID, Provider, Registry revision으로 Snapshot한다.
6. 비용과 예산을 검사한다.
7. Version, 입력, resolved graph, 모델, Compiler revision을 한 Transaction으로 Run에 저장한다.
8. 기존 Local 또는 Temporal Canvas DAG 실행기에 Run ID를 전달한다.

이후 Worker는 Version이나 Canvas를 다시 읽지 않는다. Retry는 같은 resolved snapshot을 사용하고, 다른 입력으로 다시 실행하면 새 Run을 만든다.

Cache key에는 최소한 아래 값이 포함되어야 한다.

- WorkflowVersion content hash
- Node type/version
- 해당 노드에 적용된 normalized config
- 입력 Artifact hash
- Prompt hash
- Provider와 exact model ID
- Renderer/Executor revision

## 9. API 설계

기존 `/canvases`와 Draft Run API는 호환을 위해 유지하고, 관리형 Workflow API를 추가한다.

| Method | Path | 역할 |
| --- | --- | --- |
| `POST` | `/workflows` | Definition과 Draft Canvas 생성 |
| `GET` | `/workflows` | 상태, 최신 Version, Run 요약 목록 |
| `GET` | `/workflows/{id}` | Definition 상세 |
| `PATCH` | `/workflows/{id}` | 이름, 설명, 태그 변경 |
| `POST` | `/workflows/{id}/publish` | Draft Canvas를 새 Version으로 게시 |
| `GET` | `/workflows/{id}/versions` | Version 목록 |
| `GET` | `/workflows/{id}/versions/{number}` | 불변 Version 상세 |
| `POST` | `/workflows/{id}/versions/{number}/restore-draft` | 과거 Version으로 Draft 복원 |
| `GET` | `/workflows/{id}/annotations` | Definition 공통 메모 조회 |
| `POST` | `/workflows/{id}/annotations` | Definition 공통 메모 추가 |
| `GET` | `/workflows/{id}/versions/{number}/annotations` | Version 메모 조회 |
| `POST` | `/workflows/{id}/versions/{number}/annotations` | Version 메모 추가 |
| `PATCH` | `/workflow-annotations/{annotation_id}` | 메모 내용·위치·색상 수정 |
| `DELETE` | `/workflow-annotations/{annotation_id}` | 메모 삭제와 Audit 기록 |
| `POST` | `/workflows/{id}/runs` | 입력값으로 Version 실행 |
| `POST` | `/workflows/{id}/archive` | Archive |
| `POST` | `/workflows/{id}/activate` | 다시 활성화 |

Canvas autosave 요청에는 `revision`과 `draft_contract`를 포함한다. 서버 응답의 새 revision을 다음 저장의 `expected_revision`으로 사용한다. Revision은 실행 상태 복구가 아니라 그래프, 설정, 계약이 바뀔 때만 증가한다. 충돌은 `409 Conflict`로 반환한다.

오류는 UI가 필드에 연결할 수 있도록 구조화한다.

```json
{
  "code": "WORKFLOW_INPUT_INVALID",
  "message": "Workflow input validation failed",
  "issues": [
    { "input_key": "duration_seconds", "code": "MAXIMUM", "message": "8 이하여야 합니다." }
  ]
}
```

## 10. UI/UX 설계

### 10.1 용어와 Route

현재 섞인 용어를 아래처럼 분리한다.

- `/canvases`: 독립 Canvas와 Workflow Draft 편집 문서
- `/canvases/{canvas_id}`: 그래프 편집기
- `/workflows`: 게시 가능한 Workflow 관리 목록
- `/workflows/{workflow_id}`: Overview, Versions, Runs
- `/workflows/{workflow_id}/versions/{number}`: Frozen graph와 Annotation Layer
- `/workflows/{workflow_id}/run`: 입력 Form과 실행 전 검토

기존 `/workflows/{canvas_id}` 링크에는 마이그레이션 기간 동안 `/canvases/{canvas_id}` Redirect를 둔다.

### 10.2 Canvas 편집기

각 변수화 가능한 Inspector 필드 오른쪽에 `Expose as input` Action을 둔다.

Action을 누르면 다음을 설정한다.

- Key, label, 설명
- 타입과 Validation
- Required 여부
- 현재 값을 Default로 사용할지
- 문자열이면 전체 교체 또는 Template Token으로 사용할지

Canvas 상단에는 다음 항목을 둔다.

- `Draft` / `Based on vN` / `Unpublished changes` 상태
- `Inputs (N)` 버튼
- `Validate`
- `Publish vN`
- Draft 자체를 시험하는 기존 `Run workflow`

`Inputs` 패널은 입력 목록, Default, 사용 중인 Node field, 미사용 입력과 충돌을 표시한다. 하나의 대상 필드에는 하나의 Binding expression만 허용한다.

### 10.3 Workflow 관리 화면

Workflow 목록에는 다음을 표시한다.

- 이름, 상태, 최신/현재 Version
- 입력 개수와 Primary output type
- 마지막 Run 상태와 시각
- 최근 성공률, 평균 실행 시간, 평균 비용
- `Edit draft`, `Run`, `Versions`, `Archive` Action

상세 화면은 다음 Tab으로 나눈다.

1. Overview: 설명, 현재 Version, 입력/출력 계약, 최근 Run
2. Versions: 게시 시각, 작성자, release note, graph/input 변경 요약
3. Runs: Version, 주요 입력, 상태, 비용, 결과 Artifact
4. Settings: 이름, 태그, Archive

### 10.4 게시된 Version Viewer

게시된 Version은 당시 Node 위치, Edge, Config와 입출력 계약을 그대로 보여주는 읽기 전용 Canvas로 표시한다.

```text
Workflow v3 · Published
[Read-only graph] [Edit as draft] [Run]

Graph layer       Node/Edge/Config 수정 불가
Annotation layer  메모 추가/수정/이동/삭제 가능
```

- Node를 선택하면 게시 당시의 Config, 모델 별칭과 계약 버전을 읽기 전용으로 표시한다.
- `Edit as draft`는 Version을 Unlock하지 않고 활성 Draft에 복사하거나 해당 Version 기반 Draft를 연다.
- 현재 Version이 아닌 과거 Version에도 별도 Annotation을 남길 수 있다.
- 실행 상태는 Version graph에 덮어쓰지 않고 선택한 WorkflowRun overlay 또는 Runs Tab에서 본다.

### 10.5 실행 Form

선택한 Version의 input schema로 Form을 생성한다.

- `artifact`: Asset Library Picker와 type filter
- `character`: Character Library Picker
- `enum` / `model_alias`: Select
- `number`: 범위를 표시하는 Number input
- `prompt`: Textarea

실행 전에는 Version, 예상 비용, Default가 적용된 최종 입력을 보여준다. Run 상세에서는 민감하지 않은 `input_snapshot`, 정확한 모델, Node별 상태와 Primary output을 표시한다.

## 11. 검증과 보안 규칙

Publish 시 검사:

- Node ID 유일성, 알려진 Node type, DAG acyclic
- Edge와 Port type 호환성, 다중 입력 순서
- 필수 Port 연결
- Input key 유일성과 Schema 유효성
- Binding Node/path 존재 및 Node별 Allowlist
- 입력 타입과 대상 필드 타입 호환성
- Template Token과 `input_keys` 일치
- Runtime-only field가 Version에 남지 않았는지
- 상수 Artifact 존재, 불변성, 권리 및 접근 가능성
- 모델 별칭의 Node capability 호환성
- Output node와 port 유효성
- Primary output 존재와 Output 역방향 도달 그래프
- Canvas-only 요소가 execution graph에 남지 않았는지
- 미완료 Upload와 저장되지 않은 Drawing이 없는지

Run 시 검사:

- Version과 Definition 상태
- Required/default/unknown input
- 값의 타입, 범위와 길이
- Artifact/Character 존재와 Workspace 접근 권한
- 입력 Artifact의 권리 및 생성 사용 가능 여부
- Budget limit
- Idempotency key 재사용 시 동일 payload인지

Prompt와 Asset metadata는 기존 Trust Boundary 원칙대로 untrusted data로 취급한다. Template resolver는 문자열을 치환할 뿐 입력값을 명령이나 코드로 실행하지 않는다.

## 12. 기존 데이터 호환과 Migration

1. `workflow_definitions`, `workflow_versions`를 추가한다.
2. `workflow_annotations`를 추가하고 Version/Definition 범위와 optimistic revision을 저장한다.
3. `canvases`에 Draft 연결, revision, contract 필드를 추가한다.
4. `canvas_runs`에 source와 Version/input/model snapshot 필드를 추가한다.
5. 기존 Canvas는 모두 독립 Canvas로 유지한다.
6. 기존 Canvas Run은 `source_type=CANVAS_DRAFT`로 Backfill한다.
7. 사용자가 `Convert to workflow`를 실행할 때만 Definition과 Draft 연결을 만든다.
8. Publish 시 기존 Sticky는 Version Annotation으로 복사하고, Folder는 Draft에만 남긴다.
9. 완료된 Upload/Drawing은 Artifact source로 정규화한다.
10. 기존 Experiment와 Artifact ID는 변경하지 않는다.
11. 관리형 Workflow Run도 초기에는 기존 Canvas DAG/Temporal Activity를 사용한다.

자동 변환이나 자동 Publish는 하지 않는다. 현재 Canvas 문서에 실행 결과가 섞여 있으므로 사용자의 명시적인 Publish 과정에서 Sanitizer와 검증을 거쳐야 한다.

## 13. 단계별 구현 순서

### Phase 1: 계약과 저장 기반

- `workflow.graph.v1`, `workflow.inputs.v1`, `workflow.bindings.v1`, `workflow.outputs.v1` Schema
- 버전이 고정된 Node Definition Registry와 Manifest Schema
- DB Migration과 Domain model
- Canvas sanitizer/canonicalizer/content hash
- Output reachability compiler와 Canvas-only element normalizer
- Input validator와 Binding resolver
- Publish API와 단위/계약 테스트

### Phase 2: 실행 통합

- Workflow Run API
- WorkflowVersion을 기존 Canvas execution graph로 바꾸는 Adapter
- Run input/model/compiler snapshot
- Local/Temporal 양쪽 실행 테스트
- Idempotency와 비용 검사

### Phase 3: Canvas 변수화 UX

- Inspector의 `Expose as input`
- Inputs panel과 Draft contract autosave
- Publish dialog, release note, validation issue 연결
- Existing Canvas의 `Convert to workflow`

### Phase 4: 관리 화면

- Workflow 목록과 상세
- Frozen Version Viewer와 편집 가능한 Annotation Layer
- Version history/diff
- Schema 기반 Run Form
- Run/Artifact 연결과 요약 지표
- Archive/activate/restore-draft

### Phase 5: 운영 보강

- Workspace 격리와 권한
- Audit 화면, 관측성, 성공률/비용 집계
- Version export/import, Trigger와 Schedule은 별도 설계 후 추가

## 14. 테스트 전략

### 단위 테스트

- 모든 입력 타입의 Default, Required, 범위 검증
- `input`과 `template` 바인딩
- 미선언 Token, 잘못된 JSON Pointer, 금지 필드 거부
- Sanitizer가 모든 실행 상태와 URL을 제거하는지
- Output에 도달하지 않는 Node와 Canvas-only 요소를 제거하는지
- Sticky가 Annotation으로 변환되고 Version hash에서 제외되는지
- 같은 Canonical 문서의 content hash 안정성

### API/DB 테스트

- Publish version number의 동시성 및 단조 증가
- 같은 Canvas revision 또는 Idempotency key의 Publish 재시도
- Version update/delete 거부
- Canvas 수정이 기존 Version과 Run을 바꾸지 않는지
- Archive 상태에서 Publish/Run 거부
- 과거 Version 지정 실행
- Annotation 수정 전후 WorkflowVersion hash와 Run payload 불변
- Annotation optimistic revision과 Audit Event

### 실행 통합 테스트

- `Prompt + Artifact + duration` 입력으로 resolved graph 생성
- 같은 Version을 서로 다른 입력으로 두 번 실행
- Run에 입력, 모델, graph snapshot이 남는지
- Local과 Temporal의 동일한 resolved graph 처리
- WAITING_INPUT 승인 후 Version snapshot을 유지하는지

### 브라우저 E2E

```text
기존 Canvas 열기
→ Prompt/Asset/Duration을 Input으로 노출
→ Publish v1
→ Frozen v1 graph에서 메모 추가·수정
→ v1 hash와 실행 graph가 변하지 않는지 확인
→ 생성된 Form으로 Run
→ Draft 수정 후 Publish v2
→ v1/v2 Run과 결과가 분리되어 표시되는지 확인
```

## 15. V1 완료 기준

- 기존 Canvas 하나를 명시적으로 Workflow로 전환할 수 있다.
- Prompt, Artifact, 숫자/Enum 설정을 입력으로 노출할 수 있다.
- 입력 누락이나 타입 오류가 Publish 또는 Run 전에 명확히 표시된다.
- v1 게시 후 Canvas를 수정해도 v1과 기존 Run은 변하지 않는다.
- Publish 후 Canvas를 Lock/Unlock하지 않고 Draft 편집을 계속할 수 있다.
- 게시된 Version graph를 당시 상태 그대로 읽기 전용으로 조회할 수 있다.
- Version 메모를 수정해도 Version hash, Cache와 Run payload가 바뀌지 않는다.
- Sticky/Folder/미완료 Upload가 Workflow execution graph에 포함되지 않는다.
- 선언된 Output에 도달하는 Node만 Workflow execution graph에 포함된다.
- 같은 Version을 다른 입력으로 반복 실행할 수 있다.
- 모든 Run에서 Version, 입력, resolved graph, exact model snapshot을 조회할 수 있다.
- v2를 게시하고 v1/v2 변경 요약과 각각의 Run을 조회할 수 있다.
- 기존 Draft Canvas Run과 Local/Temporal 실행 경로가 계속 동작한다.
- 게시 Workflow Run API는 클라이언트의 Raw graph를 받지 않는다.

## 16. 구현 전 제품 결정과 확정 기본값

아래는 구현 범위를 크게 바꾸므로 착수 전에 한 번 확정한다. 권장 기본값도 함께 적는다.

1. V1 입력 타입: 위에 정의한 9종으로 제한한다. 권장: 그대로 진행.
2. Artifact 상수 허용: 불변 Artifact만 허용한다. 권장: 허용.
3. 하나의 Workflow당 활성 Draft: V1은 하나만 둔다. 권장: 하나.
4. 과거 Version 긴급 전환: `current_version_id` 변경을 허용하되 Audit을 남긴다. 권장: 허용.
5. Route 분리: Canvas와 Workflow를 `/canvases`, `/workflows`로 분리한다. 권장: 분리.
6. Draft Run: Publish 전 테스트를 위해 현재 Canvas Run을 유지한다. 권장: 유지하되 관리형 Run과 명확히 표시.
7. Canvas Lock: Publish 후에도 Canvas는 편집 가능하며 별도 Unlock은 없다. 확정.
8. Version 메모: Frozen graph 밖의 WorkflowAnnotation으로 저장하고 수정 가능하게 한다. 확정.
9. Publish graph: 선언된 Output의 역방향 도달 Node만 포함한다. 확정.
10. Canvas-only 요소: Sticky는 Annotation, Folder는 Draft-only, Upload/Drawing은 Artifact source로 정규화한다. 확정.

## 17. 노드가 계속 추가되는 경우의 확장 설계

새 노드를 추가할 때 기존 Workflow를 유지하려면 Workflow가 현재 애플리케이션 코드의 암묵적인 Node 동작에 의존해서는 안 된다. 각 Node를 버전이 있는 독립 계약으로 취급한다.

### 17.1 Node Definition Registry

서버를 기준으로 `NodeDefinition` Registry를 둔다. Node Library, Publish Validator, Binding Resolver와 Executor가 모두 같은 정의를 읽는다.

```text
NodeDefinition
- type_key: video.generate
- contract_version: 2
- definition_digest
- display: label, description, category, icon
- config_schema
- input_ports
- output_ports
- binding_policy
- executor: kind, name, compatible revisions
- editor: generic | asset-picker | caption-layout | drawing | custom
- lifecycle: ACTIVE | DEPRECATED | RETIRED | BLOCKED
```

`type_key`는 Node의 안정적인 정체성이고 `contract_version`은 설정, Port, 의미 계약의 버전이다. 예를 들어 `video.generate@1`과 `video.generate@2`는 같은 계열이지만 서로 다른 불변 계약이다.

WorkflowVersion의 각 Node에는 다음 값을 고정한다.

```json
{
  "id": "video-generator-1",
  "type_key": "video.generate",
  "contract_version": 2,
  "definition_digest": "sha256:...",
  "config": {
    "model_alias": "video.omni",
    "duration_seconds": 6,
    "aspect_ratio": "9:16"
  }
}
```

새 Node Definition을 Registry에 추가해도 이미 게시된 WorkflowVersion은 자신이 고정한 계약을 계속 사용한다.

### 17.2 Node Manifest

대부분의 새 노드는 하나의 Manifest와 Executor 구현으로 추가할 수 있어야 한다.

```json
{
  "schema_version": "node.definition.v1",
  "type_key": "video.generate",
  "contract_version": 2,
  "display": {
    "label": "Video generator",
    "category": "Video",
    "icon": "video"
  },
  "ports": {
    "inputs": [
      { "key": "prompt", "type": "prompt.text.v1", "required": true },
      { "key": "reference", "type": "media.video.v1", "multiple": true }
    ],
    "outputs": [
      { "key": "video", "type": "media.video.v1" }
    ]
  },
  "config_schema": {
    "type": "object",
    "additionalProperties": false,
    "required": ["model_alias", "duration_seconds", "aspect_ratio"],
    "properties": {
      "model_alias": {
        "type": "string",
        "x-workflow-input": { "enabled": true, "type": "model_alias" }
      },
      "duration_seconds": {
        "type": "integer",
        "minimum": 4,
        "maximum": 8,
        "x-workflow-input": { "enabled": true, "type": "integer" }
      },
      "aspect_ratio": {
        "type": "string",
        "enum": ["9:16", "16:9", "1:1"],
        "x-workflow-input": { "enabled": true, "type": "enum" }
      }
    }
  },
  "executor": {
    "kind": "provider",
    "name": "video-generation"
  },
  "editor": { "kind": "generic" }
}
```

`x-workflow-input` metadata가 Inspector의 `Expose as input` 가능 여부, 입력 타입과 Validation을 결정한다. 따라서 새 Node의 변수화 지원을 별도 UI 분기나 서버 Allowlist에 다시 작성하지 않는다.

### 17.3 Port 타입도 버전 관리

현재와 같은 `"Video"`, `"Prompt"` 문자열만으로는 미래 호환성을 충분히 표현하기 어렵다. Canonical Workflow에서는 다음처럼 버전이 있는 Port type ID를 사용한다.

```text
prompt.text.v1
media.image.v1
media.video.v1
media.audio.v1
artifact.character.v1
timeline.caption.v1
```

연결 가능 여부는 Registry가 결정한다.

- 같은 type ID는 직접 연결할 수 있다.
- 명시적으로 등록된 호환 관계만 연결할 수 있다.
- 변환이 필요한 경우 암묵적으로 처리하지 않고 Adapter Node를 그래프에 둔다.

이 원칙을 사용하면 새 Node가 기존 `Video`와 비슷하지만 다른 계약을 출력할 때 기존 Workflow를 우연히 깨뜨리지 않는다.

### 17.4 Config Default의 고정

Node Manifest의 Default는 Canvas에서 새 Node를 만들 때만 사용한다. Publish할 때 모든 실행 관련 Default를 Node config에 명시적으로 Materialize한다.

```text
Manifest default 변경
        │
        ├─ 새로 추가한 Node: 새 default 사용
        └─ 기존 Draft/Version Node: 저장된 값을 계속 사용
```

이렇게 해야 Node Library의 기본 길이를 6초에서 8초로 바꾸더라도 기존 Workflow가 조용히 달라지지 않는다.

### 17.5 Executor 계약

모든 Atomic Node Executor는 같은 인터페이스를 구현한다.

```text
execute(
  execution_context,
  resolved_node_config,
  typed_input_artifacts
) -> NodeExecutionResult
```

`NodeExecutionResult`에는 출력 Artifact, 타입, Provider request/operation ID, 비용, 로그용 metadata가 포함된다. Local 실행과 Temporal Activity는 각각 Node별 코드를 직접 선택하지 않고 Executor Registry를 통해 같은 Executor를 호출한다.

WorkflowVersion은 Node의 `contract_version`을 고정한다. WorkflowRun은 실제로 선택된 아래 Runtime revision을 추가로 Snapshot한다.

- Executor revision
- Provider와 exact model ID
- Renderer/FFmpeg revision
- Node Definition digest

호환되는 버그 수정은 같은 Node contract 안에서 Executor revision만 올릴 수 있다. Port, 필수 Config, 출력 의미가 달라지면 반드시 새 `contract_version`을 만든다.

### 17.6 호환성 규칙

다음 변경은 같은 contract version에서 허용할 수 있다.

- 설명, 아이콘, 도움말 변경
- 기존 동작을 유지하는 Executor 버그 수정
- 실행 결과의 비계약 metadata 추가

다음 변경은 새 contract version이 필요하다.

- 필수 Config 추가 또는 타입/범위 변경
- Config 의미나 Default 적용 방식 변경
- Input/Output Port 추가, 제거, 타입 변경
- 다중 입력 순서나 Cardinality 변경
- Artifact output 의미 또는 Schema 변경
- 기존 Binding path 제거

새 contract version이 만들어져도 기존 Version을 자동 변환하지 않는다.

### 17.7 명시적인 Node Upgrade

기존 Draft에서 구버전 Node가 발견되면 Canvas에 다음 상태를 표시한다.

```text
video.generate@1 · Update available: @2
```

사용자가 `Upgrade node`를 선택할 때만 Registry에 등록된 Migration을 실행한다.

```text
migrate_config(
  from_contract=1,
  to_contract=2,
  old_config,
  old_bindings
) -> new_config, new_bindings, warnings
```

Migration은 Draft만 변경한다. Upgrade 결과는 Diff와 경고를 보여주고, 검증 후 새 WorkflowVersion으로 Publish한다. 게시된 Version 안의 Node contract를 직접 바꾸지 않는다.

Migration이 없는 Breaking change는 자동 Upgrade하지 않고 새 Node로 교체하도록 안내한다.

### 17.8 Node 생명주기

| 상태 | 새 Canvas에 추가 | 새 Version Publish | 기존 Version Run | 과거 조회 |
| --- | --- | --- | --- | --- |
| `ACTIVE` | 허용 | 허용 | 허용 | 허용 |
| `DEPRECATED` | 기본 숨김 | 경고 후 허용 | 허용 | 허용 |
| `RETIRED` | 금지 | 금지 | 정책에 따라 제한 | 허용 |
| `BLOCKED` | 금지 | 금지 | 보안상 금지 | 허용 |

`DEPRECATED` Node의 Executor와 Definition은 기존 Workflow 실행을 위해 유지한다. `RETIRED` 전에는 대체 Node와 Migration 경로를 제공한다. 심각한 보안 또는 권리 문제만 `BLOCKED`로 기존 실행까지 중단할 수 있고, 이 경우 Run 오류에 운영자 조치와 대체 경로를 명시한다.

### 17.9 Web UI 확장 방식

현재 `nodeTemplates`처럼 모든 Node 설정을 Web 코드 한 파일에 직접 넣는 구조는 단계적으로 Registry 기반으로 전환한다.

- Node Library: Registry의 `ACTIVE` Manifest로 생성
- 일반 Inspector: `config_schema`와 UI metadata로 자동 생성
- Workflow input 노출: `x-workflow-input`으로 자동 생성
- Port와 연결 검증: Registry Port 계약 사용
- 특별한 미디어 UX: `editor.kind`에 대응하는 Custom Editor 사용

Caption layout, Drawing Canvas, Asset Picker처럼 상호작용이 복잡한 Node만 Custom Editor가 필요하다. Custom Editor가 설치되지 않은 환경에서도 Generic Inspector 또는 읽기 전용 Fallback으로 Workflow 구조와 설정을 볼 수 있어야 한다.

Custom Editor를 사용하는 신규 계약은 `editor.kind=custom`과 안정적인 `editor.ref`를 Manifest에 선언한다. `editor.ref`는 서버 소유 catalog에 먼저 등록하며 API Node Registry는 시작 시 ref 존재 여부를 검증한다. Web Custom Editor Registry 구현과 catalog의 불일치는 Architecture test에서 실패한다.

이미 게시 가능한 상태로 배포된 `editor.kind=legacy` 계약은 editor metadata만 바꾸기 위해 같은 contract version을 덮어쓰지 않는다. 기존 definition digest를 유지한 채 `type_key@contract_version` Legacy Adapter로 Custom Editor ref에 연결하고, 새 contract부터 명시적인 Manifest ref를 사용한다. ref 구현이 없거나 로드되지 않으면 저장 Config를 삭제하지 않고 read-only fallback으로 연다.

Canvas의 신규 Edge는 source/target Node의 고정된 contract version에서 Port ID와 cardinality를 해석하고 서버 Port Registry의 compatibility로 검증한다. 기존 React Flow의 `input-Prompt-0` 같은 Handle은 Legacy Adapter에서만 Port key로 변환한다. Unknown Node 또는 과거에 허용된 비호환 Edge는 Load 중 삭제하지 않고 Draft에 보존하며 Validate/Publish에서 명확한 오류를 반환한다.

### 17.10 새 Node 추가 절차

새 Node를 추가하는 표준 절차는 다음과 같다.

1. 안정적인 `type_key`와 첫 `contract_version`을 정한다.
2. Config Schema, Port 계약, 변수화 가능한 필드를 Manifest에 선언한다.
3. 공통 Executor 인터페이스를 구현한다.
4. Generic Inspector로 충분하지 않은 경우에만 Custom Editor를 추가한다.
5. Manifest validation, Executor contract, Artifact lineage 테스트를 작성한다.
6. Local과 Temporal에서 동일한 실행 결과 계약을 검증한다.
7. Registry에 `ACTIVE`로 등록한다.

기존 Node 변경이면 호환성 분류, 새 contract version과 Config/Binding Migration 테스트를 추가한다.

### 17.11 노드 확장 완료 기준

- Generic Node 하나를 Manifest와 Executor만으로 Library에 추가할 수 있다.
- 새 Node의 설정 Form과 `Expose as input`이 Schema에서 자동 생성된다.
- 새 Node 등록 전후 기존 WorkflowVersion의 hash와 실행 계약이 바뀌지 않는다.
- 기존 contract version을 사용하는 Workflow를 계속 열고 실행할 수 있다.
- Breaking change는 자동 적용되지 않고 명시적인 Draft Upgrade와 새 Publish를 거친다.
- Local과 Temporal이 같은 Node Executor Registry를 사용한다.
- 누락된 Custom Editor가 있어도 Workflow를 조회할 수 있다.

## 18. 현재 Node의 Workflow 포함 여부

2026-08-31 기준 `nodeTemplates`에는 37개 Library entry와 31개 고유 `node_key`가 있다. Workflow 계약화에서는 Library entry 수가 아니라 고유 실행/데이터 계약을 기준으로 한다.

### 18.1 Canvas-only 또는 Publish 변환 대상

| 현재 key | 분류 | 처리 |
| --- | --- | --- |
| `utility.sticky` | Annotation | WorkflowAnnotation으로 복사, execution graph 제외 |
| `folder.group` | Canvas layout | Draft에만 유지, execution graph 제외 |
| `utility.text` | Legacy | Sticky로 읽은 뒤 Annotation 처리, 신규 Definition 금지 |
| `asset.upload` | Authoring tool | 완료된 Artifact source로 변환, 미완료 Publish 거부 |
| `utility.drawing` | Authoring tool | Image Artifact source로 변환, Drawing document는 Draft-only |

이 요소들은 Canvas에서 계속 사용할 수 있지만 Workflow NodeRun과 비용/진행률 계산 대상이 아니다.

### 18.2 실행하지 않아도 필요한 Source Node

- `prompt.input`
- 타입이 고정된 Image/Video/Audio Artifact input
- `character.select`

이 Node들은 Worker Executor는 없지만 상수와 Workflow input을 Typed Port로 전달하므로 Canonical Workflow definition에 포함한다.

현재 `asset.select`는 선택 결과에 따라 출력 타입이 바뀌므로 계약화하면서 다음 중 하나로 고정해야 한다.

- `asset.image@1`, `asset.video@1`, `asset.audio@1`로 분리
- `asset.select@1` Config의 `artifact_type`을 Publish 전에 고정

### 18.3 중복 Library entry

다음 key는 Quick/Category에 두 번씩 정의돼 있지만 각각 하나의 NodeDefinition만 가져야 한다.

- `image.generate`
- `lora.image.generate`
- `character.generate`
- `video.generate`
- `tts.generate`
- `asset.select`

Quick/Image/Video/Audio 노출 차이는 Node 계약을 복제하지 않고 Library placement metadata로 처리한다.

### 18.4 Legacy Pipeline 검토 대상

다음 Node는 Canvas Library에서 숨겨져 있고 현재 저장 Canvas 사용은 없지만 기존 Default Generation Pipeline 코드와 테스트에 연결돼 있다.

- `generation.brief`
- `format.profile`
- `generation.resolve`
- `script.generate`
- `script.fit_duration`
- `shot.plan`
- `candidate.select`
- `media.qc`

기존 Generation Run을 유지하면 Legacy Workflow contract로 계약화한다. 새 Canvas 기반 Workflow가 완전히 대체한다면 개별 삭제하지 않고 Pipeline 전체를 `DEPRECATED` 처리한다.

- `candidate.select`는 범용 Human gate로 재설계할 수 있다.
- `media.qc`는 삭제하기보다 Compiler가 Final Video output에 자동 부착하는 내부 검증 정책으로 전환할 수 있다.
- `generation.brief`와 `format.profile`의 Canvas source 표현은 Workflow input/Artifact source로 대체할 수 있지만 Backend domain data는 별도로 유지할 수 있다.

### 18.5 Workflow에 유지할 실행 Node

Provider generation, Reference/Motion analysis, Video/Audio editing, Subtitle/Caption/Render처럼 선언된 Output에 도달하는 Node는 계약화해 유지한다. 현재 DB 사용 횟수가 0이라는 이유만으로 삭제하지 않는다. Registry lifecycle, 제품 노출 여부와 실행 계약 존재 여부를 분리한다.
