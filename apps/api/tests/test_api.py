from copy import deepcopy
import json
import subprocess
import threading
import time
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.canvas_operations import executor_revision
from app.database import ExperimentRunRecord
from app.experiments import FIXTURE_EXECUTOR_REVISION
from app.media_preview import render_audio_wav, render_video_mp4
from app.providers_localization import (
    LocalizationServices,
    SpeechSegment,
    SynthesizedSpeech,
    TranscriptResult,
    TranslationResult,
)
from app.providers_generation import LiveGenerationResult


def test_executor_revision_fits_persisted_execution_mode(monkeypatch):
    max_length = ExperimentRunRecord.__table__.c.execution_mode.type.length
    assert max_length == 64
    assert len(FIXTURE_EXECUTOR_REVISION) <= max_length

    for analysis_mode, audio_separator in (("live", "demucs"), ("fixture", "fixture")):
        monkeypatch.setenv("REFERENCE_ANALYSIS_MODE", analysis_mode)
        monkeypatch.setenv("REFERENCE_AUDIO_SEPARATOR", audio_separator)
        assert len(executor_revision("reference.decompose")) <= max_length


def test_project_skill_registry_and_executor_snapshot_are_available(client: TestClient):
    skills = client.get("/skills")
    assert skills.status_code == 200
    registered = next(skill for skill in skills.json() if skill["id"] == "nottalggak-prompt-machine")
    assert registered["display_name"] == "NOTTALGGAK Prompt Machine"
    assert len(registered["version"]) == 64

    executed = client.post("/experiments", json={
        "canvas_id": "skill_canvas",
        "node_id": "skill_executor",
        "node_key": "skill.execute",
        "prompt": "비 오는 밤의 작은 골목",
        "model_alias": "text.3.1-pro-preview",
        "parameters": {"skill_id": registered["id"], "provider": "google"},
        "inputs": [],
    })
    assert executed.status_code == 201
    result = executed.json()
    assert result["status"] == "SUCCEEDED"
    assert result["model_alias"] == "google.text.3.1-pro-preview"
    assert result["exact_model_id"] == "gemini-3.1-pro-preview"
    assert result["parameters"]["skill_version"] == registered["version"]
    assert result["output"]["title"] == "Generated master prompt"
    assert "### 1. English Master Prompt" in result["output"]["text"]


def import_reference(client: TestClient, suffix: str = "abc") -> str:
    inspect = client.post("/references/inspect", json={"urls": [f"https://youtube.com/watch?v={suffix}"]})
    assert inspect.status_code == 200
    response = client.post("/references/import", json={"metadata": inspect.json()[0], "rights_basis": "analysis_only"})
    assert response.status_code == 201
    return response.json()["reference_id"]


def create_format(client: TestClient) -> str:
    reference_ids = [import_reference(client, "a1"), import_reference(client, "b2")]
    reference_set = client.post("/reference-sets", json={"name": "Test set", "reference_ids": reference_ids})
    assert reference_set.status_code == 201
    result = client.post("/format-runs", json={"reference_set_id": reference_set.json()["id"], "name": "Test format"})
    assert result.status_code == 201
    return result.json()["id"]


def test_reference_deduplication_and_rights_isolation(client: TestClient):
    first_id = import_reference(client, "same-video")
    preview = client.post("/references/inspect", json={"urls": ["https://youtube.com/watch?v=same-video&utm_source=x"]}).json()[0]
    assert preview["duplicate_reference_id"] == first_id
    imported = client.post("/references/import", json={"metadata": preview, "rights_basis": "analysis_only", "allow_generation_input": True})
    assert imported.json()["deduplicated"] is True
    record = client.get("/references").json()[0]
    assert record["allow_generation_input"] is False


def test_format_variation_and_merge_preserve_lineage(client: TestClient):
    format_a = create_format(client)
    reference_id = import_reference(client, "c3")
    reference_set = client.post("/reference-sets", json={"name": "Second", "reference_ids": [reference_id]}).json()
    format_b = client.post("/format-runs", json={"reference_set_id": reference_set["id"], "name": "Second format"}).json()["id"]
    variants = client.post(f"/formats/{format_a}/variants", json={"count": 3, "distance": "medium", "variation_axes": ["visual_motion"]})
    assert variants.status_code == 201
    assert len(variants.json()) == 3
    merged = client.post("/formats/merge", json={"name": "Merged", "sources": [{"format_id": format_a, "weight": 0.7}, {"format_id": format_b, "weight": 0.3}]})
    assert merged.status_code == 201
    assert merged.json()["lineage"]["core.editing.median_shot_duration_ms"]["strategy"] == "weighted_average"


def test_generation_compile_budget_and_immutable_node_history(client: TestClient):
    format_id = create_format(client)
    over_budget = client.post("/generation-briefs", json={"topic": "Budget failure", "key_message": "x", "audience": "general", "format_id": format_id, "budget_limit_usd": 1})
    response = client.post("/generation-runs", json={"brief_id": over_budget.json()["id"], "dry_run": True})
    assert response.status_code == 422

    brief = client.post("/generation-briefs", json={"topic": "Roman roads", "key_message": "Old engineering survives", "audience": "history fans", "format_id": format_id, "budget_limit_usd": 5})
    run = client.post("/generation-runs", json={"brief_id": brief.json()["id"], "dry_run": True})
    assert run.status_code == 201
    payload = run.json()
    assert payload["execution_plan"]["checks"]["reference_isolation"] is True
    assert payload["execution_plan"]["expanded_jobs"] > 40
    assert len(payload["node_runs"]) == 12


def test_fork_reuses_upstream_without_overwriting(client: TestClient):
    format_id = create_format(client)
    brief = client.post("/generation-briefs", json={"topic": "Fork test", "key_message": "x", "audience": "general", "format_id": format_id, "budget_limit_usd": 5}).json()
    run = client.post("/generation-runs", json={"brief_id": brief["id"], "dry_run": True}).json()
    target = run["node_runs"][4]
    fork = client.post(f"/node-runs/{target['id']}/fork")
    assert fork.status_code == 201
    forked = client.get(f"/runs/{fork.json()['run_id']}").json()
    assert forked["execution_plan"]["forked_at_node"] == target["node_key"]
    assert forked["id"] != run["id"]


def test_run_waits_for_candidate_selection_then_resumes(client: TestClient):
    format_id = create_format(client)
    brief = client.post("/generation-briefs", json={"topic": "End to end", "key_message": "x", "audience": "general", "format_id": format_id, "budget_limit_usd": 5}).json()
    run = client.post("/generation-runs", json={"brief_id": brief["id"]}).json()
    deadline = time.monotonic() + 6
    while time.monotonic() < deadline:
        run = client.get(f"/runs/{run['id']}").json()
        if run["status"] == "WAITING_INPUT":
            break
        time.sleep(0.08)
    assert run["status"] == "WAITING_INPUT"
    candidate_node = next(node for node in run["node_runs"] if node["node_key"] == "candidate.select")
    video_node = next(node for node in run["node_runs"] if node["node_key"] == "video.generate")
    assert video_node["output_artifact_ids"]
    selected = client.post(f"/node-runs/{candidate_node['id']}/select", json={"artifact_id": video_node["output_artifact_ids"][0]})
    assert selected.status_code == 201
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        run = client.get(f"/runs/{run['id']}").json()
        if run["status"] == "SUCCEEDED":
            break
        time.sleep(0.08)
    assert run["status"] == "SUCCEEDED"
    assert run["progress"] == 100
    assert sum(len(node["output_artifact_ids"]) for node in run["node_runs"]) >= 10


