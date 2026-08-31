from __future__ import annotations

import os
import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .database import ProviderSettingRecord, SessionLocal
from .domain import utc_now
from .google_service_account import GOOGLE_SERVICE_ACCOUNT_ENV, validate_service_account_json
from .local_subscription_agents import LocalAuthStatus, check_local_provider_auth


@dataclass(frozen=True)
class ProviderField:
    key: str
    label: str
    env_var: str
    secret: bool = False
    required: bool = False
    default: str = ""
    placeholder: str = ""
    help_text: str = ""
    auth_methods: tuple[str, ...] = ()
    input_kind: str = "text"


@dataclass(frozen=True)
class ProviderAuthMethod:
    key: str
    label: str
    description: str
    kind: str = "api_key"
    required_fields: tuple[str, ...] = ()
    external: bool = False


@dataclass(frozen=True)
class ProviderDefinition:
    key: str
    label: str
    description: str
    fields: tuple[ProviderField, ...]
    auth_methods: tuple[ProviderAuthMethod, ...]
    default_auth_method: str
    order: int


def _field(
    key: str,
    label: str,
    env_var: str,
    *,
    secret: bool = False,
    default: str = "",
    placeholder: str = "",
    help_text: str = "",
    auth_methods: tuple[str, ...] = (),
    input_kind: str = "text",
) -> ProviderField:
    return ProviderField(
        key,
        label,
        env_var,
        secret=secret,
        default=default,
        placeholder=placeholder,
        help_text=help_text,
        auth_methods=auth_methods,
        input_kind=input_kind,
    )


