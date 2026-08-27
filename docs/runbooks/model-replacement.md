# Model replacement runbook

1. 새 모델을 비활성 Registry Entry로 등록한다.
2. Region, 입력·출력 Modality, Structured Output 제약, Quota와 비용을 확인한다.
3. Provider Adapter Contract Test와 실제 API Canary를 분리 실행한다.
4. 동일 GenerationSpec으로 기존 모델과 Golden 비교를 수행한다.
5. Fallback과 Retirement Date를 설정한다.
6. 새 Registry Revision을 배포하고 논리적 별칭을 전환한다.
7. 새 Run이 정확한 모델 ID를 Snapshot하는지 확인한다.
8. 과거 Run Replay가 기존 모델 ID를 유지하는지 확인한다.

문제가 발생하면 별칭만 이전 Registry Entry로 되돌린다. 기존 Artifact와 Run을 수정하지 않는다.