def test_single_experiment_snapshots_inputs_caches_and_sets_baseline(client: TestClient):
    payload = {
        "canvas_id": "canvas_test",
        "node_id": "video_1",
        "node_key": "video.generate",
        "prompt": "A slow cinematic push-in on ancient stone",
        "model_alias": "video.fast",
        "parameters": {"resolution": "1080p", "aspect_ratio": "9:16", "seed": 42},
        "inputs": [{"node_id": "image_1", "type": "Image", "artifact_id": "art_image_1"}],
    }
    first = client.post("/experiments", json=payload)
    assert first.status_code == 201
    first_run = first.json()
    assert first_run["status"] == "SUCCEEDED"
    assert first_run["model_alias"] == "google.video.fast"
    assert first_run["exact_model_id"] == "veo-3.1-fast-generate-001"
    assert first_run["inputs"] == payload["inputs"]
    assert first_run["cache_hit"] is False
    assert len(first_run["output_artifact_ids"]) == 1
    assert first_run["output"]["mimeType"] == "video/mp4"
    assert first_run["output"]["url"].endswith(f"/artifacts/{first_run['output_artifact_ids'][0]}/content")
    artifact_id = first_run["output_artifact_ids"][0]
    artifact = client.get(f"/artifacts/{artifact_id}").json()
    assert artifact["uri"].startswith("memory://project-generation-assets/")
    assert artifact["metadata"]["storage"]["content_type"] == "video/mp4"
    assert artifact["metadata"]["storage"]["size_bytes"] > 0
    download = client.get(f"/artifacts/{artifact_id}/download-url").json()
    assert download["provider"] == "memory"
    assert download["url"].startswith("memory://project-generation-assets/")
    content = client.get(f"/artifacts/{artifact_id}/content", follow_redirects=False)
    assert content.status_code == 200
    assert content.headers["content-type"].startswith("video/mp4")
    assert len(content.content) == artifact["metadata"]["storage"]["size_bytes"]

    second_run = client.post("/experiments", json=payload).json()
    assert second_run["id"] != first_run["id"]
    assert second_run["request_hash"] == first_run["request_hash"]
    assert second_run["cache_hit"] is True
    assert second_run["cached_from_id"] == first_run["id"]
    assert second_run["cost_usd"] == 0

    changed = client.post("/experiments", json={**payload, "model_alias": "video.quality"}).json()
    assert changed["request_hash"] != first_run["request_hash"]

    baseline = client.post(f"/experiments/{first_run['id']}/baseline")
    assert baseline.status_code == 200
    assert baseline.json()["is_baseline"] is True
    history = client.get("/experiments", params={"canvas_id": "canvas_test", "node_id": "video_1"})
    assert history.status_code == 200
    assert len(history.json()) == 3
    assert sum(item["is_baseline"] for item in history.json()) == 1
    invalid = client.post("/experiments", json={**payload, "model_alias": "text.quality"})
    assert invalid.status_code == 422


def test_live_generation_mode_uses_google_service_without_deterministic_fallback(client: TestClient, monkeypatch):
    class FakeLiveServices:
        def execute(self, payload, inputs):
            assert payload.node_key == "image.generate"
            assert inputs == []
            return LiveGenerationResult(
                {"kind": "image", "title": "Live image", "mimeType": "image/png"},
                "Image", "google.image.v1", "google_live_request", b"\x89PNG\r\n\x1a\n",
                "image/png", "generated.png", [],
            )

    monkeypatch.setenv("GENERATION_PROVIDER_MODE", "live")
    monkeypatch.setattr("app.experiments.get_google_generation_services", lambda: FakeLiveServices())
    response = client.post("/experiments", json={
        "canvas_id": "canvas_live",
        "node_id": "image_live",
        "node_key": "image.generate",
        "prompt": "A live provider image",
        "model_alias": "image.fast",
        "parameters": {"aspect_ratio": "9:16"},
        "inputs": [],
    })
    assert response.status_code == 201
    result = response.json()
    assert result["status"] == "SUCCEEDED"
    assert result["execution_mode"] == "google-live.v1"
    assert result["provider_request_id"] == "google_live_request"
    assert result["output"]["title"] == "Live image"


def test_openai_chat_provider_routes_through_live_service(client: TestClient, monkeypatch):
    class FakeOpenAIServices:
        def execute(self, payload, inputs):
            assert payload.model_alias == "openai.chat.latest"
            assert payload.node_key == "llm.assistant"
            return LiveGenerationResult(
                {"kind": "text", "title": "ChatGPT response", "text": "OpenAI response"},
                "Text", "openai.text.v1", "resp_openai_test", b"OpenAI response",
                "text/plain", "result.txt", [],
            )

    monkeypatch.setenv("GENERATION_PROVIDER_MODE", "live")
    monkeypatch.setattr("app.experiments.get_openai_generation_services", lambda: FakeOpenAIServices())
    response = client.post("/experiments", json={
        "canvas_id": "canvas_openai",
        "node_id": "assistant_openai",
        "node_key": "llm.assistant",
        "prompt": "Use ChatGPT",
        "model_alias": "openai.chat.latest",
        "parameters": {},
        "inputs": [],
    })
    assert response.status_code == 201
    result = response.json()
    assert result["status"] == "SUCCEEDED"
    assert result["execution_mode"] == "openai-live.v1"
    assert result["exact_model_id"] == "chat-latest"
    assert result["provider_request_id"] == "resp_openai_test"
    mismatch = client.post("/experiments", json={
        "canvas_id": "canvas_openai",
        "node_id": "assistant_mismatch",
        "node_key": "llm.assistant",
        "prompt": "Mismatch",
        "model_alias": "openai.chat.latest",
        "parameters": {"provider": "google"},
        "inputs": [],
    })
    assert mismatch.status_code == 422


def test_canvas_can_import_a_video_url_as_an_artifact(client: TestClient):
    response = client.post("/artifacts/import-url", json={"url": "https://youtube.com/watch?v=canvas-url"})
    assert response.status_code == 201
    imported = response.json()
    assert imported["type"] == "Video"
    assert imported["content_type"] == "video/mp4"
    assert imported["filename"].endswith(".mp4")
    assert imported["source_url"] == "https://youtube.com/watch?v=canvas-url"
    assert imported["downloader_provider"] == "fixture"
    assert imported["size_bytes"] > 0
    assert client.get(f"/artifacts/{imported['artifact_id']}/content").content[:8] != b""
    artifact = client.get(f"/artifacts/{imported['artifact_id']}").json()
    assert artifact["metadata"]["source"] == "canvas_url_import"
    assert artifact["metadata"]["source_url"] == imported["source_url"]
    assert artifact["metadata"]["downloader_provider"] == "fixture"
    listed = client.get("/artifacts", params={"types": "Image,Video,FinalVideo", "limit": 500}).json()
    listed_asset = next(item for item in listed if item["id"] == imported["artifact_id"])
    assert listed_asset["source"] == "canvas_url_import"
    assert listed_asset["size_bytes"] == imported["size_bytes"]
    assert listed_asset["duration_ms"] == 35_000


def test_manual_image_edit_creates_an_immutable_derived_artifact(client: TestClient):
    uploaded = client.post(
        "/artifacts/upload",
        files={"file": ("source.png", b"\x89PNG\r\n\x1a\nsource", "image/png")},
    ).json()
    document = {
        "version": "image-edit.v1",
        "aspect_ratio": "4:5",
        "transform": {
            "rotation": 2.5,
            "zoom": 1.15,
            "offset_x": 0.1,
            "offset_y": -0.05,
            "flip_horizontal": False,
            "flip_vertical": False,
        },
        "adjustments": {
            "brightness": 1.08,
            "contrast": 1.05,
            "saturation": 0.95,
            "blur": 0,
            "grayscale": 0,
            "sepia": 0,
        },
        "lighting": {
            "enabled": True,
            "x": 0.68,
            "y": 0.3,
            "intensity": 1.15,
            "radius": 0.52,
            "softness": 0.8,
            "color": "#ffd6a3",
        },
    }
    response = client.post(
        f"/artifacts/{uploaded['artifact_id']}/image-edits",
        files={"file": ("edited.png", b"\x89PNG\r\n\x1a\nedited", "image/png")},
        data={"edit_document": json.dumps(document)},
    )
    assert response.status_code == 201
    edited = response.json()
    assert edited["type"] == "Image"
    assert edited["source"] == "image_manual_edit"
    assert edited["filename"] == "source-edited.png"

    artifact = client.get(f"/artifacts/{edited['id']}").json()
    assert artifact["input_artifact_ids"] == [uploaded["artifact_id"]]
    assert artifact["metadata"]["immutable"] is True
    assert artifact["metadata"]["image_edit"] == document
    lineage = client.get(f"/artifacts/{edited['id']}/lineage").json()
    node = next(item for item in lineage["nodes"] if item["id"] == edited["id"])
    assert node["derivation"]["operation"] == "image.manual_edit"
    assert node["derivation"]["parameters"] == document
    edge = next(item for item in lineage["edges"] if item["child_artifact_id"] == edited["id"])
    assert edge["parent_artifact_id"] == uploaded["artifact_id"]
    assert edge["role"] == "source_image"