PROVIDER_DEFINITIONS: dict[str, ProviderDefinition] = {
    "openai": ProviderDefinition(
        key="openai",
        label="OpenAI",
        description="GPT models and Codex agent runs",
        fields=(
            _field("api_key", "API key", "OPENAI_API_KEY", secret=True, placeholder="sk-…", auth_methods=("api_key",)),
            _field("base_url", "Base URL", "OPENAI_BASE_URL", placeholder="https://api.openai.com/v1", auth_methods=("api_key",)),
            _field("organization_id", "Organization ID", "OPENAI_ORG_ID", placeholder="org_…", auth_methods=("api_key",)),
            _field("project_id", "Project ID", "OPENAI_PROJECT_ID", placeholder="proj_…", auth_methods=("api_key",)),
        ),
        auth_methods=(
            ProviderAuthMethod(
                key="api_key",
                label="API key",
                description="Use OpenAI API Platform billing.",
                required_fields=("api_key",),
            ),
            ProviderAuthMethod(
                key="chatgpt_oauth",
                label="ChatGPT OAuth",
                description="Use the ChatGPT subscription connected to the Codex host.",
                kind="oauth",
                external=True,
            ),
        ),
        default_auth_method="api_key",
        order=0,
    ),
    "google": ProviderDefinition(
        key="google",
        label="Google AI",
        description="Gemini, Veo, and Google Cloud media services",
        fields=(
            _field("api_key", "Gemini API key", "GEMINI_API_KEY", secret=True, placeholder="AIza…", auth_methods=("api_key",)),
            _field("project_id", "Google Cloud project", "GOOGLE_CLOUD_PROJECT", placeholder="my-gcp-project", help_text="Optional with Gemini API; required for Chirp 3 Speech-to-Text.", auth_methods=("api_key", "vertex")),
            _field("location", "Google Cloud location", "GOOGLE_CLOUD_LOCATION", default="us-central1", placeholder="us-central1", auth_methods=("api_key", "vertex")),
            _field("credentials_path", "Application credentials path", "GOOGLE_APPLICATION_CREDENTIALS", placeholder="/run/secrets/google-application-default-credentials.json", help_text="Required for Chirp 3 and must be readable by the API and Temporal worker.", auth_methods=("api_key", "vertex")),
            _field("service_account_json", "Service Account JSON", GOOGLE_SERVICE_ACCOUNT_ENV, secret=True, placeholder="Select the downloaded Service Account JSON file", help_text="Stored as a write-only DB secret and loaded directly by API and Temporal workers.", auth_methods=("api_key", "vertex"), input_kind="service_account_json"),
            _field("speech_location", "Speech location", "GOOGLE_SPEECH_LOCATION", default="us", placeholder="us", auth_methods=("api_key", "vertex")),
            _field("video_output_gcs_uri", "Video output GCS URI", "GOOGLE_VIDEO_OUTPUT_GCS_URI", placeholder="gs://bucket/path", auth_methods=("vertex",)),
        ),
        auth_methods=(
            ProviderAuthMethod("api_key", "Gemini API", "Connect with a Gemini API key from Google AI Studio.", required_fields=("api_key",)),
            ProviderAuthMethod("vertex", "Vertex AI", "Use a Google Cloud project and Application Default Credentials.", kind="cloud", required_fields=("project_id",)),
        ),
        default_auth_method="api_key",
        order=1,
    ),
    "claude": ProviderDefinition(
        key="claude",
        label="Claude",
        description="Anthropic API and Claude Code agent runs",
        fields=(
            _field("api_key", "Anthropic API key", "ANTHROPIC_API_KEY", secret=True, placeholder="sk-ant-…", auth_methods=("api_key",)),
            _field("setup_token", "Claude Code setup token", "CLAUDE_CODE_OAUTH_TOKEN", secret=True, placeholder="Paste the token from claude setup-token", help_text="Generate on the execution host with: claude setup-token", auth_methods=("setup_token",)),
            _field("base_url", "Base URL", "ANTHROPIC_BASE_URL", placeholder="https://api.anthropic.com", auth_methods=("api_key",)),
        ),
        auth_methods=(
            ProviderAuthMethod("api_key", "API key", "Use Anthropic Console usage-based billing.", required_fields=("api_key",)),
            ProviderAuthMethod("setup_token", "Setup token", "Run Claude Code with a long-lived subscription token.", kind="setup_token", required_fields=("setup_token",)),
        ),
        default_auth_method="api_key",
        order=2,
    ),
    "elevenlabs": ProviderDefinition(
        key="elevenlabs",
        label="ElevenLabs",
        description="Voice generation, speech-to-text, and audio models",
        fields=(
            _field("api_key", "API key", "ELEVENLABS_API_KEY", secret=True, placeholder="Your ElevenLabs API key"),
            _field("base_url", "Base URL", "ELEVENLABS_BASE_URL", default="https://api.elevenlabs.io", placeholder="https://api.elevenlabs.io"),
            _field("voice_id", "Default voice ID", "ELEVENLABS_VOICE_ID", placeholder="Optional default voice"),
        ),
        auth_methods=(ProviderAuthMethod("api_key", "API key", "Use a scoped ElevenLabs API key.", required_fields=("api_key",)),),
        default_auth_method="api_key",
        order=3,
    ),
    "seedance": ProviderDefinition(
        key="seedance",
        label="Seedance",
        description="ByteDance video generation through ModelArk",
        fields=(
            _field("api_key", "API key", "LAS_API_KEY", secret=True, placeholder="Your ModelArk API key"),
            _field("base_url", "Base URL", "SEEDANCE_BASE_URL", default="https://operator.las.ap-southeast-1.bytepluses.com", placeholder="https://operator.las.ap-southeast-1.bytepluses.com"),
        ),
        auth_methods=(ProviderAuthMethod("api_key", "API key", "Use a server-side ModelArk bearer token.", required_fields=("api_key",)),),
        default_auth_method="api_key",
        order=4,
    ),
    "kling": ProviderDefinition(
        key="kling",
        label="Kling",
        description="Kling AI video and image generation",
        fields=(
            _field("access_key", "Access key", "KLING_ACCESS_KEY", secret=True, placeholder="Access key"),
            _field("secret_key", "Secret key", "KLING_SECRET_KEY", secret=True, placeholder="Secret key"),
            _field("base_url", "Base URL", "KLING_BASE_URL", default="https://api.klingai.com", placeholder="https://api.klingai.com"),
        ),
        auth_methods=(ProviderAuthMethod("api_key", "API credentials", "Use the access key and secret issued by Kling AI.", required_fields=("access_key", "secret_key")),),
        default_auth_method="api_key",
        order=5,
    ),
    "minimax": ProviderDefinition(
        key="minimax",
        label="MiniMax",
        description="MiniMax text, speech, image, and video models",
        fields=(
            _field("api_key", "API key", "MINIMAX_API_KEY", secret=True, placeholder="Your MiniMax API key"),
            _field("api_host", "API host", "MINIMAX_API_HOST", default="https://api.minimax.io", placeholder="https://api.minimax.io", help_text="Use the host that matches the region where the key was created."),
        ),
        auth_methods=(ProviderAuthMethod("api_key", "API key", "Use a server-side MiniMax bearer token.", required_fields=("api_key",)),),
        default_auth_method="api_key",
        order=6,
    ),
    "fal": ProviderDefinition(
        key="fal",
        label="fal.ai",
        description="Serverless generative media inference and model APIs",
        fields=(
            _field("api_key", "API key", "FAL_KEY", secret=True, placeholder="Your fal API key"),
        ),
        auth_methods=(ProviderAuthMethod("api_key", "API key", "Use a server-side fal API key.", required_fields=("api_key",)),),
        default_auth_method="api_key",
        order=7,
    ),
    "r2": ProviderDefinition(
        key="r2",
        label="Cloudflare R2",
        description="Private LoRA training datasets with time-limited download URLs",
        fields=(
            _field("account_id", "Cloudflare account ID", "R2_ACCOUNT_ID", placeholder="32-character account ID", help_text="R2 Overview에서 확인할 수 있습니다.", auth_methods=("s3_api",)),
            _field("bucket", "Training bucket", "R2_TRAINING_BUCKET", default="frameflow-lora-training", placeholder="frameflow-lora-training", help_text="LoRA ZIP 전용 비공개 버킷 이름입니다.", auth_methods=("s3_api",)),
            _field("access_key_id", "Access Key ID", "R2_ACCESS_KEY_ID", secret=True, placeholder="R2 S3 Access Key ID", auth_methods=("s3_api",)),
            _field("secret_access_key", "Secret Access Key", "R2_SECRET_ACCESS_KEY", secret=True, placeholder="R2 S3 Secret Access Key", auth_methods=("s3_api",)),
            _field("endpoint_url", "S3 endpoint override", "R2_ENDPOINT_URL", placeholder="https://<ACCOUNT_ID>.r2.cloudflarestorage.com", help_text="기본 jurisdiction이면 비워 두세요.", auth_methods=("s3_api",)),
            _field("key_prefix", "Object key prefix", "R2_TRAINING_PREFIX", default="lora-training", placeholder="lora-training", auth_methods=("s3_api",)),
            _field("signed_url_ttl_seconds", "Signed URL lifetime", "R2_PRESIGNED_URL_TTL_SECONDS", default="3600", placeholder="3600", help_text="fal이 ZIP을 내려받을 수 있는 시간(초)입니다.", auth_methods=("s3_api",)),
        ),
        auth_methods=(
            ProviderAuthMethod(
                "s3_api",
                "R2 S3 API",
                "Use an Object Read & Write token scoped only to the LoRA training bucket.",
                required_fields=("account_id", "bucket", "access_key_id", "secret_access_key"),
            ),
        ),
        default_auth_method="s3_api",
        order=8,
    ),
}


