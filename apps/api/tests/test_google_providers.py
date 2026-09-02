from types import SimpleNamespace
import base64
import json

import pytest

from app.providers_google import GeneratedBinary, GoogleImageProvider, GoogleProviderConfig, GoogleTextProvider, GoogleTtsProvider, GoogleVideoProvider
from app import providers_localization
from app.providers_localization import get_localization_services
from app.format_extraction import FormatSource, GeminiFormatExtractor
from app.providers_openai import OpenAIProviderConfig
from app.providers import ProviderSubmission, model_id_for_alias
from app.experiments import resolve_model
from app.domain import ExperimentRunRequest
from app.providers_generation import GoogleGenerationServices, InputMedia


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


@pytest.mark.parametrize(("logical_alias", "exact_model_id"), [
    ("google.text.3.6-flash", "gemini-3.6-flash"),
    ("google.text.3.5-flash", "gemini-3.5-flash"),
    ("google.text.3.5-flash-lite", "gemini-3.5-flash-lite"),
    ("google.text.3.1-pro-preview", "gemini-3.1-pro-preview"),
    ("google.text.3.1-flash-lite", "gemini-3.1-flash-lite"),
    ("google.text.2.5-flash", "gemini-2.5-flash"),
    ("google.text.2.5-flash-lite", "gemini-2.5-flash-lite"),
])
def test_selectable_google_text_models_resolve_to_current_model_ids(
    logical_alias: str,
    exact_model_id: str,
):
    assert model_id_for_alias(logical_alias) == exact_model_id
    assert model_id_for_alias(logical_alias, gemini_api=True) == exact_model_id


def test_fast_text_alias_tracks_latest_stable_flash_model():
    assert model_id_for_alias("google.text.fast") == "gemini-3.6-flash"


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
    assert client.models.last["model"] == "gemini-3.1-pro-preview"
    assert client.models.last["config"].response_mime_type == "application/json"
    assert client.models.last["config"].seed == 9


def test_google_skill_executor_uses_registered_skill_as_system_prompt():
    class FakeText:
        def __init__(self):
            self.last = None

        def generate_text(self, **kwargs):
            self.last = kwargs
            return "generated prompt", "google_skill_request"

    text = FakeText()
    service = GoogleGenerationServices(text=text, image=object(), video=object(), tts=object())
    payload = ExperimentRunRequest(
        canvas_id="canvas", node_id="skill", node_key="skill.execute", prompt="비 오는 골목",
        model_alias="google.text.quality", parameters={"skill_id": "nottalggak-prompt-machine"}, inputs=[],
    )
    result = service.execute(payload, [])
    assert result.output["title"] == "Generated master prompt"
    assert result.schema_id == "prompt.master.v1"
    assert "# NOTTALGGAK Prompt Machine" in text.last["system_prompt"]
    assert text.last["rendered_prompt"] == "비 오는 골목"


def test_character_generator_uses_connected_image_as_canonical_reference():
    class FakeCharacterImage:
        def __init__(self):
            self.calls = []

        def generate(self, **kwargs):
            self.calls.append(kwargs)
            index = len(self.calls)
            return [GeneratedBinary(f"generated-{index}".encode(), "image/png", "model", f"request-{index}")]

    image = FakeCharacterImage()
    service = GoogleGenerationServices(text=object(), image=image, video=object(), tts=object())
    request = ExperimentRunRequest(
        canvas_id="canvas", node_id="character", node_key="character.generate",
        prompt="A black-haired anime cat-eared athlete", model_alias="google.image.fast",
        parameters={"shot_count": 4}, inputs=[],
    )
    result = service.execute(request, [InputMedia("base-image", "Image", b"canonical-base", "image/png")])
    assert len(result.images) == 4
    assert [image.role for image in result.images] == ["baseline", "closeup", "daily_life", "work_scene"]
    assert all(call["reference_images"][0] == (b"canonical-base", "image/png") for call in image.calls)
    assert all(b"generated-" not in call["reference_images"][0][0] for call in image.calls)


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


def test_gemini_omni_combines_character_images_reference_video_and_prompt():
    class FakeInteractions:
        def __init__(self):
            self.last = None

        def create(self, **kwargs):
            self.last = kwargs
            return SimpleNamespace(
                id="omni_request_1",
                outputs=[SimpleNamespace(type="video", data=base64.b64encode(b"omni-video").decode(), mime_type="video/mp4")],
            )

    client = FakeClient()
    client.interactions = FakeInteractions()
    provider = GoogleVideoProvider(GoogleProviderConfig(api_key="demo"), client=client)
    result = provider.generate_omni(
        prompt="The character waves and turns around",
        reference_images=[(b"front", "image/png"), (b"profile", "image/png")],
        reference_videos=[(b"driving-motion", "video/mp4")],
        resolution="1080p",
    )
    assert result[0].data == b"omni-video"
    assert result[0].provider_request_id == "omni_request_1"
    assert client.interactions.last["model"] == "gemini-omni-1.1-flash"
    assert client.interactions.last["generation_config"]["video_config"]["task"] == "reference_to_video"
    assert client.interactions.last["response_format"] == {"type": "video", "aspect_ratio": "9:16", "resolution": "1080p"}
    prompt = client.interactions.last["input"][-1]["text"]
    assert "<IMAGE_REF_0>" in prompt
    assert "<VIDEO_REF_0>" in prompt
    assert "do not copy its person's identity" in prompt


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


