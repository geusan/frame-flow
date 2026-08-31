from __future__ import annotations

from types import SimpleNamespace

import pytest

from app import experiments as experiments_module
from app import providers_xai as providers_xai_module
from app.providers_xai import XAI_API_BASE_URL, XAIProviderConfig, XAITextResult, XAITextServices


class FakeResponses:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            id="xai_response_1",
            output_text="Grok final response",
            usage=SimpleNamespace(input_tokens=100, output_tokens=50),
        )


class FakeClient:
    def __init__(self) -> None:
        self.responses = FakeResponses()
        self.timeout = None

    def with_options(self, *, timeout):
        self.timeout = timeout
        return self


def test_xai_provider_requires_api_key(monkeypatch):
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="XAI_API_KEY"):
        XAIProviderConfig.from_env()


def test_xai_provider_uses_the_fixed_official_api_base(monkeypatch):
    captured = {}
    fake_client = FakeClient()

    def fake_openai(**kwargs):
        captured.update(kwargs)
        return fake_client

    monkeypatch.setattr(providers_xai_module, "OpenAI", fake_openai)
    XAITextServices(XAIProviderConfig("xai-test-key"))

    assert captured == {"api_key": "xai-test-key", "base_url": XAI_API_BASE_URL}


def test_xai_text_service_uses_responses_contract_and_tracks_cost():
    client = FakeClient()
    service = XAITextServices(XAIProviderConfig("xai-test-key"), client=client)

    result = service.generate(
        model_alias="xai.text.quality",
        prompt="Explain the result",
        instructions="Return only the answer.",
        reasoning_effort="high",
        timeout_seconds=180,
        prompt_cache_key="request_hash_1",
    )

    assert client.timeout == 180
    assert client.responses.calls == [{
        "model": "grok-4.6",
        "instructions": "Return only the answer.",
        "input": "Explain the result",
        "reasoning": {"effort": "high"},
        "prompt_cache_key": "request_hash_1",
    }]
    assert result.text == "Grok final response"
    assert result.provider_request_id == "xai_response_1"
    assert result.cost_usd == pytest.approx(0.0005)


def test_llm_assistant_v2_runs_through_registered_xai_provider(client, monkeypatch):
    captured = {}
    monkeypatch.setenv("GENERATION_PROVIDER_MODE", "live")

    class FakeService:
        def generate(self, **kwargs):
            captured.update(kwargs)
            return XAITextResult(
                text="Grok Node result",
                provider_request_id="xai_node_response",
                exact_model_id="grok-4.6",
                input_tokens=120,
                output_tokens=30,
                cost_usd=0.00042,
            )

    monkeypatch.setattr(experiments_module, "get_xai_text_services", lambda: FakeService())
    connected = client.put("/settings/providers/xai", json={
        "enabled": True,
        "auth_method": "api_key",
        "values": {"api_key": "xai-database-test"},
    })
    assert connected.status_code == 200
    assert connected.json()["configured"] is True
    api_key = next(field for field in connected.json()["fields"] if field["key"] == "api_key")
    assert api_key["value"] == ""
    assert api_key["has_value"] is True

    response = client.post("/experiments", json={
        "canvas_id": "canvas_grok",
        "node_id": "grok_1",
        "node_key": "llm.assistant",
        "node_contract_version": 2,
        "prompt": "Summarize this",
        "model_alias": "xai.text.quality",
        "parameters": {
            "provider": "xai",
            "temperature": 0.4,
        },
        "inputs": [],
    })

    assert response.status_code == 201
    payload = response.json()
    assert payload["status"] == "SUCCEEDED"
    assert payload["model_alias"] == "xai.text.quality"
    assert payload["exact_model_id"] == "grok-4.6"
    assert payload["provider_request_id"] == "xai_node_response"
    assert payload["output"]["text"] == "Grok Node result"
    assert payload["cost_usd"] == pytest.approx(0.00042)
    assert captured["reasoning_effort"] == "high"
    assert captured["prompt_cache_key"] == payload["request_hash"]

    model = next(item for item in client.get("/models").json() if item["logical_alias"] == "xai.text.quality")
    assert model["provider"] == "xAI"
    assert model["exact_model_id"] == "grok-4.6"
    assert model["configured"] is True
