import os

from fastapi.testclient import TestClient

from app.database import ProviderSettingRecord, SessionLocal
from app.provider_settings import ensure_provider_settings, provider_settings_payload


def test_provider_settings_are_created_and_secrets_are_write_only(client: TestClient, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    initial = client.get("/settings/providers")
    assert initial.status_code == 200
    assert [record["label"] for record in initial.json()] == [
        "OpenAI",
        "Google AI",
        "Claude",
        "ElevenLabs",
        "Seedance",
        "Kling",
        "MiniMax",
        "fal.ai",
    ]
    initial_openai = initial.json()[0]
    assert initial_openai["auth_method"] == "api_key"
    assert {method["key"] for method in initial_openai["auth_methods"]} == {"api_key", "chatgpt_oauth"}
    google = next(record for record in initial.json() if record["provider"] == "google")
    assert {method["label"] for method in google["auth_methods"]} == {"Gemini API", "Vertex AI"}
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
    assert oauth.json()["configured"] is False

    unknown = client.put("/settings/providers/claude", json={
        "enabled": True,
        "auth_method": "password",
        "values": {},
    })
    assert unknown.status_code == 422
    assert "unknown authentication method" in unknown.json()["detail"]


def test_google_api_key_mode_can_apply_cloud_speech_adc_settings(client: TestClient, monkeypatch):
    for key in ("GEMINI_API_KEY", "GOOGLE_CLOUD_PROJECT", "GOOGLE_APPLICATION_CREDENTIALS"):
        monkeypatch.delenv(key, raising=False)

    saved = client.put("/settings/providers/google", json={
        "enabled": True,
        "auth_method": "api_key",
        "values": {
            "api_key": "gemini-test-key",
            "project_id": "speech-project",
            "credentials_path": "/run/secrets/google-adc.json",
            "speech_location": "us",
        },
    })

    assert saved.status_code == 200
    payload = saved.json()
    visible_with_api_key = {
        field["key"] for field in payload["fields"]
        if not field["auth_methods"] or "api_key" in field["auth_methods"]
    }
    assert {"api_key", "project_id", "credentials_path", "speech_location"} <= visible_with_api_key
    assert payload["auth_method"] == "api_key"
    assert payload["configured"] is True
    assert os.environ["GEMINI_API_KEY"] == "gemini-test-key"
    assert os.environ["GOOGLE_CLOUD_PROJECT"] == "speech-project"
    assert os.environ["GOOGLE_APPLICATION_CREDENTIALS"] == "/run/secrets/google-adc.json"


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


def test_environment_values_seed_a_missing_provider_record(client: TestClient, monkeypatch):
    del client
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "project-from-env")
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
