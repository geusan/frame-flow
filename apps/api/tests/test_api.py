from fastapi.testclient import TestClient
import json
import threading
import time
from types import SimpleNamespace

from app.experiments import FIXTURE_EXECUTOR_REVISION
from app.media_preview import render_audio_wav
from app.providers_localization import (
    LocalizationServices,
    SpeechSegment,
    SynthesizedSpeech,
    TranscriptResult,
    TranslationResult,
)
from app.providers_generation import LiveGenerationResult


def test_executor_revision_fits_persisted_execution_mode():
    assert len(FIXTURE_EXECUTOR_REVISION) <= 32


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


def test_frame_extract_canvas_operation_preserves_timestamp_and_lineage(client: TestClient):
    imported = client.post(
        "/artifacts/import-url",
        json={"url": "https://youtube.com/watch?v=frame-node"},
    ).json()
    response = client.post("/experiments", json={
        "canvas_id": "canvas_frame_extract",
        "node_id": "frame_extract_1",
        "node_key": "video.frame_extract",
        "prompt": "",
        "model_alias": "local.ffmpeg",
        "parameters": {"frame_timestamp_ms": 400},
        "inputs": [{
            "node_id": "video_source",
            "type": "Video",
            "artifact_ids": [imported["artifact_id"]],
        }],
    })

    assert response.status_code == 201
    experiment = response.json()
    assert experiment["status"] == "SUCCEEDED"
    assert experiment["output"]["kind"] == "image"
    assert "0.400s" in experiment["output"]["title"]
    artifact_id = experiment["output_artifact_ids"][0]
    artifact = client.get(f"/artifacts/{artifact_id}").json()
    assert artifact["input_artifact_ids"] == [imported["artifact_id"]]
    assert artifact["metadata"]["capture"]["timestamp_ms"] == 400
    lineage = client.get(f"/artifacts/{artifact_id}/lineage").json()
    edge = lineage["edges"][0]
    assert edge["role"] == "source_video"
    extracted_node = next(node for node in lineage["nodes"] if node["id"] == artifact_id)
    assert extracted_node["derivation"]["operation"] == "video.frame_extract"


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
    assert search["exact_model_id"] == "gemini-2.5-pro"
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
    )
    assert '"version": "timeline.v1"' in timeline["output"]["text"]

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