def test_video_frame_capture_creates_a_derived_image_artifact(client: TestClient):
    imported = client.post(
        "/artifacts/import-url",
        json={"url": "https://youtube.com/watch?v=frame-capture"},
    ).json()
    partial = client.get(
        f"/artifacts/{imported['artifact_id']}/content",
        headers={"Range": "bytes=0-99"},
    )
    assert partial.status_code == 206
    assert len(partial.content) == 100
    assert partial.headers["accept-ranges"] == "bytes"
    assert partial.headers["content-range"].endswith(f"/{imported['size_bytes']}")

    response = client.post(
        f"/artifacts/{imported['artifact_id']}/capture-frame",
        json={"timestamp_ms": 500},
    )

    assert response.status_code == 201
    captured = response.json()
    assert captured["type"] == "Image"
    assert captured["content_type"] == "image/jpeg"
    assert captured["source"] == "video_frame_capture"
    assert captured["source_artifact_id"] == imported["artifact_id"]
    assert captured["timestamp_ms"] == 500
    assert captured["filename"].endswith("-frame-00-00-00-500.jpg")
    content = client.get(f"/artifacts/{captured['id']}/content")
    assert content.status_code == 200
    assert content.content.startswith(b"\xff\xd8")
    probe = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height", "-of", "json", "pipe:0",
        ],
        input=content.content,
        check=True,
        capture_output=True,
    )
    assert json.loads(probe.stdout)["streams"][0] == {"width": 360, "height": 640}

    artifact = client.get(f"/artifacts/{captured['id']}").json()
    assert artifact["input_artifact_ids"] == [imported["artifact_id"]]
    assert artifact["metadata"]["capture"] == {
        "operation": "ffmpeg-accurate-seek.v1",
        "source_artifact_id": imported["artifact_id"],
        "timestamp_ms": 500,
        "source_duration_ms": 1000,
        "width": 360,
        "height": 640,
    }
    lineage = client.get(f"/artifacts/{captured['id']}/lineage").json()
    assert lineage["root_artifact_id"] == captured["id"]
    assert {node["id"] for node in lineage["nodes"]} == {
        imported["artifact_id"],
        captured["id"],
    }
    captured_node = next(node for node in lineage["nodes"] if node["id"] == captured["id"])
    assert captured_node["derivation"]["operation"] == "video.frame.capture"
    assert "0.500s" in captured_node["derivation"]["description"]
    assert captured_node["derivation"]["parameters"]["source_artifact_id"] == imported["artifact_id"]
    assert len(lineage["edges"]) == 1
    edge = lineage["edges"][0]
    assert edge["parent_artifact_id"] == imported["artifact_id"]
    assert edge["child_artifact_id"] == captured["id"]
    assert edge["role"] == "source_video"
    assert edge["ordinal"] == 0
    assert edge["operation_id"] == "ffmpeg-accurate-seek.v1"
    descendants = client.get(
        f"/artifacts/{imported['artifact_id']}/lineage",
        params={"direction": "descendants", "depth": 1},
    ).json()
    assert {node["id"] for node in descendants["nodes"]} == {
        imported["artifact_id"],
        captured["id"],
    }

    past_end = client.post(
        f"/artifacts/{imported['artifact_id']}/capture-frame",
        json={"timestamp_ms": 2_000},
    )
    assert past_end.status_code == 422


