# 기존 Node 계약화 리팩터링 계획

Status: Proposed
작성 기준: 2026-08-31
범위: 현재 저장소에 이미 존재하는 Canvas/Generation Node를 버전이 있는 공통 Node Protocol로 전환한다.

## 구현 상태

2026-08-31 기준:

- Phase 0 완료: 36개 key를 31개 production contract와 5개 Canvas-only 요소로 고정했다.
- Phase 1 완료: Node Definition Schema, Port Type Registry, immutable digest와 Registry API가 있다. `editor.kind=custom`은 서버 소유 ref catalog에 등록된 `editor.ref`를 요구하고 Registry 시작 시 존재 여부를 검증한다.
- Phase 2 완료: production Node 31개에 `@1` Manifest를 등록했고 Legacy Pipeline 8개는 `DEPRECATED`다. LLM Assistant, Skill Executor, Script Generator는 xAI 모델 범위를 추가한 `@2`도 함께 등록했다.
- Phase 3 진행 중: 신규 Canvas 저장은 `canvas.document.v1`의 Canonical Node/Canvas element/Runtime sidecar로 분리되고 기존 Canvas는 다음 저장 시 전환된다. Web autosave/manual save/Publish 선행 저장은 Canonical serializer를 사용한다. Canvas 조회 응답과 Draft Run은 아직 Legacy React Flow Adapter payload를 사용한다.
- Phase 4 진행 중: production Node 31개 중 5개는 native Executor, 26개는 `legacy-compatibility` Executor Adapter를 사용한다.
- Phase 5 진행 중: ACTIVE production Node Library는 최신 Registry Manifest에서 생성되고 `nodeTemplates`는 Canvas-only 요소와 Legacy read fallback으로 제한됐다. Provider/model 선택도 Manifest `model_families`와 Model Registry에서 생성되며 xAI를 포함한 Provider별 Node key 분기는 제거됐다. 복잡한 Inspector는 Custom Editor ref Registry로 격리됐고 누락된 editor는 read-only fallback으로 열린다. 신규 계약은 Manifest의 명시적인 `editor.ref`로 dispatch하며 기존 immutable `editor.kind=legacy` 계약은 `type_key@contract_version` Adapter로 digest를 유지한다. Canvas 신규 연결과 Publish의 Port 호환성·cardinality·필수 입력 검증은 versioned Port Registry 계약을 사용한다.
- Phase 6 Backend/Web 수직 단면 완료: WorkflowVersion Publish, Annotation, Version Run, Frozen Viewer, `Expose as input`과 Artifact/Character Picker Run Form이 연결됐다. Prompt Template 다중 binding과 복수 Output 선택 UX는 남았다.
- Phase 7 진행 중: Canvas의 직접 Legacy JSON literal write, Generation Canvas Inspector의 Node key별 UI 분기와 Legacy Port 비교 재도입을 막는 Architecture test가 추가됐다. Legacy/Unknown Edge는 Load 중 삭제하지 않고 검증 오류와 read-only 호환 경로를 유지한다. Generation Canvas의 Legacy write는 제거됐고 로컬 스토리지 1회성 Import만 호환 요청을 사용한다. `nodeTemplates` Legacy read 목록과 중앙 실행 dispatch 제거는 남았다.

## 1. 목적

현재 Node 정의와 동작은 Web과 API 여러 파일에 분산돼 있다. 앞으로 Node가 추가되어도 기존 Workflow가 깨지지 않게 하려면 기존 data/execution Node는 공통 계약으로 전환하고 Canvas-only 요소는 Annotation/Layout/Authoring 계약으로 분리해야 한다.

```text
immutable NodeDefinition
  + versioned Node contract
  + common Executor interface
  + typed ports
  + schema-driven config/bindings
        │
        ├─ Canvas authoring
        ├─ Workflow publish validation
        ├─ Local execution
        └─ Temporal execution
```

이 계획의 결과로 다음을 달성한다.

