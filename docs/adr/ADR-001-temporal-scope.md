# ADR-001: Temporal 사용 범위

Status: Accepted

Temporal은 사용자 그래프 정의 저장소가 아니라 실행 내구성 계층으로 사용한다. PostgreSQL이 Workflow, Run, NodeRun과 사용자 상태의 기준이다. Temporal은 Retry, Timeout, Cancel, Provider polling, 사용자 선택 대기와 Worker 복구를 담당한다. UI와 API에는 Temporal 용어를 노출하지 않는다.