def test_video_frame_preview_returns_cached_jpeg_without_creating_artifact(client: TestClient):
    imported = client.post(
        "/artifacts/import-url",
        json={"url": "https://youtube.com/watch?v=frame-preview"},
    ).json()
    images_before = client.get("/artifacts", params={"types": "Image", "limit": 500, "offset": 0}).json()

    response = client.get(
        f"/artifacts/{imported['artifact_id']}/frame-preview",
        params={"timestamp_ms": 500},
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.headers["cache-control"] == "public, max-age=86400, immutable"
    assert response.headers["x-frame-timestamp-ms"] == "500"
    assert response.content.startswith(b"\xff\xd8")
    images_after = client.get("/artifacts", params={"types": "Image", "limit": 500, "offset": 0}).json()
    assert len(images_after) == len(images_before)


def test_prompt_scene_search_seeks_and_captures_with_search_lineage(client: TestClient):
    imported = client.post(
        "/artifacts/import-url",
        json={"url": "https://youtube.com/watch?v=scene-search"},
    ).json()
    response = client.post(
        f"/artifacts/{imported['artifact_id']}/scene-search",
        json={
            "prompt": "인물이 카메라를 바라보는 장면",
            "provider": "google",
            "model_alias": "google.text.quality",
            "candidate_count": 3,
            "sample_count": 5,
        },
    )

    assert response.status_code == 200
    search = response.json()
    assert search["provider"] == "google"
    assert search["model_alias"] == "google.text.quality"
    assert search["exact_model_id"] == "gemini-3.1-pro-preview"
    assert len(search["candidates"]) == 3
    assert all(candidate["thumbnail_data_url"].startswith("data:image/jpeg;base64,") for candidate in search["candidates"])
    assert [candidate["score"] for candidate in search["candidates"]] == sorted(
        [candidate["score"] for candidate in search["candidates"]],
        reverse=True,
    )

    selected = search["candidates"][0]
    captured_response = client.post(
        f"/artifacts/{imported['artifact_id']}/capture-frame",
        json={
            "timestamp_ms": selected["timestamp_ms"],
            "search_id": search["search_id"],
            "search_prompt": search["prompt"],
            "search_score": selected["score"],
            "search_reason": selected["reason"],
            "search_provider": search["provider"],
            "search_model_alias": search["model_alias"],
            "search_model": search["exact_model_id"],
            "provider_request_id": search["provider_request_id"],
        },
    )
    assert captured_response.status_code == 201
    captured = captured_response.json()
    lineage = client.get(f"/artifacts/{captured['id']}/lineage").json()
    captured_node = next(node for node in lineage["nodes"] if node["id"] == captured["id"])
    assert captured_node["derivation"]["prompt"] == search["prompt"]
    assert captured_node["derivation"]["model_alias"] == "google.text.quality"
    assert "Match score" in captured_node["derivation"]["description"]
    assert captured_node["derivation"]["parameters"]["scene_search"]["search_id"] == search["search_id"]

    openai = client.post(
        f"/artifacts/{imported['artifact_id']}/scene-search",
        json={
            "prompt": "A close-up detail",
            "provider": "openai",
            "model_alias": "openai.chat.latest",
            "candidate_count": 2,
            "sample_count": 3,
        },
    )
    assert openai.status_code == 200
    assert openai.json()["provider"] == "openai"
    assert openai.json()["model_alias"] == "openai.chat.latest"
    assert openai.json()["exact_model_id"] == "chat-latest"

    mismatch = client.post(
        f"/artifacts/{imported['artifact_id']}/scene-search",
        json={
            "prompt": "Mismatch",
            "provider": "google",
            "model_alias": "openai.chat.latest",
        },
    )
    assert mismatch.status_code == 422


def test_canvas_upload_and_real_media_edit_pipeline(client: TestClient, monkeypatch):
    upload = client.post("/artifacts/upload", files={"file": ("note.txt", b"Canvas source", "text/plain")})
    assert upload.status_code == 201
    uploaded = upload.json()
    assert uploaded["type"] == "Text"
    assert client.get(f"/artifacts/{uploaded['artifact_id']}/content").content == b"Canvas source"

    def execute(node_id: str, node_key: str, model_alias: str, prompt: str = "", inputs: list[dict] | None = None, parameters: dict | None = None):
        response = client.post("/experiments", json={
            "canvas_id": "canvas_media_pipeline",
            "node_id": node_id,
            "node_key": node_key,
            "prompt": prompt,
            "model_alias": model_alias,
            "parameters": parameters or {},
            "inputs": inputs or [],
        })
        assert response.status_code == 201
        result = response.json()
        assert result["status"] == "SUCCEEDED", result.get("error")
        return result

    video = execute("video", "video.generate", "video.fast", "A real editable video source")
    video_two = execute("video-two", "video.generate", "video.fast", "A second editable video source")
    audio = execute("audio", "tts.generate", "tts.fast", "Replacement narration")
    script = execute("script", "script.generate", "text.quality", "First sentence. Second sentence.")

    edited = execute(
        "editor",
        "video.edit",
        "local.ffmpeg",
        inputs=[
            {"type": "Video", "artifact_ids": video["output_artifact_ids"]},
            {"type": "Video", "artifact_ids": video_two["output_artifact_ids"]},
        ],
        parameters={"resolution": "source", "aspect_ratio": "source", "target_duration_seconds": 7, "transition": "crossfade"},
    )
    assert edited["execution_mode"] == "local-media.v1"
    assert edited["output"]["mimeType"] == "video/mp4"
    edited_artifact = client.get(f"/artifacts/{edited['output_artifact_ids'][0]}").json()
    assert edited_artifact["input_artifact_ids"] == video["output_artifact_ids"] + video_two["output_artifact_ids"]

    localized = execute(
        "replace-audio",
        "video.change_voice",
        "local.ffmpeg",
        inputs=[
            {"type": "Video", "artifact_ids": edited["output_artifact_ids"]},
            {"type": "Audio", "artifact_ids": audio["output_artifact_ids"]},
        ],
    )

    class FakeRecognizer:
        def transcribe(self, audio: bytes, *, language_code: str, duration_ms: int) -> TranscriptResult:
            assert audio.startswith(b"RIFF")
            assert language_code == "auto"
            assert duration_ms > 0
            return TranscriptResult("en-US", [
                SpeechSegment(0, 0, 900, "First sentence."),
                SpeechSegment(1, 900, 1800, "Second sentence."),
            ])

    class FakeTranslator:
        def translate(self, transcript: TranscriptResult, *, target_language: str) -> TranslationResult:
            assert transcript.language_code == "en-US"
            assert target_language == "ko-KR"
            return TranslationResult([
                SpeechSegment(0, 0, 900, "첫 번째 문장입니다."),
                SpeechSegment(1, 900, 1800, "두 번째 문장입니다."),
            ], "google_translation_test")

    class FakeSynthesizer:
        def synthesize(self, text: str, *, language_code: str, voice_name: str) -> SynthesizedSpeech:
            assert "첫 번째" in text
            assert language_code == "ko-KR"
            assert voice_name == "Kore"
            return SynthesizedSpeech(render_audio_wav("abc123", duration_seconds=2), "audio/wav", "google_tts_test")

    monkeypatch.setattr(
        "app.canvas_operations.get_localization_services",
        lambda: LocalizationServices(FakeRecognizer(), FakeTranslator(), FakeSynthesizer()),
    )
    translated = execute(
        "translate",
        "video.translate",
        "google.localization.pipeline",
        inputs=[{"type": "Video", "artifact_ids": video["output_artifact_ids"]}],
        parameters={"source_language": "auto", "target_language": "ko-KR", "voice_name": "Kore"},
    )
    assert translated["execution_mode"] == "google-localization.v1"
    assert translated["provider_request_id"] == "google_translation_test"
    assert translated["output"]["sourceLanguage"] == "en-US"
    assert translated["output"]["targetLanguage"] == "ko-KR"
    translated_artifact = client.get(f"/artifacts/{translated['output_artifact_ids'][0]}").json()
    assert len(translated_artifact["input_artifact_ids"]) == 5

    subtitles = execute(
        "subtitles",
        "subtitle.align",
        "local.subtitle-align",
        inputs=[
            {"type": "Audio", "artifact_ids": audio["output_artifact_ids"]},
            {"type": "Script", "artifact_ids": script["output_artifact_ids"]},
        ],
    )
    assert "-->" in subtitles["output"]["text"]

    timeline = execute(
        "timeline",
        "timeline.compose",
        "local.timeline",
        inputs=[
            {"type": "Video", "artifact_ids": localized["output_artifact_ids"]},
            {"type": "Subtitle", "artifact_ids": subtitles["output_artifact_ids"]},
        ],
        parameters={"caption_x": 0.5, "caption_y": 0.42, "caption_align": "center", "caption_font_size": 62},
    )
    assert '"version": "timeline.v1"' in timeline["output"]["text"]
    timeline_payload = json.loads(timeline["output"]["text"])
    caption_style = timeline_payload["caption_tracks"][0]["style"]
    assert caption_style["x"] == 0.5
    assert caption_style["y"] == 0.42
    assert caption_style["align"] == "center"
    assert caption_style["font_size"] == 62

    rendered = execute(
        "render",
        "video.render",
        "local.ffmpeg",
        inputs=[{"type": "Timeline", "artifact_ids": timeline["output_artifact_ids"]}],
    )
    qc = execute(
        "qc",
        "media.qc",
        "local.ffprobe",
        inputs=[{"type": "Video", "artifact_ids": rendered["output_artifact_ids"]}],
    )
    report = json.loads(qc["output"]["text"])
    assert report["passed"] is True
    assert report["checks"]["video_codec"]["actual"] == "h264"


def test_video_reference_analyzer_creates_composite_manifest_and_component_artifacts(client: TestClient):
    video = client.post("/experiments", json={
        "canvas_id": "reference_analysis_canvas",
        "node_id": "source-video",
        "node_key": "video.generate",
        "prompt": "Reference analyzer fixture source",
        "model_alias": "video.fast",
        "parameters": {},
        "inputs": [],
    })
    assert video.status_code == 201
    video_result = video.json()
    assert video_result["status"] == "SUCCEEDED"

    response = client.post("/experiments", json={
        "canvas_id": "reference_analysis_canvas",
        "node_id": "reference-analyzer",
        "node_key": "reference.decompose",
        "prompt": "Analyze the connected reference video",
        "model_alias": "reference-analysis.pipeline.v1",
        "parameters": {
            "source_language": "auto",
            "separate_music": True,
            "scene_threshold": 0.28,
        },
        "inputs": [{"type": "Video", "artifact_ids": video_result["output_artifact_ids"]}],
    })
    assert response.status_code == 201
    result = response.json()
    assert result["status"] == "SUCCEEDED", result.get("error")
    assert result["execution_mode"] == "reference-analysis.v1:fixture:fixture"
    assert result["exact_model_id"] == "reference-analysis.v1"
    assert len(result["output_artifact_ids"]) == 1

    manifest = json.loads(result["output"]["text"])
    assert manifest["schema_version"] == "reference.decomposition.v1"
    assert manifest["components"] == {
        "actions": "succeeded",
        "music_separation": "fixture",
        "onscreen_text": "succeeded",
        "shots": "succeeded",
        "sound_effects": "succeeded",
        "speech": "succeeded",
    }
    assert manifest["speech"]["segments"][0]["start_ms"] == 0
    assert len(manifest["visual"]["shots"]) >= 1
    assert len(manifest["visual"]["actions"]) == len(manifest["visual"]["shots"])
    assert manifest["visual"]["text_tracks"][0]["positions"][0]["bbox"]["y"] == 0.76
    assert set(manifest["artifacts"]) == {"audio_mix", "transcript", "subtitle", "vocals", "accompaniment"}

    analysis_artifact = client.get(f"/artifacts/{result['output_artifact_ids'][0]}").json()
    assert analysis_artifact["type"] == "ReferenceAnalysis"
    assert analysis_artifact["schema_id"] == "reference.decomposition.v1"
    assert analysis_artifact["metadata"]["storage"]["bucket"] == "project-reference-private"
    assert analysis_artifact["input_artifact_ids"][0] == video_result["output_artifact_ids"][0]
    assert set(analysis_artifact["input_artifact_ids"][1:]) == set(manifest["artifacts"].values())
    assert client.get(f"/artifacts/{manifest['artifacts']['subtitle']}/content").content.count(b"-->") >= 1

    vocals_id = manifest["artifacts"]["vocals"]
    exported_response = client.post(f"/artifacts/{vocals_id}/audio-asset")
    assert exported_response.status_code == 201
    exported = exported_response.json()
    assert exported["type"] == "Audio"
    assert exported["filename"] == "vocals.wav"
    assert exported["source"] == "reference_audio_export"
    assert client.get(f"/artifacts/{exported['artifact_id']}/content").content == client.get(f"/artifacts/{vocals_id}/content").content
    exported_detail = client.get(f"/artifacts/{exported['artifact_id']}").json()
    assert exported_detail["input_artifact_ids"] == [vocals_id]
    assert exported_detail["metadata"]["storage"]["bucket"] == "project-generation-assets"
    assert exported_detail["metadata"]["reference_component_type"] == "ReferenceVocals"
    assert client.post(f"/artifacts/{vocals_id}/audio-asset").json()["artifact_id"] == exported["artifact_id"]
    assert client.post(f"/artifacts/{video_result['output_artifact_ids'][0]}/audio-asset").status_code == 415
    assert exported["artifact_id"] in {item["id"] for item in client.get("/artifacts", params={"types": "Audio"}).json()}
    assert client.get("/workspace/summary").json()["audio"] == 1

    canvas_run = client.post("/canvas-runs", json={
        "canvas_id": "reference_analysis_graph",
        "name": "Reference analyzer graph",
        "nodes": [
            {"id": "asset", "data": {
                "key": "asset.select",
                "label": "Source video",
                "executable": False,
                "outputType": "Video",
                "outputArtifactIds": video_result["output_artifact_ids"],
                "output": {"kind": "video", "title": "Source", "mimeType": "video/mp4"},
            }},
            {"id": "analyzer", "data": {
                "key": "reference.decompose",
                "label": "Video reference analyzer",
                "description": "Analyze the connected reference video",
                "model": "reference-analysis.pipeline.v1",
                "outputType": "ReferenceAnalysis",
                "sourceLanguage": "auto",
                "separateMusic": True,
                "sceneThreshold": 0.28,
            }},
        ],
        "edges": [{"id": "asset-analysis", "source": "asset", "target": "analyzer"}],
    })
    assert canvas_run.status_code == 201
    run_id = canvas_run.json()["id"]
    for _ in range(100):
        graph_result = client.get(f"/canvas-runs/{run_id}").json()
        if graph_result["status"] in {"SUCCEEDED", "FAILED"}:
            break
        time.sleep(0.02)
    assert graph_result["status"] == "SUCCEEDED"
    analyzer_run = next(item for item in graph_result["node_runs"] if item["canvas_node_id"] == "analyzer")
    assert analyzer_run["status"] == "SUCCEEDED"
    assert json.loads(analyzer_run["output"]["text"])["schema_version"] == "reference.decomposition.v1"


def test_holistic_motion_extractor_creates_motion_track_artifact(client: TestClient, monkeypatch):
    video = client.post("/experiments", json={
        "canvas_id": "motion_canvas",
        "node_id": "source-video",
        "node_key": "video.generate",
        "prompt": "Holistic motion fixture source",
        "model_alias": "video.fast",
        "parameters": {},
        "inputs": [],
    })
    assert video.status_code == 201
    video_result = video.json()
    assert video_result["status"] == "SUCCEEDED"

    def fake_extract(video_data: bytes, content_type: str, **options):
        assert video_data
        assert content_type == "video/mp4"
        assert options["sample_fps"] == 12
        assert options["min_confidence"] == 0.5
        return {
            "schema_version": "motion.track.v1",
            "extractor": {
                "name": "MediaPipe Holistic Landmarker",
                "revision": "mediapipe.holistic.v1",
                "model": "holistic_landmarker.task",
                "min_confidence": 0.5,
                "output_face_blendshapes": True,
            },
            "source": {
                "duration_ms": 2000,
                "width": 540,
                "height": 960,
                "sample_fps": 12,
                "sample_width": 360,
                "sample_height": 640,
                "sha256": "a" * 64,
            },
            "summary": {
                "frame_count": 24,
                "coverage": {"face": 0.75, "pose": 1.0, "left_hand": 0.5, "right_hand": 0.25},
            },
            "frames": [{
                "timestamp_ms": 0,
                "face_landmarks": [],
                "pose_landmarks": [],
                "pose_world_landmarks": [],
                "left_hand_landmarks": [],
                "left_hand_world_landmarks": [],
                "right_hand_landmarks": [],
                "right_hand_world_landmarks": [],
                "face_blendshapes": [],
                "channels": {},
            }],
        }

    monkeypatch.setattr("app.canvas_operations.extract_holistic_motion", fake_extract)
    response = client.post("/experiments", json={
        "canvas_id": "motion_canvas",
        "node_id": "motion-extractor",
        "node_key": "motion.extract",
        "prompt": "Extract motion locally",
        "model_alias": "local.mediapipe.holistic",
        "parameters": {
            "motion_sample_fps": 12,
            "motion_max_width": 640,
            "motion_min_confidence": 0.5,
            "motion_face_blendshapes": True,
        },
        "inputs": [{"type": "Video", "artifact_ids": video_result["output_artifact_ids"]}],
    })
    assert response.status_code == 201
    result = response.json()
    assert result["status"] == "SUCCEEDED", result.get("error")
    assert result["execution_mode"] == "mediapipe.holistic.v1"
    assert result["exact_model_id"] == "mediapipe-holistic-landmarker"
    assert result["cost_usd"] == 0
    assert result["output"]["frameCount"] == 24
    assert result["output"]["poseCoverage"] == 1.0
    assert "text" not in result["output"]
    artifact = client.get(f"/artifacts/{result['output_artifact_ids'][0]}").json()
    assert artifact["type"] == "MotionTrack"
    assert artifact["schema_id"] == "motion.track.v1"
    assert artifact["input_artifact_ids"] == video_result["output_artifact_ids"]
    assert json.loads(client.get(f"/artifacts/{artifact['id']}/content").content)["schema_version"] == "motion.track.v1"


def test_canvas_worker_single_node_run_executes_only_target(client: TestClient, monkeypatch):
    captured: list[str] = []

    def fake_run_experiment(db, payload):
        del db
        captured.append(payload.node_id)
        return SimpleNamespace(
            status="SUCCEEDED",
            provider_request_id=f"provider_{payload.node_id}",
            request_hash=f"{payload.node_id:0<64}"[:64],
            output_artifact_ids=[f"artifact_{payload.node_id}"],
            output_payload={"kind": "text", "title": payload.node_id, "text": "done"},
            duration_ms=20,
            cost_usd=0.01,
            cache_hit=False,
            error=None,
        )

    monkeypatch.setattr("app.canvas_runs.run_experiment", fake_run_experiment)
    graph = {
        "canvas_id": "single_node_canvas",
        "name": "Single node Canvas",
        "target_node_id": "gen_b",
        "nodes": [
            {"id": "prompt", "data": {"key": "prompt.input", "label": "Prompt", "executable": False, "configText": "same prompt", "outputType": "Prompt"}},
            {"id": "gen_a", "data": {"key": "llm.assistant", "label": "A", "model": "text.fast", "outputType": "Text", "outputArtifactIds": ["existing_a"], "output": {"kind": "text", "title": "existing A", "text": "keep"}}},
            {"id": "gen_b", "data": {"key": "llm.assistant", "label": "B", "model": "text.fast", "outputType": "Text"}},
        ],
        "edges": [
            {"id": "prompt-a", "source": "prompt", "target": "gen_a"},
            {"id": "prompt-b", "source": "prompt", "target": "gen_b"},
        ],
    }
    response = client.post("/canvas-runs", json=graph)
    assert response.status_code == 201
    assert response.json()["graph"]["target_node_id"] == "gen_b"
    run_id = response.json()["id"]
    deadline = time.monotonic() + 3
    run = response.json()
    while time.monotonic() < deadline:
        run = client.get(f"/canvas-runs/{run_id}").json()
        if run["status"] in {"SUCCEEDED", "FAILED"}:
            break
        time.sleep(0.03)
    assert run["status"] == "SUCCEEDED"
    assert captured == ["gen_b"]
    by_id = {node["canvas_node_id"]: node for node in run["node_runs"]}
    assert by_id["gen_a"]["status"] == "SUCCEEDED"
    assert by_id["gen_a"]["attempt_count"] == 0
    assert by_id["gen_a"]["output_artifact_ids"] == ["existing_a"]
    assert by_id["gen_b"]["status"] == "SUCCEEDED"
    assert by_id["gen_b"]["attempt_count"] == 1
    assert by_id["gen_b"]["output_artifact_ids"] == ["artifact_gen_b"]

    missing = client.post("/canvas-runs", json={**graph, "target_node_id": "missing"})
    assert missing.status_code == 422
    assert missing.json()["detail"] == "Canvas target node is not present in the graph"
    non_executable = client.post("/canvas-runs", json={**graph, "target_node_id": "prompt"})
    assert non_executable.status_code == 422
    assert non_executable.json()["detail"] == "Canvas target node is not executable"


def test_canvas_run_snapshots_the_saved_canonical_canvas_revision(client: TestClient):
    created = client.post("/canvases", json={
        "name": "Stored run source",
        "nodes": [{
            "id": "prompt",
            "position": {"x": 10, "y": 20},
            "data": {
                "key": "prompt.input",
                "label": "Prompt",
                "description": "Stored snapshot",
                "configText": "original snapshot",
                "outputType": "Prompt",
                "executable": False,
            },
        }],
        "edges": [],
    }).json()
    started = client.post("/canvas-runs", json={
        "canvas_id": created["id"],
        "name": "Stored snapshot run",
        "canvas_revision": created["revision"],
    })
    assert started.status_code == 201, started.text
    assert started.json()["graph"]["canvas_revision"] == created["revision"]
    assert started.json()["graph"]["nodes"][0]["data"]["configText"] == "original snapshot"

    edited_nodes = deepcopy(created["nodes"])
    edited_nodes[0]["data"]["configText"] = "changed after run"
    saved = client.put(f"/canvases/{created['id']}", json={
        "name": created["name"],
        "nodes": edited_nodes,
        "edges": [],
        "expected_revision": created["revision"],
    })
    assert saved.status_code == 200
    assert saved.json()["revision"] == created["revision"] + 1
    frozen = client.get(f"/canvas-runs/{started.json()['id']}").json()
    assert frozen["graph"]["nodes"][0]["data"]["configText"] == "original snapshot"

    stale = client.post("/canvas-runs", json={
        "canvas_id": created["id"],
        "name": "Stale run",
        "canvas_revision": created["revision"],
    })
    assert stale.status_code == 422
    assert stale.json()["detail"] == f"Canvas revision conflict: expected {created['revision']}, current {saved.json()['revision']}"


def test_canvas_worker_runs_independent_nodes_in_parallel_and_streams_state(client: TestClient, monkeypatch):
    starts: list[float] = []
    lock = threading.Lock()

    def fake_run_experiment(db, payload):
        del db
        with lock:
            starts.append(time.monotonic())
        time.sleep(0.2)
        return SimpleNamespace(
            status="SUCCEEDED",
            provider_request_id=f"provider_{payload.node_id}",
            request_hash=f"{payload.node_id:0<64}"[:64],
            output_artifact_ids=[],
            output_payload={"kind": "text", "title": payload.node_id, "text": "done"},
            duration_ms=200,
            cost_usd=0.01,
            cache_hit=False,
            error=None,
        )

    monkeypatch.setattr("app.canvas_runs.run_experiment", fake_run_experiment)
    graph = {
        "canvas_id": "parallel_canvas",
        "name": "Parallel Canvas",
        "nodes": [
            {"id": "prompt", "data": {"key": "prompt.input", "label": "Prompt", "kind": "input", "executable": False, "configText": "same prompt", "outputType": "Prompt"}},
            {"id": "gen_a", "data": {"key": "llm.assistant", "label": "A", "kind": "generate", "provider": "google", "model": "text.fast", "outputType": "Text"}},
            {"id": "gen_b", "data": {"key": "llm.assistant", "label": "B", "kind": "generate", "provider": "openai", "model": "openai.chat.latest", "outputType": "Text"}},
        ],
        "edges": [
            {"id": "prompt-a", "source": "prompt", "target": "gen_a"},
            {"id": "prompt-b", "source": "prompt", "target": "gen_b"},
        ],
    }
    started_at = time.monotonic()
    response = client.post("/canvas-runs", json=graph)
    assert response.status_code == 201
    run_id = response.json()["id"]
    deadline = time.monotonic() + 3
    run = response.json()
    while time.monotonic() < deadline:
        run = client.get(f"/canvas-runs/{run_id}").json()
        if run["status"] == "SUCCEEDED":
            break
        time.sleep(0.03)
    assert run["status"] == "SUCCEEDED"
    assert len(starts) == 2
    assert abs(starts[0] - starts[1]) < 0.12
    assert time.monotonic() - started_at < 0.55
    event_stream = client.get(f"/canvas-runs/{run_id}/events")
    assert event_stream.status_code == 200
    assert "event: canvas.run.updated" in event_stream.text
    assert '"status":"SUCCEEDED"' in event_stream.text


def test_caption_layout_pauses_canvas_workflow_and_resumes_with_approved_position(client: TestClient, monkeypatch):
    captured = []

    def fake_run_experiment(db, payload):
        del db
        captured.append(payload)
        return SimpleNamespace(
            status="SUCCEEDED",
            provider_request_id=f"provider_{payload.node_id}",
            request_hash=f"{payload.node_id:0<64}"[:64],
            output_artifact_ids=[f"artifact_{payload.node_id}"],
            output_payload={"kind": "json" if payload.node_key == "timeline.compose" else "video", "title": payload.node_id, "text": "{}"},
            duration_ms=10,
            cost_usd=0,
            cache_hit=False,
            error=None,
        )

    monkeypatch.setattr("app.canvas_runs.run_experiment", fake_run_experiment)
    graph = {
        "canvas_id": "caption_workflow_canvas",
        "name": "Caption workflow",
        "nodes": [
            {"id": "video", "data": {"key": "asset.select", "label": "Video", "kind": "input", "executable": False, "outputType": "Video", "outputArtifactIds": ["video_artifact"]}},
            {"id": "subtitle", "data": {"key": "subtitle.align", "label": "Subtitle", "kind": "compose", "executable": False, "outputType": "Subtitle", "outputArtifactIds": ["subtitle_artifact"]}},
            {"id": "layout", "data": {"key": "timeline.compose", "label": "Caption layout", "kind": "compose", "model": "local.timeline", "outputType": "Timeline", "waitForInput": True, "captionX": 0.5, "captionY": 0.82, "captionAlign": "center", "captionFontSize": 54}},
            {"id": "render", "data": {"key": "video.render", "label": "Render", "kind": "compose", "model": "local.ffmpeg", "outputType": "Video"}},
        ],
        "edges": [
            {"id": "video-layout", "source": "video", "target": "layout"},
            {"id": "subtitle-layout", "source": "subtitle", "target": "layout"},
            {"id": "layout-render", "source": "layout", "target": "render"},
        ],
    }
    started = client.post("/canvas-runs", json=graph)
    assert started.status_code == 201
    run_id = started.json()["id"]
    deadline = time.monotonic() + 3
    run = started.json()
    while time.monotonic() < deadline:
        run = client.get(f"/canvas-runs/{run_id}").json()
        if run["status"] == "WAITING_INPUT":
            break
        time.sleep(0.03)
    assert run["status"] == "WAITING_INPUT"
    layout_node = next(node for node in run["node_runs"] if node["canvas_node_id"] == "layout")
    assert layout_node["status"] == "WAITING_INPUT"
    assert captured == []

    approved = client.post(f"/canvas-runs/{run_id}/nodes/layout/approve", json={"parameters": {
        "caption_x": 0.31,
        "caption_y": 0.44,
        "caption_align": "left",
        "caption_font_size": 68,
    }})
    assert approved.status_code == 200
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        run = client.get(f"/canvas-runs/{run_id}").json()
        if run["status"] in {"SUCCEEDED", "FAILED"}:
            break
        time.sleep(0.03)
    assert run["status"] == "SUCCEEDED"
    assert [payload.node_key for payload in captured] == ["timeline.compose", "video.render"]
    layout_parameters = captured[0].parameters
    assert layout_parameters["caption_x"] == 0.31
    assert layout_parameters["caption_y"] == 0.44
    assert layout_parameters["caption_align"] == "left"
    assert layout_parameters["caption_font_size"] == 68


def test_skill_executor_prompt_flows_to_downstream_generator(client: TestClient):
    uploaded = client.post(
        "/artifacts/upload",
        files={"file": ("reference.png", b"\x89PNG\r\n\x1a\n-skill-reference", "image/png")},
    ).json()
    graph = {
        "canvas_id": "skill_prompt_canvas",
        "name": "Skill prompt flow",
        "nodes": [
            {
                "id": "prompt",
                "data": {
                    "key": "prompt.input", "label": "Prompt", "kind": "input",
                    "executable": False, "configText": "비 오는 밤의 작은 골목",
                    "outputType": "Prompt",
                },
            },
            {
                "id": "skill",
                "data": {
                    "key": "skill.execute", "label": "Skill executor", "kind": "generate",
                    "inputTypes": ["Prompt"], "requiredInputTypes": ["Prompt"],
                    "outputType": "Prompt", "model": "text.quality", "provider": "google",
                    "skillId": "nottalggak-prompt-machine",
                },
            },
            {
                "id": "image1",
                "data": {
                    "key": "asset.select", "label": "Image 1", "kind": "input",
                    "executable": False, "outputType": "Image",
                    "outputArtifactIds": [uploaded["artifact_id"]],
                    "output": {"kind": "image", "title": "reference.png", "url": uploaded["url"], "mimeType": "image/png"},
                },
            },
            {
                "id": "prompt2",
                "data": {
                    "key": "prompt.input", "label": "Prompt 2", "kind": "input",
                    "executable": False, "inputTypes": ["Prompt", "Image"],
                    "requiredInputTypes": [], "multiInputTypes": ["Image"],
                    "outputType": "Prompt", "configText": "",
                },
            },
            {
                "id": "image",
                "data": {
                    "key": "image.generate", "label": "Image generator", "kind": "generate",
                    "inputTypes": ["Prompt"], "requiredInputTypes": ["Prompt"],
                    "outputType": "Image", "model": "image.fast", "provider": "google",
                },
            },
        ],
        "edges": [
            {"id": "prompt-skill", "source": "prompt", "target": "skill", "targetHandle": "input-Prompt-0"},
            {"id": "skill-prompt2", "source": "skill", "target": "prompt2", "targetHandle": "input-Prompt-0"},
            {"id": "image1-prompt2", "source": "image1", "target": "prompt2", "targetHandle": "input-Image-1"},
            {"id": "prompt2-image", "source": "prompt2", "target": "image", "targetHandle": "input-Prompt-0"},
        ],
    }
    response = client.post("/canvas-runs", json=graph)
    assert response.status_code == 201
    run = response.json()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        run = client.get(f"/canvas-runs/{run['id']}").json()
        if run["status"] in {"SUCCEEDED", "FAILED"}:
            break
        time.sleep(0.03)
    assert run["status"] == "SUCCEEDED"

    skill_run = client.get("/experiments", params={"canvas_id": graph["canvas_id"], "node_id": "skill"}).json()[0]
    image_run = client.get("/experiments", params={"canvas_id": graph["canvas_id"], "node_id": "image"}).json()[0]
    assert skill_run["parameters"]["skill_id"] == "nottalggak-prompt-machine"
    assert image_run["prompt"] == skill_run["output"]["text"]
    assert "### 3. Technical / Visual Blueprint" in image_run["prompt"]
    forwarded_artifact_ids = [artifact_id for item in image_run["inputs"] for artifact_id in item["artifact_ids"]]
    assert uploaded["artifact_id"] in forwarded_artifact_ids

    edited_graph = json.loads(json.dumps(graph))
    edited_graph["canvas_id"] = "edited_skill_prompt_canvas"
    next(node for node in edited_graph["nodes"] if node["id"] == "prompt2")["data"]["configText"] = "Manually edited master prompt"
    edited_response = client.post("/canvas-runs", json=edited_graph)
    assert edited_response.status_code == 201
    edited_run = edited_response.json()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        edited_run = client.get(f"/canvas-runs/{edited_run['id']}").json()
        if edited_run["status"] in {"SUCCEEDED", "FAILED"}:
            break
        time.sleep(0.03)
    assert edited_run["status"] == "SUCCEEDED"
    edited_image_run = client.get("/experiments", params={"canvas_id": edited_graph["canvas_id"], "node_id": "image"}).json()[0]
    assert edited_image_run["prompt"] == "Manually edited master prompt"


def test_workspace_summary_unified_runs_and_model_usage_are_persisted(client: TestClient):
    initial = client.get("/workspace/summary")
    assert initial.status_code == 200
    assert initial.json()["runs"] == 0
    assert initial.json()["experiments"] == 0

    experiment = client.post("/experiments", json={
        "canvas_id": "real_data_canvas",
        "node_id": "image_1",
        "node_key": "image.generate",
        "prompt": "Persisted image experiment",
        "model_alias": "image.fast",
        "parameters": {"aspect_ratio": "1:1"},
        "inputs": [],
    })
    assert experiment.status_code == 201
    canvas_run = client.post("/canvas-runs", json={
        "canvas_id": "real_data_canvas",
        "name": "Persisted Canvas Run",
        "nodes": [{
            "id": "prompt",
            "data": {
                "key": "prompt.input",
                "label": "Prompt",
                "kind": "input",
                "executable": False,
                "configText": "Persisted prompt",
                "outputType": "Prompt",
            },
        }],
        "edges": [],
    })
    assert canvas_run.status_code == 201

    summary = client.get("/workspace/summary").json()
    assert summary["runs"] == 1
    assert summary["canvas_runs"] == 1
    assert summary["experiments"] == 1
    assert summary["images"] == 1
    assert summary["artifacts"] >= 1

    runs = client.get("/workflow-runs").json()
    assert len(runs) == 1
    assert runs[0]["run_type"] == "canvas"
    assert runs[0]["name"] == "Persisted Canvas Run"
    models = client.get("/models").json()
    selectable_text_models = {
        model["logical_alias"]: model["exact_model_id"]
        for model in models
        if model["logical_alias"].startswith("google.text.3")
    }
    assert selectable_text_models == {
        "google.text.3.6-flash": "gemini-3.6-flash",
        "google.text.3.5-flash": "gemini-3.5-flash",
        "google.text.3.5-flash-lite": "gemini-3.5-flash-lite",
        "google.text.3.1-pro-preview": "gemini-3.1-pro-preview",
        "google.text.3.1-flash-lite": "gemini-3.1-flash-lite",
    }
    image_model = next(model for model in models if model["logical_alias"] == "google.image.fast")
    assert image_model["usage_count"] == 1
    assert image_model["last_used_at"] is not None
    assert image_model["configuration"]


def test_lora_image_generator_experiment_uses_fal_model_contract(client: TestClient):
    response = client.post("/experiments", json={
        "canvas_id": "lora_canvas",
        "node_id": "lora_image",
        "node_key": "lora.image.generate",
        "prompt": "mori walking through a rainy city",
        "model_alias": "fal.image.flux2-lora",
        "parameters": {
            "provider": "fal",
            "lora_url": "https://weights.example/mori.safetensors",
            "lora_scale": 0.9,
            "trigger_word": "mori_catgirl_v1",
            "aspect_ratio": "9:16",
        },
        "inputs": [],
    })
    assert response.status_code == 201
    result = response.json()
    assert result["status"] == "SUCCEEDED"
    assert result["model_alias"] == "fal.image.flux2-lora"
    assert result["exact_model_id"] == "fal-ai/flux-2/lora"
    assert result["output"]["kind"] == "image"
    model = next(item for item in client.get("/models").json() if item["logical_alias"] == "fal.image.flux2-lora")
    assert model["provider"] == "fal.ai"
    assert model["exact_model_id"] == "fal-ai/flux-2/lora"


def test_character_lora_training_persists_weights_and_hydrates_lora_generator(client: TestClient, monkeypatch):
    character_experiment = client.post("/experiments", json={
        "canvas_id": "character_training_canvas",
        "node_id": "character",
        "node_key": "character.generate",
        "prompt": "Black-haired anime cat-eared athlete",
        "model_alias": "image.fast",
        "parameters": {"character_name": "Mori", "shot_count": 4, "aspect_ratio": "9:16"},
        "inputs": [],
    }).json()
    character_id = character_experiment["output_artifact_ids"][0]

    class FakeTrainingService:
        def submit_lora_training(self, **kwargs):
            assert kwargs["image_data_url"].startswith("https://r2.test/")
            assert kwargs["trigger_word"] == "mori_catgirl_v1"
            return {
                "request_id": "fal_train_1",
                "status_url": "https://fal.test/status/fal_train_1",
                "response_url": "https://fal.test/result/fal_train_1",
                "status": "IN_QUEUE",
            }

        def get_queue_status(self, status_url):
            assert status_url.endswith("fal_train_1")
            return {"status": "COMPLETED"}

        def get_queue_result(self, response_url):
            assert response_url.endswith("fal_train_1")
            return {
                "diffusers_lora_file": {"url": "https://weights.fal.test/mori.safetensors"},
                "config_file": {"url": "https://weights.fal.test/mori-config.json"},
            }

    class FakeDatasetStore:
        def put_archive(self, **kwargs):
            assert kwargs["character_id"] == character_id
            assert kwargs["archive"].startswith(b"PK")
            return type("Dataset", (), {
                "bucket": "frameflow-lora-training",
                "key": "lora-training/character.zip",
                "uri": "r2://frameflow-lora-training/lora-training/character.zip",
                "sha256": "dataset-sha",
                "size_bytes": len(kwargs["archive"]),
                "download_url": "https://r2.test/character.zip?X-Amz-Signature=test",
                "expires_at": "2026-08-31T02:00:00+00:00",
            })()

    monkeypatch.setattr("app.main.get_fal_generation_services", lambda: FakeTrainingService())
    monkeypatch.setattr("app.main.get_r2_training_dataset_store", lambda: FakeDatasetStore())
    monkeypatch.setattr("app.character_lora.build_captioned_lora_archive", lambda images, trigger_word: b"PK-test-archive")
    submitted = client.post(f"/characters/{character_id}/lora-training", json={
        "trigger_word": "mori_catgirl_v1",
        "steps": 1000,
    })
    assert submitted.status_code == 202
    assert submitted.json()["status"] == "IN_QUEUE"

    completed = client.get(f"/characters/{character_id}/lora-training")
    assert completed.status_code == 200
    assert completed.json()["status"] == "READY"
    assert completed.json()["weights_url"] == "https://weights.fal.test/mori.safetensors"
    listed = next(item for item in client.get("/characters").json() if item["id"] == character_id)
    assert listed["lora"]["status"] == "READY"
    assert listed["lora"]["trigger_word"] == "mori_catgirl_v1"

    generated = client.post("/experiments", json={
        "canvas_id": "character_training_canvas",
        "node_id": "lora_image",
        "node_key": "lora.image.generate",
        "prompt": "working at a cafe",
        "model_alias": "fal.image.flux2-lora",
        "parameters": {"provider": "fal", "aspect_ratio": "9:16"},
        "inputs": [{"type": "Character", "artifact_ids": [character_id]}],
    })
    assert generated.status_code == 201
    assert generated.json()["status"] == "SUCCEEDED"
    assert generated.json()["parameters"]["lora_url"] == "https://weights.fal.test/mori.safetensors"
    assert generated.json()["parameters"]["trigger_word"] == "mori_catgirl_v1"


def test_image_connected_through_prompt_reaches_image_generator(client: TestClient):
    uploaded = client.post(
        "/artifacts/upload",
        files={"file": ("source.png", b"\x89PNG\r\n\x1a\n", "image/png")},
    ).json()
    uploaded_second = client.post(
        "/artifacts/upload",
        files={"file": ("source-two.png", b"\x89PNG\r\n\x1a\n-second", "image/png")},
    ).json()
    graph = {
        "canvas_id": "canvas_prompt_image",
        "name": "Prompt image pass-through",
        "nodes": [
            {
                "id": "source_image",
                "data": {
                    "key": "asset.select", "label": "Assets", "kind": "input",
                    "executable": False, "outputType": "Image",
                    "outputArtifactIds": [uploaded["artifact_id"]],
                    "output": {"kind": "image", "title": "source.png", "url": uploaded["url"], "mimeType": "image/png"},
                },
            },
            {
                "id": "edit_prompt",
                "data": {
                    "key": "prompt.input", "label": "Prompt", "kind": "input",
                    "executable": False, "inputTypes": ["Image"], "requiredInputTypes": [],
                    "outputType": "Prompt", "configText": "Use {{image:source_image}} for the subject and {{image:source_image_two}} for the background",
                },
            },
            {
                "id": "source_image_two",
                "data": {
                    "key": "asset.select", "label": "Assets 2", "kind": "input",
                    "executable": False, "outputType": "Image",
                    "outputArtifactIds": [uploaded_second["artifact_id"]],
                    "output": {"kind": "image", "title": "source-two.png", "url": uploaded_second["url"], "mimeType": "image/png"},
                },
            },
            {
                "id": "image_generator",
                "data": {
                    "key": "image.generate", "label": "Image generator", "kind": "generate",
                    "inputTypes": ["Prompt"], "requiredInputTypes": ["Prompt"],
                    "outputType": "Image", "model": "image.fast", "provider": "google",
                },
            },
        ],
        "edges": [
            {"id": "source-to-prompt", "source": "source_image", "target": "edit_prompt", "targetHandle": "input-Image-0"},
            {"id": "source-two-to-prompt", "source": "source_image_two", "target": "edit_prompt", "targetHandle": "input-Image-0"},
            {"id": "prompt-to-generator", "source": "edit_prompt", "target": "image_generator", "targetHandle": "input-Prompt-0"},
        ],
    }
    response = client.post("/canvas-runs", json=graph)
    assert response.status_code == 201
    run = response.json()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        run = client.get(f"/canvas-runs/{run['id']}").json()
        if run["status"] in {"SUCCEEDED", "FAILED"}:
            break
        time.sleep(0.03)
    assert run["status"] == "SUCCEEDED"
    experiments = client.get("/experiments", params={"canvas_id": graph["canvas_id"], "node_id": "image_generator"}).json()
    assert "Image 1" in experiments[0]["prompt"]
    assert "Image 2" in experiments[0]["prompt"]
    assert "{{image:" not in experiments[0]["prompt"]
    forwarded_artifact_ids = [artifact_id for item in experiments[0]["inputs"] for artifact_id in item["artifact_ids"]]
    assert uploaded["artifact_id"] in forwarded_artifact_ids
    assert uploaded_second["artifact_id"] in forwarded_artifact_ids


def test_character_generator_persists_bundle_and_flows_with_reference_video(client: TestClient):
    motion = render_video_mp4("abc123def4567890abc123def4567890abc123def4567890abc123def4567890")
    uploaded_motion = client.post(
        "/artifacts/upload",
        files={"file": ("motion.mp4", motion, "video/mp4")},
    ).json()
    graph = {
        "canvas_id": "character_bundle_canvas",
        "name": "Character bundle to video",
        "nodes": [
            {
                "id": "character_prompt",
                "data": {
                    "key": "prompt.input", "label": "Character synopsis", "kind": "input",
                    "executable": False, "configText": "Black-haired anime cat-eared athlete with amber eyes",
                    "outputType": "Prompt",
                },
            },
            {
                "id": "character",
                "data": {
                    "key": "character.generate", "label": "Character generator", "kind": "generate",
                    "inputTypes": ["Prompt", "Image"], "requiredInputTypes": ["Prompt"],
                    "multiInputTypes": ["Image"], "outputType": "Character", "model": "image.fast", "provider": "google",
                    "characterName": "Mori", "shotCount": 4, "aspectRatio": "9:16", "resolution": "2K",
                },
            },
            {
                "id": "motion_prompt",
                "data": {
                    "key": "prompt.input", "label": "Motion prompt", "kind": "input",
                    "executable": False, "configText": "She copies the warm-up motion and waves at the camera",
                    "outputType": "Prompt",
                },
            },
            {
                "id": "motion_video",
                "data": {
                    "key": "asset.select", "label": "Reference motion", "kind": "input",
                    "executable": False, "outputType": "Video", "outputArtifactIds": [uploaded_motion["artifact_id"]],
                    "output": {"kind": "video", "title": "motion.mp4", "url": uploaded_motion["url"], "mimeType": "video/mp4"},
                },
            },
            {
                "id": "video",
                "data": {
                    "key": "video.generate", "label": "Video generator", "kind": "generate",
                    "inputTypes": ["Prompt", "Character", "Video"], "requiredInputTypes": ["Prompt"],
                    "outputType": "Video", "model": "video.omni", "provider": "google", "aspectRatio": "9:16", "resolution": "1080p",
                },
            },
        ],
        "edges": [
            {"id": "prompt-character", "source": "character_prompt", "target": "character", "targetHandle": "input-Prompt-0"},
            {"id": "motion-prompt-video", "source": "motion_prompt", "target": "video", "targetHandle": "input-Prompt-0"},
            {"id": "character-video", "source": "character", "target": "video", "targetHandle": "input-Character-1"},
            {"id": "motion-video", "source": "motion_video", "target": "video", "targetHandle": "input-Video-2"},
        ],
    }
    response = client.post("/canvas-runs", json=graph)
    assert response.status_code == 201
    run = response.json()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        run = client.get(f"/canvas-runs/{run['id']}").json()
        if run["status"] in {"SUCCEEDED", "FAILED"}:
            break
        time.sleep(0.03)
    assert run["status"] == "SUCCEEDED"

    character_run = next(item for item in run["node_runs"] if item["canvas_node_id"] == "character")
    character_id = character_run["output_artifact_ids"][0]
    character_artifact = client.get(f"/artifacts/{character_id}").json()
    assert character_artifact["type"] == "Character"
    assert character_artifact["schema_id"] == "character.bundle.v1"
    assert character_artifact["metadata"]["name"] == "Mori"
    assert len(character_artifact["metadata"]["image_artifact_ids"]) == 4

    characters = client.get("/characters").json()
    assert len(characters) == 1
    assert characters[0]["id"] == character_id
    assert characters[0]["image_count"] == 4
    assert characters[0]["images"][0]["role"] == "baseline"
    assert client.get("/workspace/summary").json()["characters"] == 1

    video_experiment = client.get("/experiments", params={"canvas_id": graph["canvas_id"], "node_id": "video"}).json()[0]
    input_types = {item["type"] for item in video_experiment["inputs"]}
    assert {"Prompt", "Character", "Video"}.issubset(input_types)
    forwarded = [artifact_id for item in video_experiment["inputs"] for artifact_id in item["artifact_ids"]]
    assert character_id in forwarded
    assert uploaded_motion["artifact_id"] in forwarded


def test_character_generator_accepts_image_without_prompt_and_records_canonical_reference(client: TestClient):
    uploaded = client.post(
        "/artifacts/upload",
        files={"file": ("canonical.png", b"\x89PNG\r\n\x1a\n-character-canonical", "image/png")},
    ).json()
    graph = {
        "canvas_id": "image_only_character_canvas",
        "name": "Image-only character",
        "nodes": [
            {
                "id": "image",
                "data": {
                    "key": "asset.select", "label": "Canonical image", "kind": "input", "executable": False,
                    "outputType": "Image", "outputArtifactIds": [uploaded["artifact_id"]],
                    "output": {"kind": "image", "title": "canonical.png", "url": uploaded["url"], "mimeType": "image/png"},
                },
            },
            {
                "id": "character",
                "data": {
                    "key": "character.generate", "label": "Character generator", "kind": "generate",
                    "inputTypes": ["Prompt", "Image"], "requiredInputTypes": [], "multiInputTypes": ["Image"],
                    "outputType": "Character", "model": "image.fast", "provider": "google",
                    "characterName": "Image Anchor", "shotCount": 4, "aspectRatio": "9:16",
                },
            },
        ],
        "edges": [
            {"id": "image-character", "source": "image", "target": "character", "targetHandle": "input-Image-1"},
        ],
    }
    response = client.post("/canvas-runs", json=graph)
    assert response.status_code == 201
    run = response.json()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        run = client.get(f"/canvas-runs/{run['id']}").json()
        if run["status"] in {"SUCCEEDED", "FAILED"}:
            break
        time.sleep(0.03)
    assert run["status"] == "SUCCEEDED"
    character_run = next(item for item in run["node_runs"] if item["canvas_node_id"] == "character")
    character = client.get(f"/artifacts/{character_run['output_artifact_ids'][0]}").json()
    assert character["metadata"]["reference_image_artifact_ids"] == [uploaded["artifact_id"]]
    assert len(character["metadata"]["image_artifact_ids"]) == 4


def test_canvas_documents_list_save_open_and_track_latest_run(client: TestClient):
    created = client.post("/canvases", json={"name": "Saved Canvas", "nodes": [], "edges": []})
    assert created.status_code == 201
    canvas = created.json()
    assert canvas["node_count"] == 0
    assert client.get("/workspace/summary").json()["canvases"] == 1

    saved = client.put(f"/canvases/{canvas['id']}", json={
        "name": "Saved Canvas v2",
        "nodes": [{
            "id": "prompt",
            "data": {
                "key": "prompt.input",
                "label": "Actual Prompt",
                "kind": "input",
                "executable": False,
                "configText": "Persist this graph",
                "outputType": "Prompt",
            },
        }],
        "edges": [],
    })
    assert saved.status_code == 200
    assert saved.json()["name"] == "Saved Canvas v2"
    assert saved.json()["node_count"] == 1
    listed = client.get("/canvases").json()
    assert [item["id"] for item in listed] == [canvas["id"]]

    run = client.post("/canvas-runs", json={
        "canvas_id": canvas["id"],
        "name": "Saved Canvas run",
        "nodes": saved.json()["nodes"],
        "edges": [],
    })
    assert run.status_code == 201
    opened = client.get(f"/canvases/{canvas['id']}").json()
    assert opened["active_run_id"] == run.json()["id"]
    assert opened["last_run"]["id"] == run.json()["id"]

    deleted = client.delete(f"/canvases/{canvas['id']}")
    assert deleted.status_code == 204
    assert client.get("/canvases").json() == []
