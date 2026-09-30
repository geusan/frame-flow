import asyncio
import json
import subprocess
from types import SimpleNamespace

import httpx
import pytest

from app import canvas_activities
from app.canvas_documents import canonicalize_canvas_document
from app.canvas_runs import create_canvas_run, execute_canvas_node
from app.database import SessionLocal, ExperimentRunRecord
from app.domain import CanvasRunRequest, ExperimentRunRequest
from app.experiments import request_fingerprint, resolve_model
from app.infrastructure.node_execution.provider_tasks import SqlAlchemyNodeProviderTasks
from app.media_preview import render_audio_wav, render_video_mp4
from app.nodes import node_registry
from app.nodes.contracts import ProviderTaskStateError
from app.providers_performance import FalPerformanceService, ElevenLabsVoiceService, ProviderMedia, MediaProviderError
from app.nodes.executors.reference_captions import reference_tracks_ass


def test_fal_normalized_request_and_resume_do_not_resubmit():
    calls, remembered = [], []
    def handler(request):
        calls.append((request.method, str(request.url)))
        if request.url.host == "rest.alpha.fal.ai":
            body = json.loads(request.content)
            name = body["file_name"]
            assert request.headers["authorization"] == "Key test"
            return httpx.Response(200, json={"upload_url": f"https://v3.fal.media/upload/{name}", "file_url": f"https://v3.fal.media/files/{name}"})
        if request.method == "PUT":
            assert "authorization" not in request.headers
            return httpx.Response(200)
        if request.method == "POST":
            body = json.loads(request.content)
            assert body == {"image_url": "https://v3.fal.media/files/character.png", "video_url": "https://v3.fal.media/files/driving.mp4", "prompt": "Act", "character_orientation": "video", "keep_original_sound": False}
            assert request.headers["authorization"] == "Key test"
            return httpx.Response(200, json={"request_id": "req_1"})
        if request.url.path.endswith("/status"):
            return httpx.Response(200, json={"status": "COMPLETED"})
        if request.url.host == "queue.fal.run":
            return httpx.Response(200, json={"video": {"url": "https://v3.fal.media/result.mp4"}})
        assert "authorization" not in request.headers
        return httpx.Response(200, content=b"video-output")
    service = FalPerformanceService(api_key="test", client=httpx.Client(transport=httpx.MockTransport(handler)), poll_interval=0)
    kwargs = dict(image=b"image", image_content_type="image/png", video=b"video", prompt="Act", orientation="video", timeout_seconds=30, remember=remembered.append, progress=lambda *_: None)
    result = service.transfer(**kwargs, resume_id=None)
    assert result.content == b"video-output" and remembered == ["req_1"]
    calls.clear()
    assert service.transfer(**kwargs, resume_id="req_1").request_id == "req_1"
    assert all(method == "GET" for method, _ in calls)


def test_fal_ambiguous_submission_is_nonretryable(monkeypatch):
    service = FalPerformanceService(api_key="test", client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503))))
    monkeypatch.setattr(service, "_upload", lambda *args: "https://v3.fal.media/file")
    with pytest.raises(MediaProviderError) as error:
        service.transfer(image=b"i", image_content_type="image/png", video=b"v", prompt="", orientation="video", timeout_seconds=30, resume_id=None, remember=lambda _: None, progress=lambda *_: None)
    assert error.value.retryable is False


def test_fal_exhausted_balance_is_actionable_and_not_retried(monkeypatch):
    remembered = []
    service = FalPerformanceService(api_key="test", client=httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(403, json={"detail": "User is locked. Reason: Exhausted balance."}))))
    monkeypatch.setattr(service, "_upload", lambda *args: "https://v3.fal.media/file")
    with pytest.raises(MediaProviderError, match="fal balance is exhausted") as error:
        service.transfer(image=b"i", image_content_type="image/png", video=b"v", prompt="", orientation="video", timeout_seconds=30, resume_id=None, remember=remembered.append, progress=lambda *_: None)
    assert error.value.retryable is False and error.value.rejected is True
    assert remembered == ["rejected"]


