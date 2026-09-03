# Provider 인증과 실행 권한

Settings의 Provider 연결은 외부 서비스를 호출하는 실행 자격증명만 저장한다. API 활성화, 결제 연결, IAM 정책 수정 권한을 실행 자격증명에 함께 주지 않는다.

## Provider별 인증 요약

| Settings Provider | 등록 방식 | 실행에 필요한 권한 |
| --- | --- | --- |
| OpenAI | Project API key 또는 ChatGPT OAuth | GCP IAM Role 없음. 사용하는 Responses, Image, TTS 모델에 접근 가능한 Project 자격증명 |
| xAI | API key | GCP IAM Role 없음. 사용하는 Grok API와 모델 접근 권한 |
| Google AI | Service Account JSON | 아래 Google Cloud 서비스별 최소 IAM Role |
| Claude | Anthropic API key 또는 Claude Code setup token | GCP IAM Role 없음. 선택한 Anthropic/Claude Code 인증 범위 |
| ElevenLabs | API key | GCP IAM Role 없음. 사용하는 TTS/STT 모델에 접근 가능한 key |
| Seedance | ModelArk API key | GCP IAM Role 없음. 사용하는 영상 모델 endpoint 접근 권한 |
| Kling | Access key + Secret key | GCP IAM Role 없음. 이미지/영상 생성 API 접근 권한 |
| MiniMax | API key | GCP IAM Role 없음. 선택한 리전의 API와 모델 접근 권한 |
| fal.ai | API key | GCP IAM Role 없음. 추론·LoRA 학습 API 접근 권한 |
| Cloudflare R2 | Bucket-scoped S3 Access key | GCP IAM Role 없음. LoRA ZIP prefix에 대한 Object Read & Write 권한 |

각 외부 Provider의 관리자 권한이나 전체 계정 key를 요구하지 않는다. 가능하면 프로젝트, 모델, 버킷 또는 prefix 단위로 범위를 제한한다.

## Google AI Service Account

Frameflow의 Google AI 연결은 Service Account JSON 하나만 사용한다. API key와 사용자 Application Default Credentials 파일은 사용하지 않는다. 프로젝트 ID는 JSON의 `project_id`에서 가져온다.

| 기능 | 호출 서비스 | 필수 Runtime Role | 부여 범위 |
| --- | --- | --- | --- |
| LLM, Image, Character, Gemini TTS | Vertex AI Generative AI | Vertex AI User `roles/aiplatform.user` | Service Account JSON의 Project |
| Veo 영상 생성 | Vertex AI | Vertex AI User `roles/aiplatform.user` | Service Account JSON의 Project |
| Speech subtitles | Speech-to-Text V2, Chirp 3 | Cloud Speech Client `roles/speech.client` | Service Account JSON의 Project |
| Translate Video의 STT | Speech-to-Text V2, Chirp 3 | Cloud Speech Client `roles/speech.client` | Service Account JSON의 Project |
| Veo GCS 출력 저장·회수 | Cloud Storage | Storage Object User `roles/storage.objectUser` | `GOOGLE_VIDEO_OUTPUT_GCS_URI`의 대상 Bucket에만 |

`roles/speech.serviceAgent`는 Google 관리형 Speech service agent용 역할이므로 Frameflow의 사용자 관리 Service Account에 부여하지 않는다. Runtime Service Account에는 Owner, Editor, Vertex AI Administrator, Cloud Speech Administrator, Storage Administrator가 필요하지 않다.

Google 공식 권한 문서:

- Vertex AI Generative AI: <https://cloud.google.com/vertex-ai/generative-ai/docs/access-control>
- Speech-to-Text: <https://cloud.google.com/speech-to-text/docs/iam>
- Cloud Storage: <https://cloud.google.com/storage/docs/access-control/iam-roles>

## Google 역할 부여 예시

```bash
PROJECT_ID="your-project-id"
SERVICE_ACCOUNT="frameflow-runner@${PROJECT_ID}.iam.gserviceaccount.com"

gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${SERVICE_ACCOUNT}" \
  --role="roles/aiplatform.user"

gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${SERVICE_ACCOUNT}" \
  --role="roles/speech.client"
```

Veo가 `gs://your-bucket/path`로 결과를 내보내는 경우에만 Bucket 범위 역할을 추가한다.

```bash
gcloud storage buckets add-iam-policy-binding gs://your-bucket \
  --member="serviceAccount:${SERVICE_ACCOUNT}" \
  --role="roles/storage.objectUser"
```

API 활성화는 배포 관리자 자격증명으로 한 번 수행한다. 이 권한을 Runtime Service Account에 주지 않는다.

```bash
gcloud services enable \
  aiplatform.googleapis.com \
  speech.googleapis.com \
  --project="$PROJECT_ID"
```

## 변경 후 확인

Settings의 Google AI 카드가 `Ready`이고 다음 네 가지가 맞아야 한다.

1. 인증 방식이 `service_account`다.
2. Service Account JSON은 `has_value=true`지만 원문은 API 응답에 노출되지 않는다.
3. Gemini/Veo 모델 region은 Vertex AI location을 사용한다.
4. Chirp 3 모델 region은 Speech-to-Text location을 사용한다.

역할 변경은 기존 access token이 만료될 때까지 기다릴 필요 없이 일반적으로 다음 API 호출부터 적용된다. 실행이 계속 403이면 오류에 표시된 permission과 resource project가 위 역할을 부여한 대상과 같은지 확인한다.
