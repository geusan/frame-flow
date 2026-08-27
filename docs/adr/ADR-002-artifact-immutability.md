# ADR-002: Artifact 불변성

Status: Accepted

모든 원본·중간·최종 결과에는 새 Artifact ID와 SHA-256을 발급한다. 재시도와 재생성은 기존 객체를 덮어쓰지 않는다. 선택은 후보 삭제가 아니라 SelectionArtifact 생성으로 기록한다. 이를 통해 Cache, 재현, 비용 감사와 Lineage를 안정적으로 유지한다.