- Workflow data/execution graph에 포함되는 모든 기존 Node에 안정적인 `type_key`와 `contract_version`을 부여한다.
- Sticky, Folder, Upload UI와 Drawing editor를 실행 Node와 분리한다.
- Node Library, Inspector, Graph validation, Workflow input 노출이 같은 Manifest를 사용한다.
- Canvas, Local engine, Temporal Activity가 같은 Executor Registry를 사용한다.
- 기존 Canvas와 Run 기록을 읽고 실행할 수 있다.
- Node 추가가 중앙 조건문과 타입 Union을 계속 키우지 않게 한다.
- 게시된 WorkflowVersion은 Node 구현 변경과 무관하게 기존 계약을 유지한다.

이 문서는 기존 Node의 전환 계획이다. 전환 이후 새 Node를 추가하거나 기존 Node 계약을 변경하는 규칙은 루트 `AGENTS.md`를 따른다.

## 2. 리팩터링 원칙

### 2.1 Big-bang 전환 금지

기존 실행 경로를 한 번에 교체하지 않는다. Registry와 Adapter를 먼저 추가하고, 기존 Node를 계약화한 뒤 UI와 실행기를 순차적으로 Registry로 전환한다.

각 단계는 다음 조건을 만족해야 다음 단계로 넘어간다.

- 기존 저장 Canvas를 열 수 있다.
- 기존 Canvas Run과 Step Run 테스트가 통과한다.
- Local과 Temporal의 실행 의미가 달라지지 않는다.
- Artifact type, lineage, request hash와 비용 기록이 유지된다.

### 2.2 안정적인 기존 식별자 유지

현재 `data.key`/`node_key` 값은 첫 `type_key`로 유지한다. 예:

```text
image.generate       → image.generate@1
video.generate       → video.generate@1
timeline.compose     → timeline.compose@1
reference.decompose  → reference.decompose@1
```

리팩터링을 이유로 Node key를 이름 정리하지 않는다. Alias가 필요한 경우 Legacy loader에서만 처리한다.

### 2.3 기존 Production Node는 contract version 1부터 시작

내부 구현이나 모델 이름에 이미 `v1`, `v2`가 있더라도 Node 계약 버전과 혼합하지 않는다. 현재 사용자에게 보이는 설정, Port와 실행 의미를 `contract_version=1`로 Snapshot한다.

단, Canvas에 보인다는 이유만으로 모든 요소에 실행 Node 계약을 부여하지 않는다.

- Sticky는 WorkflowAnnotation이다.
- Folder는 Canvas layout metadata다.
- Upload와 Drawing은 Artifact source를 만드는 Authoring tool이다.
- `utility.text`는 Legacy read adapter 대상이다.

### 2.4 Default를 명시적으로 저장

Manifest Default는 새 Node 생성에만 사용한다. 기존 Canvas를 읽거나 Workflow를 Publish할 때는 실행 관련 Default를 Node config에 모두 Materialize한다. 이후 Manifest Default가 바뀌어도 기존 Canvas/Workflow의 의미가 바뀌지 않아야 한다.

### 2.5 계약과 Runtime revision 분리

다음 버전은 서로 다른 의미다.

| 값 | 의미 | 저장 위치 |
| --- | --- | --- |
| `contract_version` | Config, Port, 출력 의미 | Canvas/WorkflowVersion |
| `definition_digest` | 사용한 Manifest 본문 | WorkflowVersion/Run |
| `executor_revision` | 실제 실행 코드 | Run |
| `exact_model_id` | 실행 시 선택된 Provider 모델 | Run |
| `renderer_revision` | FFmpeg/렌더러 구현 | Run |

## 3. 현재 결합 지점

리팩터링 시 최소한 다음 결합을 제거하거나 Registry Adapter 뒤로 옮긴다.

### 3.1 Web

- `apps/web/src/lib/canvas-model.ts`
  - `StudioNodeData`가 모든 Node의 설정을 하나의 큰 Optional interface로 가진다.
  - `nodeTemplates`에 Library metadata, Port, Default와 실행 설정이 함께 있다.
  - Node별 필수 입력 검증이 조건문으로 들어 있다.
- `apps/web/src/components/views/generation-canvas.tsx`
  - Provider/Model options가 Node key 조건문이다.
  - 저장 그래프 Migration과 Inspector가 Node별 필드를 직접 다룬다.
  - Step Run 요청의 `parameters`를 모든 Node 공통 객체로 수동 구성한다.
- `apps/web/src/features/workflows/components/workflow-node.tsx`
  - Node key에 따라 Preview, 입력 UX와 Action이 달라진다.

