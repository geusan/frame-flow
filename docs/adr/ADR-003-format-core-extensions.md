# ADR-003: FormatCore + Extensions

Status: Accepted

모든 생성 노드는 `format.core.v1`만으로 동작한다. Recipe별 실험 필드는 이름이 격리된 Extensions 아래에 저장한다. Extension을 소비하는 노드는 지원 Schema ID를 명시한다. Provider 구조화 출력 Schema는 내부 Schema에서 안전한 부분집합으로 변환하고 결과는 내부 Schema로 다시 검증한다.

