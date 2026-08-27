import json
from types import SimpleNamespace

import pytest

from app.providers_openai import OpenAIGenerationServices, OpenAIProviderConfig
from app.scene_search import (
    OpenAISceneRanker,
    SampledFrame,
    SceneSearchError,
    resolve_scene_search_model,
)


class FakeResponses:
    def __init__(self):
        self.last = None

    def create(self, **kwargs):
        self.last = kwargs
        return SimpleNamespace(
            id="resp_scene_test",
            output_text=json.dumps({
                "rankings": [
                    {"index": 1, "score": 0.93, "reason": "Best visible match"},
                    {"index": 0, "score": 0.62, "reason": "Partial match"},
                ],
            }),
        )


def test_openai_scene_ranker_sends_images_and_structured_output():
    responses = FakeResponses()
    client = SimpleNamespace(responses=responses)
    service = OpenAIGenerationServices(OpenAIProviderConfig("test"), client)
    ranker = OpenAISceneRanker(service)
    frames = [
        SampledFrame(0, 0, b"first"),
        SampledFrame(1, 500, b"second"),
    ]

    result = ranker.rank("person looking at camera", frames, 2, "openai.chat.latest")

    assert result.provider == "openai"
    assert result.model_alias == "openai.chat.latest"
    assert result.exact_model_id == "chat-latest"
    assert result.provider_request_id == "resp_scene_test"
    assert [scene.frame.index for scene in result.scenes] == [1, 0]
    assert responses.last["model"] == "chat-latest"
    assert responses.last["store"] is False
    content = responses.last["input"][0]["content"]
    assert sum(item["type"] == "input_image" for item in content) == 2
    assert content[2]["image_url"].startswith("data:image/jpeg;base64,")
    assert responses.last["text"]["format"]["type"] == "json_schema"


def test_scene_search_model_must_match_selected_provider():
    assert resolve_scene_search_model("google", None) == (
        "google.text.fast",
        "gemini-2.5-flash",
    )
    with pytest.raises(SceneSearchError, match="not available for google"):
        resolve_scene_search_model("google", "openai.chat.latest")