### 3.2 API와 실행기

- `apps/api/app/canvas_runs.py`
  - Canvas `data`의 camelCase 설정을 실행 `parameters`로 수동 평탄화한다.
  - Candidate/approval Node를 key 조건으로 식별한다.
- `apps/api/app/canvas_operations.py`
  - `LOCAL_MODELS`와 큰 Node key 분기에서 Local operation을 선택한다.
- `apps/api/app/providers_generation.py`, `providers_openai.py`
  - Provider 내부에서 Node key로 생성 기능과 결과 계약을 선택한다.
- `apps/api/app/experiments.py`
  - Fixture, 실행 경로, output type/schema가 Node key 조건문에 결합돼 있다.
- `apps/api/app/workflow_execution.py`
  - 일반 Generation Workflow가 Node key별 조건문으로 실행된다.
- `apps/api/app/canvas_temporal.py`, `temporal_workflow.py`
  - Human gate 의미가 특정 Node key에 결합돼 있다.
- `apps/api/app/artifact_lineage.py`
  - Artifact 역할과 Operation 이름이 Node key 조건문이다.

### 3.3 저장 계약

- 기존 Canvas Node는 `data.key`만 가지며 Node contract version이 없다.
- Port type이 `Prompt`, `Video` 같은 비버전 문자열이다.
- 정의, UI 상태, Run 상태와 최근 결과가 같은 `data` 객체에 섞여 있다.
- Run은 Graph Snapshot은 보존하지만 사용한 Node Definition digest를 보존하지 않는다.

## 4. 목표 구조

### 4.1 디렉터리 초안

구현 시 저장소 conventions에 맞게 조정할 수 있지만 책임은 아래처럼 분리한다.

```text
packages/schemas/
  node.definition.v1.schema.json
  node.config-binding.v1.schema.json
  port-types.v1.schema.json

apps/api/app/nodes/
  contracts.py
  registry.py
  validation.py
  bindings.py
  legacy_adapter.py
  definitions/
  executors/

apps/web/src/features/nodes/
  contracts.ts
  registry.ts
  generic-inspector.tsx
  custom-editors/
  legacy-adapter.ts

apps/web/src/features/workflow-annotations/
  annotation-layer.tsx
  annotation-editor.tsx
```

Node Manifest의 Source of Truth는 서버가 읽을 수 있는 공유 JSON 또는 서버 소유 정의로 둔다. Web이 별도의 복제된 Node 목록을 Source of Truth로 가져서는 안 된다. Web은 API 또는 빌드 시 생성된 타입 안전 Snapshot을 소비한다.

### 4.2 공통 Node Definition

모든 Node는 최소한 다음 계약을 가진다.

```text
NodeDefinition
- schema_version
- type_key
- contract_version
- definition_digest
- lifecycle
- display
- ports
- config_schema
- binding_policy
- execution
- editor
- artifact_contract
```

세부 규칙은 `docs/workflow-management-design.md`의 Node 확장 설계를 따른다.

Canvas 전용 요소는 NodeDefinition Registry에 억지로 포함하지 않고 별도의 Canvas element/editor contract로 관리한다. Publish Compiler가 이를 WorkflowAnnotation 또는 Typed Artifact source로 변환한다.

### 4.3 공통 Executor

```text
execute(
  execution_context,
  resolved_node_config,
  typed_inputs
) -> NodeExecutionResult
```

`NodeExecutionResult`에는 최소한 다음 값이 있다.

- output payload
- output Artifact descriptors/IDs
- Artifact type과 schema ID
- Provider request/operation ID
- cost, duration, cache metadata
- lineage roles
- retryability/error classification

Local runner와 Temporal Activity는 `type_key`로 직접 분기하지 않고 Registry가 반환한 Executor를 호출한다.

### 4.4 실행 종류

기존 Node를 다음 execution kind로 분류한다.

| Kind | 예시 | 실행 의미 |
| --- | --- | --- |
| `source` | Prompt, Asset, Character select | Run 시작 시 값 Hydration, Worker 실행 없음 |
| `provider` | Image, Video, TTS, LLM, Skill | 외부 Provider Executor |
| `local` | Video edit, Subtitle, Render, QC | Local media/policy Executor |
| `human_gate` | Candidate select, Caption approval | WAITING_INPUT과 승인 Schema |
| `composite` | Reference analysis, Translate video | 내부 단계가 있지만 외부에는 Atomic Node 계약 |

