# ADR-006: 부분 재실행과 Cache Invalidation

Status: Accepted

Cache key는 node type/version, normalized config, input hashes, prompt hash, output schema, provider, exact model ID, seed와 renderer version을 포함한다. 상위 결과 변경 시 하위를 삭제하지 않고 STALE 처리한다. Retry는 동일 요청, Regenerate는 변경된 생성 설정, Fork는 기존 결과를 보존한 새 Run 분기다.