def test_fal_result_validation_failure_does_not_echo_input_or_retry():
    remembered = []
    def handler(request):
        if request.url.path.endswith("/status"): return httpx.Response(200, json={"status": "COMPLETED"})
        return httpx.Response(422, json={"detail": [{"msg": "Video URL is invalid", "input": {"video_url": "private-input"}}]})
    service = FalPerformanceService(api_key="test", client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(MediaProviderError, match="Video URL is invalid") as error:
        service.transfer(image=b"i", image_content_type="image/png", video=b"v", prompt="", orientation="video", timeout_seconds=30, resume_id="existing-task", remember=remembered.append, progress=lambda *_: None)
    assert error.value.retryable is False and "private-input" not in str(error.value)
    assert remembered == ["rejected"]


def test_elevenlabs_uses_requested_voice_and_multilingual_sts():
    def handler(request):
        assert request.headers["xi-api-key"] == "test"
        if request.method == "GET": return httpx.Response(200, json={"voice_id": "requested_voice"})
        assert request.url.path == "/v1/speech-to-speech/requested_voice"
        assert request.url.params["output_format"] == "mp3_44100_128"
        assert b"eleven_multilingual_sts_v2" in request.content
        assert b"similarity_boost" in request.content and b"source.wav" in request.content
        return httpx.Response(200, content=b"audio-output", headers={"request-id": "req_voice", "character-cost": "100"})
    service = ElevenLabsVoiceService(api_key="test", client=httpx.Client(transport=httpx.MockTransport(handler)))
    service.validate_voice("requested_voice")
    result = service.convert(audio=b"source", voice_id="requested_voice", stability=0.5, similarity=0.9, seed=0, remove_noise=True)
    assert result.request_id == "req_voice" and result.usage["character_cost"] == "100"


@pytest.fixture(scope="module")
def media():
    video = render_video_mp4("1234567890abcdef", duration_seconds=4)
    wav = render_audio_wav("123456", duration_seconds=4)
    mp3 = subprocess.run(["ffmpeg", "-v", "error", "-i", "pipe:0", "-f", "mp3", "pipe:1"], input=wav, capture_output=True, check=True).stdout
    return video, wav, mp3


def test_contracts_defaults_validation_and_request_hash():
    motion = node_registry.get("video.performance_transfer", 1)
    voice = node_registry.get("audio.voice_convert", 1)
    assert motion.editor.kind == voice.editor.kind == "generic"
    assert node_registry.resolve_config(motion, {})["character_orientation"] == "video"
    assert node_registry.resolve_config(voice, {})["voice_id"] == "JBFqnCBsd6RMkjVDRZzb"
    with pytest.raises(ValueError): node_registry.resolve_config(voice, {"voice_id": "has/slash"})
    with pytest.raises(ValueError): node_registry.resolve_config(motion, {"character_orientation": "unknown"})
    p = ExperimentRunRequest(canvas_id="c", node_id="n", node_key="audio.voice_convert", model_alias="elevenlabs.audio.voice_change", parameters={"voice_id": "voice_a"})
    model, exact = resolve_model(p.model_alias, p.node_key)
    assert exact == "eleven_multilingual_sts_v2"
    changed = p.model_copy(update={"parameters": {"voice_id": "voice_b"}})
    assert request_fingerprint(p, model, exact) != request_fingerprint(changed, model, exact)


def test_performance_workflow_publish_freezes_contracts_and_prunes_unused_branch(client, media):
    def upload(name, data, mime):
        return client.post("/artifacts/upload", files={"file": (name, data, mime)}).json()["artifact_id"]
    image_id = upload("identity.png", b"image", "image/png")
    video_id = upload("reference.mp4", media[0], "video/mp4")
    nodes = []
    def node(ident, key, version=1, config=None):
        d = node_registry.get(key, version)
        data = {"key": key, "contractVersion": version, "model": d.execution.model_alias, "config": config or {}}
        if key == "asset.select": data["outputArtifactIds"] = [config["artifact_id"]]
        nodes.append({"id": ident, "data": data})
    node("image", "asset.select", 2, {"artifact_id": image_id, "artifact_type": "Image"})
    node("video", "asset.select", 2, {"artifact_id": video_id, "artifact_type": "Video"})
    node("analysis", "reference.decompose", 2)
    node("motion", "video.performance_transfer")
    node("extract", "audio.extract")
    node("voice", "audio.voice_convert", config={"voice_id": "requested_voice"})
    node("captions", "video.reference_captions")
    node("final", "video.change_voice")
    node("unused", "audio.voice_convert")
    nodes.append({"id": "note", "data": {"key": "utility.sticky", "configText": "Keep character proportions"}})
    edge_specs = [("image", "motion", "artifact", "image"), ("video", "motion", "artifact", "video"),
                  ("video", "analysis", "artifact", "video"), ("video", "extract", "artifact", "video"),
                  ("extract", "voice", "audio", "audio"), ("motion", "captions", "video", "video"),
                  ("analysis", "captions", "analysis", "analysis"), ("captions", "final", "video", "video"),
                  ("voice", "final", "audio", "audio")]
    edges = [{"id": f"e{i}", "source": s, "target": t, "sourceHandle": sp, "targetHandle": tp} for i, (s,t,sp,tp) in enumerate(edge_specs)]
    workflow = client.post("/workflows", json={"name": "Performance transfer"}).json()
    canvas = client.get("/canvases/" + workflow["draft_canvas_id"]).json()
    contract = {"schema_version": "workflow.contract.draft.v1", "inputs": [], "bindings": [], "outputs": [
        {"key": "video", "label": "Final video", "node_id": "final", "port_key": "video", "port_type": "media.video.v1", "primary": True}]}
    saved = client.put("/canvases/" + canvas["id"], json={"name": canvas["name"], "document": canonicalize_canvas_document(nodes, edges),
        "expected_revision": canvas["revision"], "draft_contract": contract})
    assert saved.status_code == 200, saved.text
    response = client.post(f"/workflows/{workflow['id']}/publish", json={"expected_canvas_revision": saved.json()["revision"]})
    assert response.status_code == 201, response.text
    version = response.json()
    assert {n["id"] for n in version["graph"]["nodes"]} == {"image", "video", "analysis", "motion", "extract", "voice", "captions", "final"}
    assert version["warnings"] == ["Unused Canvas Node excluded: unused"]
    for n in version["graph"]["nodes"]:
        assert n["definition_digest"] == node_registry.get(n["type_key"], n["contract_version"]).definition_digest
    annotations = client.get(f"/workflows/{workflow['id']}/versions/1/annotations").json()
    assert len(annotations) == 1 and annotations[0]["body"] == "Keep character proportions"


@pytest.mark.parametrize("temporal", [False, True])
@pytest.mark.parametrize("kind", ["motion", "voice"])
def test_registry_local_temporal_artifacts_lineage_and_checkpoints(client, monkeypatch, media, temporal, kind):
    video, wav, mp3 = media
    monkeypatch.setattr(canvas_activities, "refresh_provider_environment", lambda: None)
    monkeypatch.setattr(canvas_activities.activity, "heartbeat", lambda *_: None)
    submissions = []
    class Motion:
        def transfer(self, **kwargs):
            submissions.append("motion")
            assert kwargs["orientation"] == "video"
            kwargs["remember"]("task_test")
            return ProviderMedia(video, "video/mp4", "task_test", {})
        def close(self): pass
    class Voice:
        def validate_voice(self, voice_id): assert voice_id == "requested_voice"
        def convert(self, **kwargs):
            submissions.append("voice")
            return ProviderMedia(mp3, "audio/mpeg", "voice_test", {})
        def close(self): pass
    monkeypatch.setattr("app.nodes.executors.performance_transfer.FalPerformanceService", Motion)
    monkeypatch.setattr("app.nodes.executors.performance_transfer.ElevenLabsVoiceService", Voice)
    def upload(name, data, mime):
        response = client.post("/artifacts/upload", files={"file": (name, data, mime)})
        assert response.status_code == 201, response.text
        return response.json()["artifact_id"]
    if kind == "motion":
        refs = [(upload("identity.png", b"image", "image/png"), "Image", "image"), (upload("drive.mp4", video, "video/mp4"), "Video", "video")]
        key, model, config, output_type, schema = "video.performance_transfer", "fal.video.performance", {}, "Video", "video.performance_transferred.v1"
    else:
        refs = [(upload("speech.wav", wav, "audio/wav"), "Audio", "audio")]
        key, model, config, output_type, schema = "audio.voice_convert", "elevenlabs.audio.voice_change", {"voice_id": "requested_voice"}, "Audio", "audio.voice_converted.v1"
    nodes = [{"id": f"source-{i}", "data": {"key": "asset.select", "contractVersion": 2, "config": {"artifact_id": aid, "artifact_type": typ}, "outputArtifactIds": [aid]}} for i, (aid, typ, _) in enumerate(refs)]
    nodes.append({"id": "target", "data": {"key": key, "contractVersion": 1, "model": model, "provider": model.split('.')[0], "config": config}})
    edges = [{"id": f"edge-{i}", "source": f"source-{i}", "target": "target", "sourceHandle": "artifact", "targetHandle": port} for i, (_, _, port) in enumerate(refs)]
    saved = client.post("/canvases", json={"name": "performance", "document": canonicalize_canvas_document(nodes, edges)}).json()
    with SessionLocal() as db:
        run = create_canvas_run(db, CanvasRunRequest(canvas_id=saved["id"], canvas_revision=saved["revision"], target_node_id="target"))
        run_id = run.id
    result = asyncio.run(canvas_activities.execute_canvas_node_activity(run_id, "target")) if temporal else execute_canvas_node(run_id, "target")
    artifact = client.get(f"/artifacts/{result['artifact_ids'][0]}").json()
    assert artifact["type"] == output_type and artifact["schema_id"] == schema
    assert artifact["input_artifact_ids"] == [aid for aid, _, _ in refs]
    assert artifact["metadata"]["normalized_config"] == node_registry.resolve_config(node_registry.get(key, 1), config)
    assert "+ffmpeg:" in artifact["metadata"]["execution_mode"]
    assert artifact["metadata"]["definition_digest"] == node_registry.get(key, 1).definition_digest
    assert len(submissions) == 1
    # Cached retries use the same successful Artifact, never a second billable request.
    result2 = execute_canvas_node(run_id, "target")
    assert result2["artifact_ids"] == result["artifact_ids"] and len(submissions) == 1


@pytest.mark.parametrize("temporal", [False, True])
def test_typed_asset_port_feeds_existing_audio_extract(client, monkeypatch, media, temporal):
    video, _, _ = media
    monkeypatch.setattr(canvas_activities, "refresh_provider_environment", lambda: None)
    monkeypatch.setattr(canvas_activities.activity, "heartbeat", lambda *_: None)
    aid = client.post("/artifacts/upload", files={"file": ("source.mp4", video, "video/mp4")}).json()["artifact_id"]
    nodes = [
        {"id": "source", "data": {"key": "asset.select", "contractVersion": 2, "config": {"artifact_id": aid, "artifact_type": "Video"}, "outputArtifactIds": [aid]}},
        {"id": "extract", "data": {"key": "audio.extract", "contractVersion": 1, "model": "local.audio-extract", "config": {}}},
    ]
    edges = [{"id": "source-extract", "source": "source", "target": "extract", "sourceHandle": "artifact", "targetHandle": "video"}]
    saved = client.post("/canvases", json={"name": "typed extraction", "document": canonicalize_canvas_document(nodes, edges)}).json()
    with SessionLocal() as db:
        run = create_canvas_run(db, CanvasRunRequest(canvas_id=saved["id"], canvas_revision=saved["revision"], target_node_id="extract"))
        run_id = run.id
    result = asyncio.run(canvas_activities.execute_canvas_node_activity(run_id, "extract")) if temporal else execute_canvas_node(run_id, "extract")
    artifact = client.get("/artifacts/" + result["artifact_ids"][0]).json()
    assert artifact["type"] == "Audio" and artifact["schema_id"] == "audio.extracted.v1"
    assert artifact["input_artifact_ids"] == [aid]
    assert artifact["metadata"]["stream_copy"] is True


def test_pending_provider_submission_is_not_blindly_retried(client):
    with SessionLocal() as db:
        record = ExperimentRunRecord(id="exp_pending", canvas_id="c", node_id="n", node_key="video.performance_transfer", prompt="", model_alias="fal.video.performance", exact_model_id="model", execution_mode="test", status="RUNNING", parameters={}, input_snapshot=[], request_hash="a" * 64, output_artifact_ids=[], output_payload={})
        db.add(record); db.commit()
        tasks = SqlAlchemyNodeProviderTasks(db, record.id, record.request_hash)
        assert tasks.claim("fal", "performance", resumable=True) is None
        with pytest.raises(ProviderTaskStateError): tasks.claim("fal", "performance", resumable=True)
        tasks.remember("fal", "performance", "known_task")
        assert tasks.claim("fal", "performance", resumable=True) == "known_task"


def test_reference_caption_timing_positions_colors_and_safe_text():
    definition = node_registry.get("video.reference_captions", 1)
    config = node_registry.resolve_config(definition, {
        "text_overrides": {"jp": "おとうさん"},
        "timing_overrides": {"jp": {"start_ms": 550, "end_ms": 5000}},
        "accent_track_ids": ["roman"], "boxed_track_ids": ["anchor"],
        "callout_anchor_id": "anchor", "callout_target_ids": ["jp"],
    })
    def track(ident, text, x, y):
        return {"track_id": ident, "text": text, "start_ms": 0, "end_ms": 4000,
                "positions": [{"timestamp_ms": 0, "bbox": {"x": x, "y": y, "width": .3, "height": .08}}]}
    analysis = {"schema_version": "reference.decomposition.v1", "visual": {"text_tracks": [
        track("anchor", "Dad", .05, .6), track("roman", "otousan", .55, .1), track("jp", "wrong", .55, .2),
        track("escaped", "{\\pos(0,0)}\rNew line", .1, .8),
    ]}}
    ass, tracks = reference_tracks_ass(analysis, config, 720, 1280, 3000)
    jp = next(t for t in tracks if t['id'] == 'jp')
    assert (jp['x'], jp['y'], jp['start_ms'], jp['end_ms']) == (396,256,550,3000)
    assert "おとうさん" in ass and "wrong" not in ass
    assert "&H00808DF2" in ass and "Dialogue: 0" in ass and "Dialogue: 1" in ass
    assert "\\NNew line" in ass and "{\\pos(0,0)}" not in ass


def test_reference_caption_executor_renders_and_preserves_audio(client, media):
    from app.service import create_artifact
    video, _, _ = media
    source_id = client.post('/artifacts/upload', files={'file': ('ref.mp4', video, 'video/mp4')}).json()['artifact_id']
    analysis = {'schema_version':'reference.decomposition.v1','visual':{'text_tracks':[
        {'track_id':'title','text':'Japanese is','start_ms':0,'end_ms':3000,'positions':[{'timestamp_ms':0,'bbox':{'x':.2,'y':.1,'width':.6,'height':.1}}]}
    ]}}
    with SessionLocal() as db:
        artifact = create_artifact(db,'ReferenceAnalysis',schema_id='reference.decomposition.v1',content=json.dumps(analysis).encode(),content_type='application/json',filename='analysis.json',metadata={})
        db.commit();analysis_id=artifact.id
    result=client.post('/experiments',json={'canvas_id':'captions','node_id':'burn','node_key':'video.reference_captions','model_alias':'local.reference-captions','inputs':[{'type':'Video','artifact_ids':[source_id]},{'type':'ReferenceAnalysis','artifact_ids':[analysis_id]}]})
    assert result.status_code==201,result.text
    data=result.json();assert data['status']=='SUCCEEDED',data.get('error')
    output=client.get('/artifacts/'+data['output_artifact_ids'][0]).json()
    assert output['schema_id']=='video.reference_captioned.v1'
    assert output['metadata']['text_tracks'][0]['text']=='Japanese is'
    assert output['input_artifact_ids']==[source_id,analysis_id]