Human gate 여부와 승인 Schema는 Manifest에 선언한다. 특정 Node key를 Temporal Workflow에 하드코딩하지 않는다.

## 5. 기존 Node 인벤토리 작성

첫 구현 PR에서 코드로부터 Node 인벤토리를 생성하고 Golden fixture로 고정한다. 중복 Library entry는 하나의 `type_key` Definition으로 합친다.

최소 분류 대상:

### Canvas-only/Authoring

- `utility.sticky`: Publish 시 WorkflowAnnotation
- `folder.group`: Draft layout only
- `utility.text`: Legacy → Sticky
- `asset.upload`: 완료된 Artifact source로 정규화
- `utility.drawing`: 저장된 Image Artifact source로 정규화

이 항목들은 production Executor Node Manifest 대상이 아니다. Canvas element/editor contract와 Publish normalization test를 가진다.

### Source

- `prompt.input`
- `asset.select`
- `character.select`
- `generation.brief`
- `format.profile`

### Provider/Generation

- `image.generate`
- `lora.image.generate`
- `character.generate`
- `video.generate`
- `tts.generate`
- `llm.assistant`
- `skill.execute`
- `script.generate`

### Local/Composite

- `reference.decompose`
- `motion.extract`
- `generation.resolve`
- `script.fit_duration`
- `shot.plan`
- `video.edit`
- `video.change_voice`
- `video.translate`
- `subtitle.align`
- `timeline.compose`
- `video.render`
- `media.qc`

### Human gate

- `candidate.select`
- `timeline.compose`의 현재 approval 동작

### Legacy Pipeline decision gate

다음 key는 위 execution kind 인벤토리에 포함되지만 현재 Canvas Library에서 숨겨져 있고 저장 Canvas 사용이 없다. 동시에 기존 Default Generation Pipeline 코드와 테스트에는 연결돼 있다.

- `generation.brief`
- `format.profile`
- `generation.resolve`
- `script.generate`
- `script.fit_duration`
- `shot.plan`
- `candidate.select`
- `media.qc`

Phase 2 Manifest 작성 전에 기존 Generation Run의 유지 여부를 결정한다.

- 유지: Legacy Workflow contract와 `hidden`/`DEPRECATED` lifecycle로 Manifest를 작성한다.
- Canvas Workflow로 완전 대체: 개별 key를 바로 삭제하지 않고 Pipeline 전체를 `DEPRECATED` 처리하고 과거 조회/호환 Adapter를 유지한다.
- `candidate.select`는 범용 Human gate로, `media.qc`는 Final output compiler policy로 승격할 수 있다.

실제 코드 검색 결과가 이 목록과 다르면 구현 전에 인벤토리를 수정한다. 사용되지 않는 Node도 즉시 삭제하지 않고 `legacy` 또는 `hidden` 상태로 분류한다.

Quick/Category에 중복 등록된 `image.generate`, `lora.image.generate`, `character.generate`, `video.generate`, `tts.generate`, `asset.select`는 각각 하나의 NodeDefinition으로 합친다. Library 노출 위치는 placement metadata로 분리한다.

## 6. 단계별 전환 계획

### Phase 0. 현재 동작 Characterization

목적: 리팩터링 전 동작을 테스트로 고정한다.

작업:

- 현재 Node key, Library entry, Port, Default, 모델, execution mode를 JSON fixture로 추출한다.
- 각 실행 가능 Node의 요청 payload와 output Artifact 계약을 기록한다.
- Source Node의 Run 초기 상태를 기록한다.
- Sticky/Folder/Upload/Drawing의 Canvas-only 또는 Authoring 동작을 기록한다.
- Candidate selection과 Caption approval의 WAITING_INPUT/Resume 동작을 고정한다.
- Local과 Temporal에서 같은 DAG가 같은 Node 상태 전이를 가지는지 테스트한다.
- 기존 저장 Canvas fixture를 최소 3종 준비한다.
  - 단순 Prompt → Image
  - Asset/Character → Video
  - Subtitle → Caption approval → Render

완료 기준:

