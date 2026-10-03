import base64
from types import SimpleNamespace

import pytest

from app.project_skills import project_skill_system_prompt
from app.providers_generation import InputMedia
from app.providers_openai import OpenAIGenerationServices, OpenAIProviderConfig


class FakeResponses:
    def __init__(self):
        self.last = None

    def create(self, **kwargs):
        self.last = kwargs
        return SimpleNamespace(id="resp_test", output_text="OpenAI generated text")


class FakeImages:
    def __init__(self):
        self.last = None

    def generate(self, **kwargs):
        self.last = kwargs
        encoded = base64.b64encode(b"\x89PNG\r\n\x1a\n").decode()
        return SimpleNamespace(created=1, data=[SimpleNamespace(b64_json=encoded)])

    def edit(self, **kwargs):
        self.last = kwargs
        encoded = base64.b64encode(b"\x89PNG\r\n\x1a\n-edited").decode()
        return SimpleNamespace(created=2, data=[SimpleNamespace(b64_json=encoded)])


class FakeSpeech:
    def __init__(self):
        self.last = None

    def create(self, **kwargs):
        self.last = kwargs
        return SimpleNamespace(content=b"RIFFtest-wave")


class FakeOpenAIClient:
    def __init__(self):
        self.responses = FakeResponses()
        self.images = FakeImages()
        self.audio = SimpleNamespace(speech=FakeSpeech())


def test_openai_responses_provider_returns_actual_response_id():
    client = FakeOpenAIClient()
    service = OpenAIGenerationServices(OpenAIProviderConfig("test"), client)
    text, request_id = service.generate_text(
        logical_model="openai.chat.latest",
        prompt="Create something",
        instructions="Return only the result",
    )
    assert request_id == "resp_test"
    assert text == "OpenAI generated text"
    assert client.responses.last["model"] == "chat-latest"
    assert client.responses.last["store"] is False


def test_openai_skill_executor_uses_registered_skill_as_instructions():
    client = FakeOpenAIClient()
    service = OpenAIGenerationServices(OpenAIProviderConfig("test"), client)
    text, request_id = service.generate_text(
        logical_model="openai.text.quality",
        prompt="Create something",
        instructions=project_skill_system_prompt("nottalggak-prompt-machine"),
    )
    assert text == "OpenAI generated text"
    assert request_id == "resp_test"
    assert "# NOTTALGGAK Prompt Machine" in client.responses.last["instructions"]
    assert client.responses.last["input"] == "Create something"


def test_openai_image_provider_maps_vertical_size_and_decodes_png():
    client = FakeOpenAIClient()
    service = OpenAIGenerationServices(OpenAIProviderConfig("test"), client)
    images, _ = service.generate_images(
        logical_model="openai.image.default", prompt="Create something", count=1,
        aspect_ratio="9:16", quality="medium", reference_images=[],
    )
    assert images[0].startswith(b"\x89PNG")
    assert client.images.last["model"] == "gpt-image-2"
    assert client.images.last["size"] == "1152x2048"
    assert "response_format" not in client.images.last


def test_openai_image_provider_edits_connected_image():
    client = FakeOpenAIClient()
    service = OpenAIGenerationServices(OpenAIProviderConfig("test"), client)
    images, _ = service.generate_images(
        logical_model="openai.image.default", prompt="Create something", count=1,
        aspect_ratio="9:16", quality="medium",
        reference_images=[InputMedia("art_source", "Image", b"source-png", "image/png")],
    )
    assert images[0].endswith(b"-edited")
    assert client.images.last["image"][0][1] == b"source-png"
    assert "response_format" not in client.images.last
    assert "input_fidelity" not in client.images.last


def test_precision_image_alias_is_pinned_and_preserves_aspect_ratio():
    from app.providers import model_id_for_alias
    client = FakeOpenAIClient()
    service = OpenAIGenerationServices(OpenAIProviderConfig("test"), client)
    service.generate_images(
        logical_model="openai.image.precise", prompt="Correct only lighting and body reference drift", count=1,
        aspect_ratio="9:16", quality="high",
        reference_images=[InputMedia("candidate", "Image", b"candidate-png", "image/png")],
    )
    assert client.images.last["model"] == "gpt-image-2.5-sunburst-2026-09-08"
    assert client.images.last["size"] == "1152x2048"
    assert client.images.last["image"][0][1] == b"candidate-png"
    assert "input_fidelity" not in client.images.last
    assert model_id_for_alias("openai.image.default") == "gpt-image-2"


def test_precision_image_uses_explicit_documented_token_rates():
    from datetime import date
    from decimal import Decimal
    from app.cost_pricing import calculate
    amount, snapshot, unresolved = calculate(
        'openai', 'gpt-image-2.5-sunburst-2026-09-08', 'images.edit',
        {'input_tokens_details': {'text_tokens': 100, 'image_tokens': 200}, 'output_tokens': 300},
        {}, today=date(2026, 10, 2),
    )
    assert amount == Decimal('0.0111')
    assert unresolved is None
    assert 'gpt-image-2.5-sunburst' in str(snapshot)


@pytest.mark.parametrize(("model_alias", "exact_model", "uses_instructions"), [
    ("openai.tts.default", "gpt-4o-mini-tts", True),
    ("openai.tts.fast", "tts-1", False),
    ("openai.tts.quality", "tts-1-hd", False),
])
def test_openai_speech_provider_requests_supported_model(
    model_alias: str,
    exact_model: str,
    uses_instructions: bool,
):
    client = FakeOpenAIClient()
    service = OpenAIGenerationServices(OpenAIProviderConfig("test"), client)
    audio, _, _ = service.generate_speech(
        logical_model=model_alias,
        text="Create something",
        voice_name="coral",
        style_prompt="Speak naturally",
    )
    assert audio == b"RIFFtest-wave"
    assert client.audio.speech.last["model"] == exact_model
    assert client.audio.speech.last["response_format"] == "wav"
    assert ("instructions" in client.audio.speech.last) is uses_instructions
