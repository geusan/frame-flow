# ADR-005: Prompt·Schema 버전 관리

Status: Accepted

Prompt와 Output Schema는 코드와 같은 불변 버전 자산이다. Run은 Template ID/Version, rendered prompt, Schema ID/Version, exact model ID, parameters, seed, input hashes와 prompt hash를 Snapshot한다. 수정 시 기존 버전을 갱신하지 않고 새 버전을 만든다.

