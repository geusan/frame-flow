from __future__ import annotations

from app.domain import ExperimentRunRequest
from app.providers_fal import FalGenerationServices, FalProviderConfig


class FakeResponse:
    def __init__(self, payload=None, *, content=b"", content_type="application/json"):
        self.payload = payload or {}
        self.content = content
        self.headers = {"content-type": content_type}

    def json(self):
        return self.payload

    def raise_for_status(self):
        return None


class FakeFalClient:
    def __init__(self):
        self.submitted = None

    def post(self, url, **kwargs):
        self.submitted = {"url": url, **kwargs}
        return FakeResponse({
            "request_id": "fal_request_1",
            "status_url": "https://queue.fal.run/status/fal_request_1",
            "response_url": "https://queue.fal.run/result/fal_request_1",
        })

    def get(self, url, **kwargs):
        if "/status/" in url:
            return FakeResponse({"status": "COMPLETED"})
        if "/result/" in url:
            return FakeResponse({"images": [{"url": "https://cdn.fal.test/result.png", "content_type": "image/png"}]})
        if url == "https://cdn.fal.test/result.png":
            return FakeResponse(content=b"generated-png", content_type="image/png")
        raise AssertionError(f"unexpected URL: {url}")


def test_flux2_lora_provider_submits_weights_trigger_and_scale():
    client = FakeFalClient()
    service = FalGenerationServices(FalProviderConfig("fal-test-key"), client)
    payload = ExperimentRunRequest(
        canvas_id="canvas",
        node_id="lora",
        node_key="lora.image.generate",
        prompt="working at a cafe in warm morning light",
        model_alias="fal.image.flux2-lora",
        parameters={
            "lora_url": "https://weights.example/mori.safetensors",
            "lora_scale": 0.85,
            "trigger_word": "mori_catgirl_v1",
            "aspect_ratio": "9:16",
            "resolution": "2K",
        },
        inputs=[],
    )
    result = service.execute(payload, [])
    assert result.content == b"generated-png"
    assert result.provider_request_id == "fal_request_1"
    request = client.submitted["json"]
    assert request["prompt"].startswith("mori_catgirl_v1,")
    assert request["loras"] == [{"path": "https://weights.example/mori.safetensors", "scale": 0.85}]
    assert request["image_size"] == {"width": 1152, "height": 2048}
    assert client.submitted["headers"]["Authorization"] == "Key fal-test-key"


def test_flux2_lora_training_submits_downloadable_dataset_url():
    client = FakeFalClient()
    service = FalGenerationServices(FalProviderConfig("fal-test-key"), client)
    submission = service.submit_lora_training(
        image_data_url="https://example.r2.cloudflarestorage.com/training.zip?X-Amz-Signature=test",
        trigger_word="mori_catgirl_v1",
        steps=1000,
    )
    assert submission["status"] == "IN_QUEUE"
    assert client.submitted["url"].endswith("/fal-ai/flux-2-trainer-v2")
    request = client.submitted["json"]
    assert request["default_caption"].startswith("mori_catgirl_v1")
    assert request["image_data_url"].startswith("https://example.r2.cloudflarestorage.com/")
