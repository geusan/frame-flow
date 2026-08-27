# Worker recovery runbook

1. PostgreSQL에서 RUNNING 또는 SUBMITTED 상태이며 heartbeat가 만료된 NodeRun을 조회한다.
2. `provider_operation_id`가 있으면 새 요청을 제출하지 말고 Provider 상태를 조회한다.
3. 완료된 Provider 결과가 있으면 Hash를 검증해 새 Artifact를 등록하고 NodeRun을 성공 처리한다.
4. operation이 진행 중이면 Reconciler poll을 재등록한다.
5. operation을 찾을 수 없고 제출 기록이 확정되지 않은 경우에만 동일 request hash와 idempotency key로 Retry한다.
6. Run 비용 상한과 취소 상태를 다시 확인한 뒤 하위 노드를 Queue한다.
7. 모든 조치를 AuditEvent와 trace/run/node/attempt/provider ID로 기록한다.