AUTH_METHOD_CONFIG_KEY = "_auth_method"


def _record_values(record: ProviderSettingRecord) -> dict[str, str]:
    return {
        **{str(key): str(value) for key, value in (record.configuration or {}).items()},
        **{str(key): str(value) for key, value in (record.secrets or {}).items()},
    }


def _auth_method_for(record: ProviderSettingRecord, definition: ProviderDefinition) -> ProviderAuthMethod:
    configured_method = str((record.configuration or {}).get(AUTH_METHOD_CONFIG_KEY, "")).strip()
    by_key = {method.key: method for method in definition.auth_methods}
    if configured_method in by_key:
        return by_key[configured_method]

    values = _record_values(record)
    for method in definition.auth_methods:
        if method.required_fields and all(values.get(key, "").strip() for key in method.required_fields):
            return method
    return by_key[definition.default_auth_method]


def provider_auth_method_key(record: ProviderSettingRecord) -> str:
    return _auth_method_for(record, PROVIDER_DEFINITIONS[record.provider]).key


def _local_connection_status(
    record: ProviderSettingRecord,
    method: ProviderAuthMethod,
    values: dict[str, str],
) -> LocalAuthStatus | None:
    return check_local_provider_auth(record.provider, method.key, values)


def provider_is_configured(record: ProviderSettingRecord) -> bool:
    definition = PROVIDER_DEFINITIONS[record.provider]
    method = _auth_method_for(record, definition)
    values = _record_values(record)
    local_status = _local_connection_status(record, method, values)
    if local_status is not None:
        return bool(record.enabled and local_status.ready)
    return bool(
        record.enabled
        and not method.external
        and all(values.get(key, "").strip() for key in method.required_fields)
    )