def test_service_account_selects_vertex_ai_even_if_legacy_api_key_exists(monkeypatch):
    captured = {}
    credential = object()
    monkeypatch.setenv("GEMINI_API_KEY", "ignored-legacy-key")
    monkeypatch.setattr("app.providers_google.google_project_from_env", lambda: "service-project")
    monkeypatch.setattr("app.providers_google.google_credentials_from_env", lambda: credential)
    monkeypatch.setattr("app.providers_google.genai.Client", lambda **kwargs: captured.update(kwargs) or FakeClient())
    config = GoogleProviderConfig.from_env()
    provider = GoogleVideoProvider(config)
    assert config.api_key is None
    assert config.project == "service-project"
    assert captured["vertexai"] is True
    assert captured["project"] == "service-project"
    assert captured["credentials"] is credential
    assert provider.exact_model("google.video.fast") == "veo-3.1-fast-generate-001"
    assert resolve_model("video.fast", "video.generate") == ("google.video.fast", "veo-3.1-fast-generate-001")
    provider.submit(prompt="Animate this image", duration_seconds=4)
    config = provider.client.models.last["config"]
    assert config.generate_audio is True
    assert config.enhance_prompt is True


@pytest.mark.parametrize(("model_alias", "vertex_model"), [
    ("google.tts.latest", "gemini-3.1-flash-tts-preview"),
    ("google.tts.fast", "gemini-2.5-flash-tts"),
    ("google.tts.quality", "gemini-2.5-pro-tts"),
])
def test_tts_model_ids_use_vertex_contract(
    model_alias: str,
    vertex_model: str,
):
    client = FakeClient()
    vertex_provider = GoogleTtsProvider(GoogleProviderConfig(project="demo"), client=client)
    assert vertex_provider.exact_model(model_alias) == vertex_model


def test_tts_model_resolution_ignores_legacy_gemini_api_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "ignored-legacy-key")
    assert resolve_model("tts.fast", "tts.generate") == (
        "google.tts.fast",
        "gemini-2.5-flash-tts",
    )
    assert resolve_model("tts.quality", "tts.generate") == (
        "google.tts.quality",
        "gemini-2.5-pro-tts",
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


def test_localization_requires_service_account_without_mock_fallback(monkeypatch):
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.delenv("GOOGLE_SERVICE_ACCOUNT_JSON", raising=False)
    with pytest.raises(RuntimeError, match="Service Account JSON"):
        get_localization_services()


def test_localization_uses_one_service_account_for_speech_and_vertex_generation(monkeypatch):
    captured: dict[str, object] = {}
    credential = object()
    recognizer = object()
    text_provider = object()
    tts_provider = object()

    monkeypatch.setenv("GOOGLE_SPEECH_LOCATION", "us")
    monkeypatch.setattr(providers_localization, "google_project_from_env", lambda: "service-project")
    monkeypatch.setattr(providers_localization, "google_credentials_from_env", lambda: credential)
    monkeypatch.setattr(
        providers_localization.GoogleProviderConfig,
        "from_env",
        classmethod(lambda cls: providers_localization.GoogleProviderConfig(project="service-project", credentials=credential)),
    )
    monkeypatch.setattr(providers_localization, "GoogleChirp3Recognizer", lambda project, location: captured.update(project=project, location=location) or recognizer)
    monkeypatch.setattr(providers_localization, "GoogleTextProvider", lambda config: captured.update(text_config=config) or text_provider)
    monkeypatch.setattr(providers_localization, "GoogleTtsProvider", lambda config: captured.update(tts_config=config) or tts_provider)

    services = get_localization_services()

    assert services.recognizer is recognizer
    assert captured["project"] == "service-project"
    assert captured["location"] == "us"
    assert captured["text_config"].project == "service-project"
    assert captured["text_config"].credentials is credential
    assert captured["tts_config"].project == "service-project"


def test_chirp3_rejects_unsupported_global_location():
    with pytest.raises(RuntimeError, match="not available in global"):
        providers_localization.GoogleChirp3Recognizer("speech-project", "global")


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
    assert result.exact_model_id == "gemini-3.1-pro-preview"