- 리팩터링 전 Golden tests가 통과한다.
- 모든 기존 Node key가 인벤토리에 있다.
- 알려지지 않은 Node key를 검출하는 테스트가 있다.

### Phase 1. Node Protocol과 Registry 기반 추가

목적: 기존 동작을 바꾸지 않고 새 계약 계층을 추가한다.

작업:

- `node.definition.v1` JSON Schema를 추가한다.
- Pydantic/TypeScript 공통 타입을 추가한다.
- Immutable NodeDefinition Registry를 구현한다.
- Registry 시작 시 다음을 검증한다.
  - `(type_key, contract_version)` 유일성
  - Config Schema 유효성
  - Port type 존재
  - Executor/editor 참조 존재
  - `x-workflow-input`과 Config type 호환성
- Definition canonical JSON에서 `definition_digest`를 계산한다.
- API에 Node Definition list/detail read endpoint를 추가한다.
- 기존 `nodeTemplates`를 읽어 Registry 형식으로 변환하는 임시 Legacy adapter를 둔다.

완료 기준:

- Registry가 현재 Node 전체를 조회할 수 있다.
- 잘못된 Manifest가 애플리케이션 시작 또는 테스트에서 실패한다.
- 아직 기존 UI와 실행 경로의 동작은 달라지지 않는다.

### Phase 2. 기존 Node Manifest 작성

목적: 모든 기존 production data/execution Node 계약을 명시적으로 고정한다.

작업:

- 인벤토리의 각 고유 `type_key`에 `contract_version=1` Manifest를 작성한다.
- Canvas-only/Authoring 요소는 production Node Manifest에서 제외하고 별도 editor/normalization contract를 작성한다.
- Quick/Category에 중복된 Template은 같은 Definition을 참조하고 display placement만 분리한다.
- 모든 Config field의 타입, Default, 범위, Enum을 선언한다.
- Port를 버전이 있는 type ID로 매핑한다.
- 변수화 가능한 필드에 `x-workflow-input`을 선언한다.
- Artifact type/schema와 lineage role을 선언한다.
- Source/Utility/Human gate execution kind를 선언한다.
- Caption approval parameter schema를 Manifest로 이동한다.
- Provider/model capability는 Model Registry 참조로 표현한다.
- `asset.select`의 동적 output type을 타입별 Source Node 또는 Publish 시 고정되는 `artifact_type`으로 교체한다.

완료 기준:

- 모든 기존 Canvas Node가 정확히 하나의 Definition으로 해석된다.
- Manifest Snapshot test가 있다.
- `nodeTemplates`와 Manifest의 Port/Default 불일치를 검출한다.

### Phase 3. Canonical Node Config와 Legacy Graph Adapter

목적: 저장된 기존 Canvas와 새로운 계약형 Node를 함께 읽는다.

작업:

- Canonical Node shape를 정의한다.

```text
id
type_key
contract_version
config
ui
```

- 기존 `data.key`, camelCase Optional field를 Canonical config로 변환한다.
- 구버전 Port type과 Handle ID를 새 Port ID로 변환한다.
- 누락된 Default를 `@1` Manifest에서 Materialize한다.
- `status`, output, logs 등 Runtime state는 Canonical definition과 분리한다.
- `utility.sticky`는 Annotation sidecar로, `folder.group`은 Draft UI metadata로 분리한다.
- 완료된 `asset.upload`와 `utility.drawing`은 Typed Artifact source로 변환한다.
- 미완료 Upload와 저장되지 않은 Drawing은 Publish validation error로 유지한다.
- Legacy graph를 다시 저장할 때 계약 버전을 포함하되 기존 Run Snapshot을 변경하지 않는다.
- 알 수 없는 Node는 삭제하지 않고 `UnknownNode` read-only 상태로 연다.

완료 기준:

- 기존 Canvas fixture가 동일한 위치, 설정, Edge로 열린다.
- Load → canonicalize → save → load가 안정적이다.
- Legacy graph 변환 전후 실행 payload가 동일하다.

### Phase 4. Backend Executor Registry 전환

목적: Node key 중앙 조건문을 공통 Executor dispatch로 교체한다.

작업 순서:

