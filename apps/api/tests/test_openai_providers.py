import base64
from types import SimpleNamespace

from app.domain import ExperimentRunRequest
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


def test_openai_image_provider_maps_vertical_size_and_decodes_png():
    client = FakeOpenAIClient()
    service = OpenAIGenerationServices(OpenAIProviderConfig("test"), client)
    result = service.execute(payload("image.generate", "openai.image.default"), [])
    assert result.content.startswith(b"\x89PNG")
    assert client.images.last["model"] == "gpt-image-2"
    assert client.images.last["size"] == "1024x1536"


def test_openai_speech_provider_requests_wav():
    client = FakeOpenAIClient()
    service = OpenAIGenerationServices(OpenAIProviderConfig("test"), client)
    result = service.execute(payload("tts.generate", "openai.tts.default"), [])
    assert result.content == b"RIFFtest-wave"
    assert client.audio.speech.last["model"] == "gpt-4o-mini-tts"
    assert client.audio.speech.last["response_format"] == "wav"