def ensure_provider_settings(db: Session) -> list[ProviderSettingRecord]:
    """Create each provider once, copying available environment values into the DB."""
    existing = {row.provider: row for row in db.scalars(select(ProviderSettingRecord)).all()}
    created = False
    for provider, definition in PROVIDER_DEFINITIONS.items():
        if provider in existing:
            continue
        configuration: dict[str, str] = {}
        secrets: dict[str, str] = {}
        imported_from_environment = False
        for field in definition.fields:
            environment_value = os.getenv(field.env_var)
            value = environment_value if environment_value not in (None, "") else field.default
            if value:
                (secrets if field.secret else configuration)[field.key] = value
            if environment_value not in (None, ""):
                imported_from_environment = True
        required_values = {**configuration, **secrets}
        selected_method = next(
            (
                method
                for method in definition.auth_methods
                if method.required_fields
                and all(required_values.get(key, "").strip() for key in method.required_fields)
            ),
            next(method for method in definition.auth_methods if method.key == definition.default_auth_method),
        )
        configuration[AUTH_METHOD_CONFIG_KEY] = selected_method.key
        enabled = bool(
            not selected_method.external
            and all(required_values.get(key, "").strip() for key in selected_method.required_fields)
        )
        record = ProviderSettingRecord(
            id=f"provider_{provider}",
            provider=provider,
            enabled=enabled,
            configuration=configuration,
            secrets=secrets,
            source="environment" if imported_from_environment else "default",
            updated_at=utc_now(),
        )
        db.add(record)
        existing[provider] = record
        created = True
    if created:
        try:
            db.commit()
        except IntegrityError:
            # API and Temporal worker may seed simultaneously during Compose startup.
            db.rollback()
    records = {row.provider: row for row in db.scalars(select(ProviderSettingRecord)).all()}
    return [records[key] for key in sorted(PROVIDER_DEFINITIONS, key=lambda item: PROVIDER_DEFINITIONS[item].order) if key in records]


def apply_provider_settings_to_environment(records: list[ProviderSettingRecord]) -> None:
    """Keep existing provider clients compatible while making the DB authoritative."""
    for record in records:
        definition = PROVIDER_DEFINITIONS.get(record.provider)
        if not definition:
            continue
        auth_method = _auth_method_for(record, definition).key
        values = _record_values(record)
        for field in definition.fields:
            value = values.get(field.key, "").strip()
            applies_to_method = not field.auth_methods or auth_method in field.auth_methods
            if record.enabled and applies_to_method and value:
                os.environ[field.env_var] = value
            elif record.source == "database":
                os.environ.pop(field.env_var, None)