1. 기존 실행 함수를 호출하는 Legacy Executor wrapper를 등록한다.
2. Source/Utility/Human gate Executor를 먼저 분리한다.
3. Local media Node를 개별 Executor로 추출한다.
4. Provider Node를 capability 기반 Executor로 추출한다.
5. Fixture Executor도 같은 결과 계약을 구현한다.
6. Artifact type/schema/lineage metadata를 Executor 결과로 이동한다.
7. `canvas_runs.py`의 수동 parameter 평탄화를 Manifest 기반 Config normalization으로 대체한다.
8. 일반 Generation Run과 Canvas Run이 같은 Registry를 사용하게 한다.
9. Local engine과 Temporal Activity가 같은 dispatch 함수를 호출하게 한다.

주의:

- Provider Adapter 자체가 Node UI나 Workflow 의미를 알아서는 안 된다.
- Provider Adapter는 image generation, text generation 같은 capability 요청을 처리한다.
- Node Executor가 Node config를 Provider request로 변환하고 Provider 결과를 Node output 계약으로 변환한다.

완료 기준:

- 신규 Node key를 실행기에 추가하기 위해 중앙 `if/elif`를 수정할 필요가 없다.
- 모든 기존 실행 Node의 Golden execution test가 유지된다.
- Local/Temporal 실행이 같은 Executor revision을 Snapshot한다.
- request hash와 Cache hit 동작이 기존과 같거나 의도적으로 Version된 변경이다.

### Phase 5. Web Registry와 Schema 기반 UI 전환

목적: Node Library와 일반 Inspector를 Manifest에서 생성한다.

작업:

- Node Library를 Registry display metadata로 생성한다.
- Port와 연결 검증을 Registry contract로 교체한다.
- Config Schema 기반 Generic Inspector를 만든다.
- Provider/model options를 capability metadata로 생성한다.
- `x-workflow-input`에서 `Expose as input` UI를 생성한다.
- 기존 복잡한 UI를 Custom Editor로 등록한다.
  - Asset/Character picker
  - Drawing Canvas
  - Caption layout
  - Reference analysis result
- Custom Editor가 없으면 Generic/read-only Fallback을 표시한다.
- Node별 실행 파라미터 구성은 Canonical config serializer로 대체한다.

완료 기준:

- Generic Node는 Web 조건문 없이 Manifest만으로 Library와 Inspector에 표시된다.
- Custom Editor map 이외에 Node key 기반 UI 분기가 증가하지 않는다.
- 기존 Canvas 조작, Undo/Redo, autosave, Step Run이 유지된다.

### Phase 6. Workflow Version 통합

목적: 계약화된 Node를 변수화·게시·실행 가능한 WorkflowVersion에 연결한다.

작업:

- WorkflowVersion의 각 Node에 `contract_version`, `definition_digest`를 고정한다.
- Publish 시 Manifest 기준으로 Config와 Binding을 검증한다.
- 모든 실행 Default를 WorkflowVersion graph에 Materialize한다.
- WorkflowRun에 Executor/Definition/Model/Renderer revision을 Snapshot한다.
- Workflow input resolver가 `x-workflow-input`에 허용된 경로만 수정하게 한다.
- Primary/Secondary output에서 역방향으로 도달 가능한 Node만 Publish graph에 포함한다.
- Sticky는 Version Annotation으로 복사하고 execution graph/hash에서 제외한다.
- Folder, 연결되지 않은 Node와 미선언 Side branch를 execution graph에서 제외한다.
- Published Version Viewer는 Frozen graph와 별도의 편집 가능한 Annotation Layer를 사용한다.
- 기존 WorkflowVersion은 새 Manifest 등록 후에도 hash가 바뀌지 않게 한다.

완료 기준:

- 같은 WorkflowVersion이 Registry 변경 전후 같은 Node 계약으로 해석된다.
- 새 Node 등록이 기존 Version graph/hash를 변경하지 않는다.
- Node `@2` 등록 후에도 `@1` Workflow를 조회하고 실행할 수 있다.
- Annotation 수정 전후 WorkflowVersion hash와 Run payload가 동일하다.
- Publish 후 Canvas를 Lock/Unlock하지 않고 Draft 편집을 계속할 수 있다.

### Phase 7. Legacy 제거와 Architecture Guard

목적: 임시 Adapter와 중복 정의를 제거하고 회귀를 방지한다.

작업:

