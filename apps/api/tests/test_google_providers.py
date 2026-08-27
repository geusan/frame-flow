from types import SimpleNamespace

from app.providers_google import GoogleProviderConfig, GoogleTextProvider, GoogleVideoProvider


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

