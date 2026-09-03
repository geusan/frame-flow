import json
import os

from fastapi.testclient import TestClient

from app.database import ProviderSettingRecord, SessionLocal
from app import provider_settings as provider_settings_module
from app.google_service_account import GOOGLE_SERVICE_ACCOUNT_ENV
from app.local_subscription_agents import LocalAuthStatus
from app.provider_settings import ensure_provider_settings, provider_settings_payload
from app.providers_localization import GoogleChirp3Recognizer


def _service_account(project_id: str = "service-project") -> dict[str, str]:
    return {
        "type": "service_account",
        "project_id": project_id,
        "private_key_id": "key-id",
        "private_key": "-----BEGIN PRIVATE KEY-----\nTEST\n-----END PRIVATE KEY-----\n",
        "client_email": f"frameflow@{project_id}.iam.gserviceaccount.com",
        "client_id": "123456",
        "token_uri": "https://oauth2.googleapis.com/token",
    }


def test_provider_settings_are_created_and_secrets_are_write_only(client: TestClient, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    initial = client.get("/settings/providers")
    assert initial.status_code == 200
    assert [record["label"] for record in initial.json()] == [
        "OpenAI",
        "xAI",
        "Google AI",
        "Claude",
        "ElevenLabs",
        "Seedance",
        "Kling",
        "MiniMax",
        "fal.ai",
        "Cloudflare R2",
    ]
    initial_openai = initial.json()[0]
    assert initial_openai["auth_method"] == "api_key"
    assert {method["key"] for method in initial_openai["auth_methods"]} == {"api_key", "chatgpt_oauth"}
    google = next(record for record in initial.json() if record["provider"] == "google")
    assert google["auth_method"] == "service_account"
    assert [method["label"] for method in google["auth_methods"]] == ["Service Account"]
    assert {field["key"] for field in google["fields"]} == {
        "service_account_json", "location", "speech_location", "video_output_gcs_uri",
    }
    assert client.put("/settings/providers/veo3", json={"enabled": True, "values": {}}).status_code == 404

    saved = client.put("/settings/providers/openai", json={
        "enabled": True,
        "values": {
            "api_key": "sk-database-test",
            "base_url": "https://example.openai.local/v1",
            "organization_id": "org_test",
            "project_id": "proj_test",
        },
    })
    assert saved.status_code == 200
    payload = saved.json()
    assert payload["configured"] is True
    assert payload["source"] == "database"
    api_key = next(field for field in payload["fields"] if field["key"] == "api_key")
    assert api_key["value"] == ""
    assert api_key["has_value"] is True
    assert os.environ["OPENAI_API_KEY"] == "sk-database-test"

    listed = client.get("/settings/providers").json()
    listed_openai = next(record for record in listed if record["provider"] == "openai")
    assert next(field for field in listed_openai["fields"] if field["key"] == "api_key")["value"] == ""
    assert client.get("/health").json()["openai_configured"] is True
    assert all(model["configured"] for model in client.get("/models").json() if model["provider"] == "OpenAI")

    disabled = client.put("/settings/providers/openai", json={
        "enabled": False,
        "values": {},
    })
    assert disabled.status_code == 200
    assert disabled.json()["configured"] is False
    assert "OPENAI_API_KEY" not in os.environ

    enabled_again = client.put("/settings/providers/openai", json={
        "enabled": True,
        "values": {},
    })
    assert enabled_again.status_code == 200
    assert enabled_again.json()["configured"] is True
    assert os.environ["OPENAI_API_KEY"] == "sk-database-test"

    cleared = client.put("/settings/providers/openai", json={
        "enabled": True,
        "values": {},
        "clear_fields": ["api_key"],
    })
    assert cleared.status_code == 200
    assert cleared.json()["configured"] is False
    assert "OPENAI_API_KEY" not in os.environ


def test_provider_auth_method_controls_required_secret_and_environment(client: TestClient, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.setattr(
        provider_settings_module,
        "check_local_provider_auth",
        lambda provider, method, values: (
            LocalAuthStatus(True, "ready", f"{provider} local subscription ready")
            if (provider, method) in {("claude", "setup_token"), ("openai", "chatgpt_oauth")}
            else None
        ),
    )

    saved = client.put("/settings/providers/claude", json={
        "enabled": True,
        "auth_method": "setup_token",
        "values": {"setup_token": "claude-setup-token-test"},
    })

    assert saved.status_code == 200
    payload = saved.json()
    assert payload["auth_method"] == "setup_token"
    assert payload["configured"] is True
    assert os.environ["CLAUDE_CODE_OAUTH_TOKEN"] == "claude-setup-token-test"
    assert "ANTHROPIC_API_KEY" not in os.environ
    setup_token = next(field for field in payload["fields"] if field["key"] == "setup_token")
    assert setup_token["required"] is True
    assert setup_token["value"] == ""
    assert setup_token["has_value"] is True

    elevenlabs = client.put("/settings/providers/elevenlabs", json={
        "enabled": True,
        "auth_method": "api_key",
        "values": {"api_key": "elevenlabs-test-key"},
    })
    assert elevenlabs.status_code == 200
    assert elevenlabs.json()["configured"] is True
    assert os.environ["ELEVENLABS_API_KEY"] == "elevenlabs-test-key"

    oauth = client.put("/settings/providers/openai", json={
        "enabled": True,
        "auth_method": "chatgpt_oauth",
        "values": {},
    })
    assert oauth.status_code == 200
    assert oauth.json()["auth_method"] == "chatgpt_oauth"
    assert oauth.json()["configured"] is True
    assert oauth.json()["connection"]["state"] == "ready"

    unknown = client.put("/settings/providers/claude", json={
        "enabled": True,
        "auth_method": "password",
        "values": {},
    })
    assert unknown.status_code == 422
    assert "unknown authentication method" in unknown.json()["detail"]


def test_google_rejects_legacy_api_key_and_adc_registration(client: TestClient):
    rejected_method = client.put("/settings/providers/google", json={
        "enabled": True,
        "auth_method": "api_key",
        "values": {},
    })
    assert rejected_method.status_code == 422
    assert "unknown authentication method" in rejected_method.json()["detail"]

    rejected_fields = client.put("/settings/providers/google", json={
        "enabled": True,
        "auth_method": "service_account",
        "values": {"api_key": "gemini-test-key", "credentials_path": "/run/secrets/google-adc.json"},
    })
    assert rejected_fields.status_code == 422
    assert "api_key" in rejected_fields.json()["detail"]
    assert "credentials_path" in rejected_fields.json()["detail"]


def test_google_service_account_json_is_validated_write_only_and_applied(client: TestClient, monkeypatch):
    for key in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_APPLICATION_CREDENTIALS", GOOGLE_SERVICE_ACCOUNT_ENV):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "legacy-gemini-key")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "/run/secrets/legacy-adc.json")
    service_account = _service_account()
    monkeypatch.setattr(provider_settings_module, "validate_service_account_json", lambda raw: json.loads(raw))

    saved = client.put("/settings/providers/google", json={
        "enabled": True,
        "auth_method": "service_account",
        "values": {
            "service_account_json": json.dumps(service_account),
            "speech_location": "us",
        },
    })

    assert saved.status_code == 200
    payload = saved.json()
    secret = next(field for field in payload["fields"] if field["key"] == "service_account_json")
    assert payload["auth_method"] == "service_account"
    assert payload["configured"] is True
    assert secret["value"] == ""
    assert secret["has_value"] is True
    assert secret["input_kind"] == "service_account_json"
    assert json.loads(os.environ[GOOGLE_SERVICE_ACCOUNT_ENV])["client_email"] == service_account["client_email"]
    assert "GEMINI_API_KEY" not in os.environ
    assert "GOOGLE_APPLICATION_CREDENTIALS" not in os.environ
    with SessionLocal() as db:
        google = db.get(ProviderSettingRecord, "provider_google")
        assert google.configuration["project_id"] == "service-project"
    google_models = [model for model in client.get("/models").json() if model["provider"] == "Google"]
    assert "google.video.omni" not in {model["logical_alias"] for model in google_models}
    assert next(model for model in google_models if model["logical_alias"] == "google.tts.fast")["exact_model_id"] == "gemini-2.5-flash-tts"

    cleared = client.put("/settings/providers/google", json={
        "enabled": True,
        "auth_method": "service_account",
        "values": {},
        "clear_fields": ["service_account_json"],
    })
    assert cleared.status_code == 200
    assert next(field for field in cleared.json()["fields"] if field["key"] == "service_account_json")["has_value"] is False
    assert GOOGLE_SERVICE_ACCOUNT_ENV not in os.environ


def test_existing_google_record_migrates_to_service_account_only(client: TestClient):
    service_account = _service_account("migrated-project")
    with SessionLocal() as db:
        record = db.get(ProviderSettingRecord, "provider_google")
        record.enabled = True
        record.source = "database"
        record.configuration = {
            "_auth_method": "api_key",
            "project_id": "legacy-project",
            "credentials_path": "/run/secrets/google-adc.json",
            "location": "us-central1",
        }
        record.secrets = {
            "api_key": "legacy-api-key",
            "service_account_json": json.dumps(service_account),
        }
        db.commit()
        migrated = next(item for item in ensure_provider_settings(db) if item.provider == "google")

    assert migrated.configuration["_auth_method"] == "service_account"
    assert migrated.configuration["project_id"] == "migrated-project"
    assert "credentials_path" not in migrated.configuration
    assert "api_key" not in migrated.secrets
    assert "service_account_json" in migrated.secrets


def test_chirp3_uses_registered_service_account_credentials(monkeypatch):
    from google.cloud import speech_v2

    credential = object()
    captured = {}
    monkeypatch.setattr("app.providers_localization.google_credentials_from_env", lambda: credential)
    monkeypatch.setattr(speech_v2, "SpeechClient", lambda **kwargs: captured.update(kwargs) or object())

    GoogleChirp3Recognizer("service-project", "us")

    assert captured["credentials"] is credential
    assert captured["client_options"].api_endpoint == "us-speech.googleapis.com"


def test_fal_provider_uses_server_side_api_key(client: TestClient, monkeypatch):
    monkeypatch.delenv("FAL_KEY", raising=False)

    saved = client.put("/settings/providers/fal", json={
        "enabled": True,
        "auth_method": "api_key",
        "values": {"api_key": "fal-test-key"},
    })

    assert saved.status_code == 200
    payload = saved.json()
    assert payload["label"] == "fal.ai"
    assert payload["configured"] is True
    assert os.environ["FAL_KEY"] == "fal-test-key"
    api_key = next(field for field in payload["fields"] if field["key"] == "api_key")
    assert api_key["env_var"] == "FAL_KEY"
    assert api_key["value"] == ""
    assert api_key["has_value"] is True


def test_r2_provider_applies_bucket_scoped_s3_credentials(client: TestClient, monkeypatch):
    for key in ("R2_ACCOUNT_ID", "R2_TRAINING_BUCKET", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY"):
        monkeypatch.delenv(key, raising=False)

    saved = client.put("/settings/providers/r2", json={
        "enabled": True,
        "auth_method": "s3_api",
        "values": {
            "account_id": "account-test",
            "bucket": "frameflow-lora-training",
            "access_key_id": "r2-access-test",
            "secret_access_key": "r2-secret-test",
            "signed_url_ttl_seconds": "3600",
        },
    })

    assert saved.status_code == 200
    payload = saved.json()
    assert payload["label"] == "Cloudflare R2"
    assert payload["configured"] is True
    assert os.environ["R2_ACCOUNT_ID"] == "account-test"
    assert os.environ["R2_TRAINING_BUCKET"] == "frameflow-lora-training"
    assert os.environ["R2_ACCESS_KEY_ID"] == "r2-access-test"
    assert os.environ["R2_SECRET_ACCESS_KEY"] == "r2-secret-test"
    secret = next(field for field in payload["fields"] if field["key"] == "secret_access_key")
    assert secret["value"] == ""
    assert secret["has_value"] is True


def test_environment_values_seed_a_missing_provider_record(client: TestClient, monkeypatch):
    del client
    monkeypatch.setenv(GOOGLE_SERVICE_ACCOUNT_ENV, json.dumps(_service_account("project-from-env")))
    monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "asia-northeast3")

    with SessionLocal() as db:
        record = db.get(ProviderSettingRecord, "provider_google")
        assert record is not None
        db.delete(record)
        db.commit()
        records = ensure_provider_settings(db)
        google = next(item for item in records if item.provider == "google")
        payload = provider_settings_payload(google)

    assert google.configuration["project_id"] == "project-from-env"
    assert google.configuration["location"] == "asia-northeast3"
    assert payload["source"] == "environment"
    assert payload["configured"] is True


def test_provider_settings_reject_unknown_fields(client: TestClient):
    response = client.put("/settings/providers/google", json={
        "enabled": True,
        "values": {"not_a_setting": "value"},
    })
    assert response.status_code == 422
    assert "unknown provider setting fields" in response.json()["detail"]