- 모든 기존 Canvas가 계약 버전을 포함한 뒤 쓰기 경로의 Legacy adapter를 제거한다.
- Read-only Legacy loader는 지원 기간 동안 유지한다.
- `nodeTemplates`의 Source of Truth 역할을 제거한다.
- 중앙 Node key dispatch와 공통 Optional Config interface를 축소한다.
- CI Architecture check를 추가한다.
  - Manifest 없는 production Node key 금지
  - 등록되지 않은 Executor/editor 참조 금지
  - Provider layer의 UI Node key 의존 금지
  - WorkflowVersion의 미등록 contract version 금지
  - Canvas-only 요소가 Workflow execution graph에 들어가는 경로 금지
  - Annotation이 Version hash/Cache key/Run payload에 들어가는 경로 금지
- Dead Definition을 삭제하지 않고 lifecycle 상태와 사용 현황을 확인한다.

완료 기준:

- 새 Generic Node 추가가 Manifest + Executor + tests로 끝난다.
- 중앙 Library/Executor 조건문에 Node key를 추가할 필요가 없다.
- 기존 Node 계약과 WorkflowVersion 회귀 테스트가 CI에서 강제된다.

## 7. 데이터 Migration

### 7.1 Canvas

기존 Node:

```json
{
  "id": "video-1",
  "data": {
    "key": "video.generate",
    "model": "video.omni",
    "durationSeconds": 6,
    "aspectRatio": "9:16",
    "status": "SUCCEEDED"
  }
}
```

Canonical Node:

```json
{
  "id": "video-1",
  "type_key": "video.generate",
  "contract_version": 1,
  "config": {
    "model_alias": "video.omni",
    "duration_seconds": 6,
    "aspect_ratio": "9:16"
  },
  "ui": {
    "position": { "x": 120, "y": 80 },
    "label": "Video generator"
  }
}
```

Runtime 상태와 결과는 Canvas definition에서 분리해 Run/Experiment 조회로 복원하는 것을 목표로 한다. 전환 기간에는 UI state sidecar를 허용하되 Workflow Publish sanitizer가 반드시 제거한다.

Canvas-only 요소는 다음처럼 이동한다.

```text
utility.sticky  → workflow_annotations
folder.group    → Canvas Draft UI metadata
utility.text    → legacy loader → Annotation
asset.upload    → typed immutable Artifact source
utility.drawing → typed immutable Image Artifact source
```

Publish 후 Canvas는 잠그지 않는다. WorkflowVersion graph만 불변으로 저장하고 Canvas는 `base_version_id`를 가진 Draft로 계속 편집한다.

### 7.2 Run과 Experiment

기존 Run Snapshot은 변경하지 않는다. 응답 Adapter가 `node_key`를 `type_key@1`로 해석한다. 신규 Run부터 다음 값을 저장한다.

- `node_contract_version`
- `node_definition_digest`
- `executor_revision`
- normalized config snapshot

### 7.3 Unknown/Retired Node

- Definition을 찾지 못해도 Canvas와 Workflow를 삭제하거나 자동 수정하지 않는다.
- UI는 ID, 저장 Config와 Edge를 읽기 전용으로 보여준다.
- Publish와 신규 Run은 명확한 호환성 오류로 차단한다.
- 과거 Run과 Artifact는 계속 조회할 수 있다.

## 8. 테스트 계획

### Contract tests

- 모든 Manifest의 Schema validation
- `type_key@contract_version` 유일성
- Definition digest 안정성
- Config default materialization
- Port compatibility와 Binding policy

### Compatibility tests

- 기존 Canvas fixture load/save
- Legacy Config → Canonical Config Snapshot
- 기존 Run response 조회
- Deprecated/Unknown Node read-only 표시
- Sticky/Folder/Upload/Drawing Publish normalization
- Frozen Version graph와 mutable Annotation 분리

### Executor parity tests

- 기존 Node별 normalized request
- Output Artifact type/schema
- Provider request/operation ID
- Cost, duration, request hash, cache key
- Artifact lineage role
- Retryable/non-retryable error

### Engine tests

- Local과 Temporal의 동일 dispatch
- 병렬 Wave와 dependency 처리
- Human gate WAITING_INPUT/Resume
- Cancel/Retry/Restart 복구
- 선언된 Output의 reverse reachability와 unused branch 제외

