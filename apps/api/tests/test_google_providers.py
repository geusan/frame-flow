from types import SimpleNamespace
import json

import pytest

from app.providers_google import GoogleProviderConfig, GoogleTextProvider, GoogleVideoProvider
from app.providers_localization import get_localization_services
from app.format_extraction import FormatSource, GeminiFormatExtractor
from app.providers_openai import OpenAIProviderConfig


class FakeModels:
    def __init__(self):
        self.last = None

    def generate_content(self, **kwargs):
        self.last = kwargs
        return SimpleNamespace(text='{"result":"ok"}')

    def generate_videos(self, **kwargs):
        self.last = kwargs
        return SimpleNamespace(name="projects/demo/locations/us/operations/veo-123")


class FakeClient:
    def __init__(self):
        self.models = FakeModels()


def test_structured_text_uses_schema_and_exact_registered_model():
    client = FakeClient()
    provider = GoogleTextProvider(GoogleProviderConfig("demo"), client=client)
    result, request_id = provider.generate_structured(
        logical_model="google.text.quality",
        system_prompt="Return only data",
        rendered_prompt="Analyze this",
        output_json_schema={"type": "object", "properties": {"result": {"type": "string"}}},
        seed=9,
    )
    assert result == {"result": "ok"}
    assert request_id.startswith("google_")
    assert client.models.last["model"] == "gemini-2.5-pro"
    assert client.models.last["config"].response_mime_type == "application/json"
    assert client.models.last["config"].seed == 9


def test_veo_submission_snapshots_operation_and_request_hash():
    client = FakeClient()
    provider = GoogleVideoProvider(GoogleProviderConfig("demo", "us-central1"), client=client)
    submission = provider.submit(prompt="A cinematic stone road", duration_seconds=6, candidate_count=2, seed=42)
    assert submission.provider_operation_id.endswith("veo-123")
    assert len(submission.request_hash) == 64
    assert client.models.last["model"] == "veo-3.1-fast-generate-001"
    assert client.models.last["config"].aspect_ratio == "9:16"
    assert client.models.last["config"].number_of_videos == 2


def test_localization_requires_live_google_project_without_mock_fallback(monkeypatch):
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    with pytest.raises(RuntimeError, match="GOOGLE_CLOUD_PROJECT"):
        get_localization_services()


def test_openai_provider_requires_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        OpenAIProviderConfig.from_env()


def test_gemini_format_extractor_parses_real_structured_contract():
    payload = {
        "duration": {"target_ms": 30_000},
        "narrative": {"beats": [
            {"role": "hook", "start_ratio": 0, "end_ratio": 0.1, "pattern": "question"},
            {"role": "context", "start_ratio": 0.1, "end_ratio": 0.35, "pattern": "setup"},
            {"role": "escalation", "start_ratio": 0.35, "end_ratio": 0.8, "pattern": "evidence"},
            {"role": "payoff", "start_ratio": 0.8, "end_ratio": 1, "pattern": "answer"},
        ]},
        "editing": {"median_shot_duration_ms": 1800, "cuts_per_10_seconds": 5.2, "transition_policy": "hard_cut"},
        "captions": {"position": "lower", "max_lines": 2, "max_chars_per_line": 14, "words_per_chunk": 4},
        "voice": {"tone": "clear", "pace_syllables_per_second": 4.5},
        "music": {"bpm_range": [100, 115], "ducking_under_voice_db": -9},
        "visual": {"motion_intensity": 0.7, "preferred_shot_types": ["detail", "medium"]},
        "constraints": {},
        "extensions": {},
    }
    client = FakeClient()
    client.models.generate_content = lambda **kwargs: SimpleNamespace(text=json.dumps(payload))
    provider = GoogleTextProvider(GoogleProviderConfig("demo"), client=client)
    result = GeminiFormatExtractor(provider).extract([FormatSource("ref_1", "Title", "Creator", 30_000, b"video")])
    assert result.profile.core.duration["target_ms"] == 30_000
    assert result.profile.core.editing["cuts_per_10_seconds"] == 5.2
    assert result.exact_model_id == "gemini-2.5-pro"
