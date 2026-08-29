import base64
from types import SimpleNamespace

import pytest

from app.domain import ExperimentRunRequest
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


def payload(node_key: str, model_alias: str) -> ExperimentRunRequest:
    return ExperimentRunRequest(
        canvas_id="canvas", node_id="node", node_key=node_key, prompt="Create something",
        model_alias=model_alias, parameters={"aspect_ratio": "9:16"}, inputs=[],
    )


def test_openai_responses_provider_returns_actual_response_id():
    client = FakeOpenAIClient()
    service = OpenAIGenerationServices(OpenAIProviderConfig("test"), client)
    result = service.execute(payload("llm.assistant", "openai.chat.latest"), [])
    assert result.provider_request_id == "resp_test"
    assert result.content == b"OpenAI generated text"
    assert client.responses.last["model"] == "chat-latest"
    assert client.responses.last["store"] is False


def test_openai_skill_executor_uses_registered_skill_as_instructions():
    client = FakeOpenAIClient()
    service = OpenAIGenerationServices(OpenAIProviderConfig("test"), client)
    request = payload("skill.execute", "openai.text.quality").model_copy(update={
        "parameters": {"skill_id": "nottalggak-prompt-machine"},
    })
    result = service.execute(request, [])
    assert result.output["title"] == "Generated master prompt"
    assert result.schema_id == "prompt.master.v1"
    assert "# NOTTALGGAK Prompt Machine" in client.responses.last["instructions"]
    assert client.responses.last["input"] == "Create something"


def test_openai_image_provider_maps_vertical_size_and_decodes_png():
    client = FakeOpenAIClient()
    service = OpenAIGenerationServices(OpenAIProviderConfig("test"), client)
    result = service.execute(payload("image.generate", "openai.image.default"), [])
    assert result.content.startswith(b"\x89PNG")
    assert client.images.last["model"] == "gpt-image-2"
    assert client.images.last["size"] == "1024x1536"
    assert "response_format" not in client.images.last


def test_openai_image_provider_edits_connected_image():
    client = FakeOpenAIClient()
    service = OpenAIGenerationServices(OpenAIProviderConfig("test"), client)
    result = service.execute(
        payload("image.generate", "openai.image.default"),
        [InputMedia("art_source", "Image", b"source-png", "image/png")],
    )
    assert result.content.endswith(b"-edited")
    assert client.images.last["image"][0][1] == b"source-png"
    assert "response_format" not in client.images.last
    assert "input_fidelity" not in client.images.last


def test_openai_image_edit_operation_has_distinct_artifact_contract():
    client = FakeOpenAIClient()
    service = OpenAIGenerationServices(OpenAIProviderConfig("test"), client)
    result = service.execute(
        payload("image.edit", "openai.image.default"),
        [InputMedia("art_source", "Image", b"source-png", "image/png")],
    )
    assert result.output["title"] == "AI edited image"
    assert result.schema_id == "openai.image.edit.v1"
    assert result.filename == "edited.png"
    assert result.input_artifact_ids == ["art_source"]


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
    result = service.execute(payload("tts.generate", model_alias), [])
    assert result.content == b"RIFFtest-wave"
    assert client.audio.speech.last["model"] == exact_model
    assert client.audio.speech.last["response_format"] == "wav"
    assert ("instructions" in client.audio.speech.last) is uses_instructions