### Web tests

- Registry 기반 Node Library
- Generic Inspector field/validation
- Custom Editor 선택과 Fallback
- Port 연결과 다중 입력
- `Expose as input`
- 기존 Canvas Undo/Redo/autosave
- Published Version read-only graph와 editable Annotation overlay
- `Edit as draft`가 Version을 Unlock하지 않는지

## 9. 위험과 대응

| 위험 | 대응 |
| --- | --- |
| 기존 Default가 암묵적이라 Snapshot이 달라짐 | Phase 0 Golden fixture와 명시적 materialization |
| Web/API Manifest가 달라짐 | 서버 Source of Truth와 generated types/snapshot |
| Executor 추출 중 request hash 변경 | normalized config parity test |
| Human gate가 일반 Executor와 다름 | execution kind와 approval schema를 계약에 포함 |
| Custom UI가 너무 많아짐 | Generic Inspector 우선, editor map은 예외만 허용 |
| 구버전 Executor 유지 비용 | lifecycle/usage 측정 후 Retire, 과거 조회 계약은 영구 유지 |
| Port version 도입으로 기존 Edge 손실 | Legacy handle adapter와 round-trip fixture |
| 메모 수정이 Version 재현성을 변경 | Annotation 별도 테이블과 hash/payload exclusion test |
| 연결되지 않은 Node가 Run 진행률에 포함 | Output reachability compiler로 Publish graph pruning |

## 10. Rollout과 Rollback

- 각 Phase는 Feature flag 또는 Adapter 경계를 두어 기존 경로로 되돌릴 수 있게 한다.
- DB Migration은 기존 JSON과 column을 즉시 삭제하지 않는 Additive 방식으로 시작한다.
- Registry dispatch 전환 시 Node family 단위로 활성화한다.
- Web Registry 전환과 Backend Executor 전환을 같은 배포에 강제로 묶지 않는다.
- 문제 발생 시 신규 Registry dispatch만 끄고 기존 저장 데이터는 유지한다.
- 기존 WorkflowVersion과 Run Snapshot을 되쓰는 Rollback은 금지한다.

## 11. 전체 완료 기준

- 모든 기존 production data/execution Node에 Manifest와 `contract_version=1`이 있다.
- Sticky/Folder/Upload/Drawing은 NodeRun 대상이 아닌 Annotation/layout/Authoring contract로 분리됐다.
- 모든 기존 Canvas를 데이터 손실 없이 열고 저장할 수 있다.
- Node Library, 일반 Inspector, Port validation과 Workflow binding이 같은 Definition을 사용한다.
- Local과 Temporal이 같은 Executor Registry를 사용한다.
- WorkflowVersion과 Run이 Node contract/runtime revision을 Snapshot한다.
- 중앙 Node key 조건문을 수정하지 않고 Generic Node를 추가할 수 있다.
- Breaking Node 변경은 새 contract version과 명시적 Draft Migration을 요구한다.
- Deprecated Node를 사용하는 기존 Workflow를 조회하고 정책 범위 안에서 실행할 수 있다.
- Published WorkflowVersion을 읽기 전용으로 보고 메모만 별도로 수정할 수 있다.
- Annotation 수정은 Version hash, Cache key와 Run payload를 바꾸지 않는다.
- 선언된 Output에 도달하는 Node만 Workflow execution graph와 진행률에 포함된다.
- Architecture guard와 계약/호환성 테스트가 CI에서 통과한다.

## 12. 권장 PR 단위

리뷰와 Rollback을 쉽게 하기 위해 다음 단위로 나눈다.

1. Characterization fixtures와 Node inventory
2. Node Definition Schema/Registry/API
3. 기존 Node Manifest 전체와 validation
4. Legacy Canvas → Canonical adapter
5. Source/Human gate Executor 전환
6. Local media Executor 전환
7. Provider Executor 전환
8. Web Library/Port Registry 전환
9. Generic Inspector와 Custom Editor adapter
10. WorkflowVersion snapshot/binding 통합
11. Legacy write 제거와 Architecture CI guard

각 PR은 동작 변경인지 구조 변경인지 명시하고, 구조 변경 PR에서는 기존 Golden output의 의도하지 않은 변경을 허용하지 않는다.
