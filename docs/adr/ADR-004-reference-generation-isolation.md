# ADR-004: Reference와 Generation 권한 분리

Status: Accepted

Reference Analyzer만 원본 버킷을 읽는다. Generation Worker는 Format과 승인된 생성 자산 버킷만 읽는다. `analysis_only`와 `unknown`은 생성 입력 포트 연결을 거부한다. Terraform에는 Generation Worker가 Reference 버킷을 읽는 IAM Binding을 만들지 않는다.

