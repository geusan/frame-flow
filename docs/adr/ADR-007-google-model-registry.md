# ADR-007: Google Model Registry

Status: Accepted

Workflow 노드는 논리적 모델 별칭을 사용한다. Registry가 실제 모델 ID, Region, 기능, Quota, 비용, Fallback과 Retirement를 관리한다. 실행 계획에는 정확한 모델 ID가 고정되며 과거 Run은 Registry 변경의 영향을 받지 않는다. 모델 수명주기 변경은 Runbook에 따라 새 Registry Revision으로 배포한다.

