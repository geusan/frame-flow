import asyncio
import json
from pathlib import Path

import pytest

from app import canvas_activities
from app.canvas_documents import canonicalize_canvas_document
from app.canvas_runs import create_canvas_run, execute_canvas_node
from app.database import SessionLocal
from app.domain import CanvasRunRequest, ExperimentRunRequest
from app.experiments import request_fingerprint, resolve_model
from app.nodes import node_registry
from app.providers_generation import CHARACTER_SHOTS, STUDIO_CHARACTER_SHOTS, InputMedia, character_shot_prompts
from app.providers_openai import OpenAIGenerationServices, OpenAIProviderConfig, StudioCharacterGenerationError
from test_openai_providers import FakeOpenAIClient


def recording_service():
    client = FakeOpenAIClient()
    calls = []
    edit = client.images.edit
    generate = client.images.generate

    def record_edit(**kwargs):
        calls.append(kwargs)
        return edit(**kwargs)

    def record_generate(**kwargs):
        calls.append(kwargs)
        return generate(**kwargs)

    client.images.edit = record_edit
    client.images.generate = record_generate
    return OpenAIGenerationServices(OpenAIProviderConfig("test"), client), calls


def test_studio_contract_keeps_v1_and_materializes_v2_defaults():
    v1 = node_registry.get("character.generate", 1)
    v2 = node_registry.get("character.generate", 2)
    golden = json.loads((Path(__file__).parent / "fixtures/node_definition_digests.v1.json").read_text())
    assert v1.definition_digest == golden["character.generate@1"]
    assert v1.ports == v2.ports
    assert "shot_style" not in v1.config_schema["properties"]
    config = node_registry.resolve_config(v2, {})
    assert config["shot_style"] == "studio"
    assert config["shot_count"] == 8
    assert config["quality"] == "high"
    assert v2.editor.kind == "generic"
    assert v2.execution.model_families == ["openai.image."]
    assert node_registry.runtime_revision(v2, config) == "character-openai.v2"
    with pytest.raises(ValueError, match="unknown"):
        node_registry.resolve_config(v2, {"unknown_setting": True})
    assert "shot_style" not in node_registry.resolve_config(v1, {"shot_style": "studio"})
    with pytest.raises(ValueError, match="one of"):
        node_registry.resolve_config(v2, {"shot_count": 7})
    payload = ExperimentRunRequest(canvas_id="canvas", node_id="character", node_key="character.generate", model_alias="openai.image.default")
    model, exact = resolve_model(payload.model_alias, payload.node_key, 1)
    assert request_fingerprint(payload, model, exact) != request_fingerprint(payload.model_copy(update={"node_contract_version": 2}), model, exact)


def test_studio_uses_all_four_references_and_generated_anchor_without_changing_v1():
    service, calls = recording_service()
    references = [InputMedia(f"ref-{i}", "Image", f"reference-{i}".encode(), "image/jpeg") for i in range(4)]
    result = service.generate_character(logical_model="openai.image.default", synopsis="First reference identity; other references only for styling.", name="Studio", shot_count=8, aspect_ratio="9:16", quality="high", reference_images=references, shot_style="studio")
    assert len(result.images) == len(calls) == 8
    assert [image.role for image in result.images] == [role for role, _ in STUDIO_CHARACTER_SHOTS]
    assert [image[1] for image in calls[0]["image"]] == [reference.data for reference in references]
    for request in calls[1:]:
        assert request["image"][0][1] == result.images[0].data
        assert [image[1] for image in request["image"][1:]] == [reference.data for reference in references]
        assert request["model"] == "gpt-image-2"
        assert request["quality"] == "high"
        assert "input_fidelity" not in request
    legacy = character_shot_prompts("Legacy", 8)
    assert [role for role, _ in legacy] == [role for role, _ in CHARACTER_SHOTS]
    assert "quiet cafe table" in legacy[2][1]
    for _, prompt in character_shot_prompts("Studio", 8, shot_style="studio"):
        assert "same seamless neutral-gray studio" in prompt
        assert "quiet cafe table" not in prompt


@pytest.mark.parametrize("temporal", [False, True])
def test_studio_character_local_temporal_artifacts_and_lineage(client, monkeypatch, temporal):
    service, calls = recording_service()
    monkeypatch.setenv("GENERATION_PROVIDER_MODE", "live")
    monkeypatch.setattr("app.nodes.executors.character_generation.get_openai_generation_services", lambda: service)
    monkeypatch.setattr(canvas_activities, "refresh_provider_environment", lambda: None)
    monkeypatch.setattr(canvas_activities.activity, "heartbeat", lambda *_: None)
    ids = [client.post("/artifacts/upload", files={"file": (f"ref-{i}.png", f"image-{i}".encode(), "image/png")}).json()["artifact_id"] for i in range(4)]
    nodes = [{"id": f"ref-{i}", "data": {"key": "asset.select", "contractVersion": 2, "config": {"artifact_id": artifact_id, "artifact_type": "Image"}, "outputArtifactIds": [artifact_id]}} for i, artifact_id in enumerate(ids)]
    nodes += [{"id": "studio", "data": {"key": "character.generate", "contractVersion": 2, "model": "openai.image.default", "provider": "openai", "config": {"character_name": "Studio test"}}}]
    edges = [{"id": f"edge-{i}", "source": f"ref-{i}", "target": "studio", "sourceHandle": "artifact", "targetHandle": "images", "data": {"order": i}} for i in range(4)]
    saved = client.post("/canvases", json={"name": "Studio test", "document": canonicalize_canvas_document(nodes, edges)}).json()
    with SessionLocal() as db:
        run = create_canvas_run(db, CanvasRunRequest(canvas_id=saved["id"], canvas_revision=saved["revision"], target_node_id="studio"))
        db.commit()
        run_id = run.id
    result = asyncio.run(canvas_activities.execute_canvas_node_activity(run_id, "studio")) if temporal else execute_canvas_node(run_id, "studio")
    assert len(result["artifact_ids"]) == 1, result
    character = client.get(f"/artifacts/{result['artifact_ids'][0]}").json()
    assert character["type"] == "Character"
    assert character["schema_id"] == "character.v1"
    assert character["metadata"]["reference_image_artifact_ids"] == ids
    assert character["metadata"]["execution_mode"] == "character-openai.v2"
    assert character["metadata"]["normalized_config"]["shot_style"] == "studio"
    assert len(character["metadata"]["image_artifact_ids"]) == len(calls) == 8
    for image_id in character["metadata"]["image_artifact_ids"]:
        image = client.get(f"/artifacts/{image_id}").json()
        assert image["schema_id"] == "character.view.v1"
        assert image["input_artifact_ids"] == ids
        assert set(image["metadata"]["input_artifact_roles"].values()) == {"reference_image"}


def test_studio_partial_provider_failure_is_not_automatically_retryable():
    service, _ = recording_service()

    def fail(**kwargs):
        raise RuntimeError("provider unavailable")

    service.generate_images = fail
    with pytest.raises(StudioCharacterGenerationError) as caught:
        service.generate_character(logical_model="openai.image.default", synopsis="Studio", name="Studio", shot_count=8, aspect_ratio="9:16", quality="high", reference_images=[], shot_style="studio")
    assert caught.value.retryable is False
    assert "view 1/8" in str(caught.value)