def refresh_provider_environment() -> None:
    """Refresh long-running worker processes before executing provider work."""
    with SessionLocal() as db:
        records = ensure_provider_settings(db)
        apply_provider_settings_to_environment(records)


def get_provider_record(db: Session, provider: str) -> ProviderSettingRecord | None:
    return db.scalar(select(ProviderSettingRecord).where(ProviderSettingRecord.provider == provider))


def provider_settings_payload(record: ProviderSettingRecord) -> dict[str, Any]:
    definition = PROVIDER_DEFINITIONS[record.provider]
    auth_method = _auth_method_for(record, definition)
    values = _record_values(record)
    local_status = _local_connection_status(record, auth_method, values)
    configured = bool(
        record.enabled
        and (
            local_status.ready
            if local_status is not None
            else not auth_method.external and all(values.get(key, "").strip() for key in auth_method.required_fields)
        )
    )
    return {
        "provider": record.provider,
        "label": definition.label,
        "description": definition.description,
        "enabled": record.enabled,
        "configured": configured,
        "connection": local_status.payload() if local_status is not None else None,
        "auth_method": auth_method.key,
        "auth_methods": [
            {
                "key": method.key,
                "label": method.label,
                "description": method.description,
                "kind": method.kind,
                "external": method.external,
                "required_fields": list(method.required_fields),
            }
            for method in definition.auth_methods
        ],
        "source": record.source,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "fields": [
            {
                "key": field.key,
                "label": field.label,
                "env_var": field.env_var,
                "value": "" if field.secret else values.get(field.key, ""),
                "secret": field.secret,
                "required": field.key in auth_method.required_fields,
                "has_value": bool(values.get(field.key, "").strip()),
                "placeholder": field.placeholder,
                "help_text": field.help_text,
                "auth_methods": list(field.auth_methods),
                "input_kind": field.input_kind,
            }
            for field in definition.fields
        ],
    }


def update_provider_settings(
    db: Session,
    record: ProviderSettingRecord,
    *,
    enabled: bool,
    auth_method: str | None,
    values: dict[str, str],
    clear_fields: list[str],
) -> ProviderSettingRecord:
    definition = PROVIDER_DEFINITIONS[record.provider]
    fields = {field.key: field for field in definition.fields}
    unknown = (set(values) | set(clear_fields)) - set(fields)
    if unknown:
        raise ValueError(f"unknown provider setting fields: {', '.join(sorted(unknown))}")
    configuration = dict(record.configuration or {})
    secrets = dict(record.secrets or {})
    if auth_method is not None:
        allowed_auth_methods = {method.key for method in definition.auth_methods}
        if auth_method not in allowed_auth_methods:
            raise ValueError(f"unknown authentication method: {auth_method}")
        configuration[AUTH_METHOD_CONFIG_KEY] = auth_method
    for key, raw_value in values.items():
        target = secrets if fields[key].secret else configuration
        value = str(raw_value).strip()
        if record.provider == "google" and key == "service_account_json" and value:
            service_account = validate_service_account_json(value)
            service_project = str(service_account["project_id"])
            configured_project = str(values.get("project_id") or "").strip()
            if configured_project and configured_project != service_project:
                raise ValueError("Google Cloud project does not match the Service Account project_id")
            configuration["project_id"] = service_project
            value = json.dumps(service_account, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if value:
            target[key] = value
        elif not fields[key].secret:
            target.pop(key, None)
    for key in clear_fields:
        (secrets if fields[key].secret else configuration).pop(key, None)
    record.enabled = enabled
    record.configuration = configuration
    record.secrets = secrets
    record.source = "database"
    record.updated_at = utc_now()
    db.commit()
    db.refresh(record)
    apply_provider_settings_to_environment([record])
    return record
