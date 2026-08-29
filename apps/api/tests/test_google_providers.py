from types import SimpleNamespace
import json

import pytest

from app.providers_google import GoogleImageProvider, GoogleProviderConfig, GoogleTextProvider, GoogleTtsProvider, GoogleVideoProvider
from app.providers_localization import get_localization_services
from app.format_extraction import FormatSource, GeminiFormatExtractor
from app.providers_openai import OpenAIProviderConfig
from app.providers import ProviderSubmission
from app.experiments import resolve_model


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
    assert client.models.last["config"].generate_audio is True
    assert client.models.last["config"].enhance_prompt is True


def test_image_generation_sends_reference_image_with_prompt():
    client = FakeClient()
    client.models.generate_content = lambda **kwargs: (
        setattr(client.models, "last", kwargs)
        or SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(parts=[SimpleNamespace(inline_data=SimpleNamespace(data=b"result", mime_type="image/png"))]))])
    )
    result = GoogleImageProvider(GoogleProviderConfig("demo"), client=client).generate(
        prompt="Change the background to blue",
        reference_images=[(b"source-image", "image/png")],
    )
    assert result[0].data == b"result"
    assert client.models.last["contents"][0] == "Change the background to blue"
    assert client.models.last["contents"][1].inline_data.data == b"source-image"


def test_gemini_api_key_selects_developer_api_and_preview_veo_model(monkeypatch):
    captured = {}
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-test-key")
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.setattr("app.providers_google.genai.Client", lambda **kwargs: captured.update(kwargs) or FakeClient())
    config = GoogleProviderConfig.from_env()
    provider = GoogleVideoProvider(config)
    assert config.api_key == "gemini-test-key"
    assert config.project is None
    assert captured == {"api_key": "gemini-test-key"}
    assert provider.exact_model("google.video.fast") == "veo-3.1-fast-generate-preview"
    assert resolve_model("video.fast", "video.generate") == ("google.video.fast", "veo-3.1-fast-generate-preview")
    provider.submit(prompt="Animate this image", duration_seconds=4)
    config = provider.client.models.last["config"]
    assert config.generate_audio is None
    assert config.enhance_prompt is None
    assert config.output_gcs_uri is None
    provider.submit(prompt="Animate this image", duration_seconds=6, resolution="1080p", image_data=b"source", image_mime_type="image/png")
    config = provider.client.models.last["config"]
    assert config.duration_seconds == 8
    assert config.resolution == "1080p"
    provider.submit(
        prompt="Use both people as visual references",
        duration_seconds=6,
        resolution="720p",
        reference_images=[(b"image-one", "image/png"), (b"image-two", "image/jpeg")],
    )
    config = provider.client.models.last["config"]
    assert config.duration_seconds == 8
    assert len(config.reference_images) == 2
    assert config.reference_images[0].reference_type.value == "ASSET"
    assert provider.client.models.last["source"].image is None


@pytest.mark.parametrize(("model_alias", "vertex_model", "gemini_api_model"), [
    ("google.tts.latest", "gemini-3.1-flash-tts-preview", "gemini-3.1-flash-tts-preview"),
    ("google.tts.fast", "gemini-2.5-flash-tts", "gemini-2.5-flash-preview-tts"),
    ("google.tts.quality", "gemini-2.5-pro-tts", "gemini-2.5-pro-preview-tts"),
])
def test_tts_model_ids_follow_google_auth_mode(
    model_alias: str,
    vertex_model: str,
    gemini_api_model: str,
):
    client = FakeClient()
    vertex_provider = GoogleTtsProvider(GoogleProviderConfig(project="demo"), client=client)
    gemini_api_provider = GoogleTtsProvider(GoogleProviderConfig(api_key="test-key"), client=client)
    assert vertex_provider.exact_model(model_alias) == vertex_model
    assert gemini_api_provider.exact_model(model_alias) == gemini_api_model


def test_tts_model_resolution_prefers_gemini_api_key_when_both_auth_inputs_exist(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-test-key")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "vertex-project")
    assert resolve_model("tts.fast", "tts.generate") == (
        "google.tts.fast",
        "gemini-2.5-flash-preview-tts",
    )
    assert resolve_model("tts.quality", "tts.generate") == (
        "google.tts.quality",
        "gemini-2.5-pro-preview-tts",
    )


def test_latest_vertex_tts_uses_beta_api(monkeypatch):
    clients = []

    class FakeAudioModels:
        def __init__(self):
            self.last = None

        def generate_content(self, **kwargs):
            self.last = kwargs
            inline_data = SimpleNamespace(data=b"pcm", mime_type="audio/pcm;rate=24000")
            part = SimpleNamespace(inline_data=inline_data)
            return SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(parts=[part]))])

    class FakeAudioClient:
        def __init__(self, options):
            self.options = options
            self.models = FakeAudioModels()

    def create_client(**kwargs):
        client = FakeAudioClient(kwargs)
        clients.append(client)
        return client

    monkeypatch.setattr("app.providers_google.genai.Client", create_client)
    provider = GoogleTtsProvider(GoogleProviderConfig(project="demo", location="us-central1", api_version="v1"))
    generated = provider.synthesize(
        text="안녕하세요",
        style_prompt="Speak clearly.",
        voice_name="Kore",
        logical_model="google.tts.latest",
    )
    assert generated.data == b"pcm"
    assert len(clients) == 2
    assert clients[0].options["http_options"].api_version == "v1"
    assert clients[0].options["location"] == "us-central1"
    assert clients[1].options["http_options"].api_version == "v1beta1"
    assert clients[1].options["location"] == "global"
    assert clients[1].models.last["model"] == "gemini-3.1-flash-tts-preview"


def test_gemini_api_video_download_uses_files_api():
    class FakeFiles:
        def __init__(self):
            self.file = None

        def download(self, *, file):
            self.file = file
            return b"browser-video"

    video = SimpleNamespace(video_bytes=None, uri="https://generativelanguage.googleapis.com/download/video", mime_type="video/mp4")
    operation = SimpleNamespace(done=True, error=None, response=SimpleNamespace(generated_videos=[SimpleNamespace(video=video)]), result=None)
    client = FakeClient()
    client.operations = SimpleNamespace(get=lambda _: operation)
    client.files = FakeFiles()
    provider = GoogleVideoProvider(GoogleProviderConfig(api_key="gemini-test-key"), client=client)
    results = provider.wait_for_generated(
        ProviderSubmission("google_request", "operations/video-1", "request-hash"),
        poll_interval_seconds=0,
    )
    assert results[0].data == b"browser-video"
    assert client.files.file is video


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
