import asyncio
import io
import json
import subprocess
from types import SimpleNamespace

import pytest
from PIL import Image

from app import canvas_activities
from app.canvas_documents import canonicalize_canvas_document
from app.canvas_runs import create_canvas_run, execute_canvas_node
from app.database import SessionLocal
from app.domain import CanvasRunRequest, ExperimentRunRequest
from app.experiments import request_fingerprint, resolve_model
from app.nodes import node_registry
from app.providers_generation import GoogleGenerationServices, InputMedia
from app.providers_google import GeneratedBinary, GoogleProviderConfig, GoogleVideoProvider


@pytest.fixture(scope="module")
def clip(tmp_path_factory):
    path = tmp_path_factory.mktemp("frame-test") / "two-colors.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=red:s=160x96:r=10:d=1",
                    "-f", "lavfi", "-i", "color=blue:s=160x96:r=10:d=1", "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v]",
                    "-map", "[v]", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)], check=True)
    return path.read_bytes()


def upload(client, name, data, mime):
    response = client.post("/artifacts/upload", files={"file": (name, data, mime)})
    assert response.status_code == 201, response.text
    return response.json()["artifact_id"]


def image_bytes():
    buffer = io.BytesIO()
    Image.new("RGB", (32, 32), "green").save(buffer, format="PNG")
    return buffer.getvalue()


def test_frame_and_animation_manifests_defaults_ports_and_cache_hash(client):
    frame = node_registry.get("video.frame_extract", 1)
    animate = node_registry.get("video.animate_image", 1)
    assert frame.editor.kind == animate.editor.kind == "generic"
    assert frame.ports.outputs[0].type == animate.ports.inputs[1].type == "media.image.v1"
    assert frame.config_schema['properties']['timestamp_seconds']['x-workflow-input']['enabled']
    assert node_registry.resolve_config(frame, {}) == {"timestamp_seconds": 0}
    with pytest.raises(ValueError): node_registry.resolve_config(frame, {"timestamp_seconds": -1})
    with pytest.raises(ValueError): node_registry.resolve_config(animate, {"aspect_ratio": "1:1"})
    published = client.get("/node-definitions").json()
    assert {"video.frame_extract", "video.animate_image"} <= {d['type_key'] for d in published}
    p = ExperimentRunRequest(canvas_id="c", node_id="f", node_key="video.frame_extract", model_alias="local.frame-extract", parameters={"timestamp_seconds": 0})
    model, exact = resolve_model(p.model_alias, p.node_key)
    assert request_fingerprint(p, model, exact) != request_fingerprint(p.model_copy(update={"parameters": {"timestamp_seconds": 1}}), model, exact)


@pytest.mark.parametrize("temporal", [False, True])
@pytest.mark.parametrize("kind", ["frame", "animate"])
def test_local_temporal_execution_artifacts_and_cached_replay(client, monkeypatch, clip, kind, temporal):
    monkeypatch.setattr(canvas_activities, "refresh_provider_environment", lambda: None)
    monkeypatch.setattr(canvas_activities.activity, "heartbeat", lambda *_: None)
    calls = []
    if kind == "frame":
        aid = upload(client, "source.mp4", clip, "video/mp4")
        key, model, typ, port, config = "video.frame_extract", "local.frame-extract", "Video", "video", {"timestamp_seconds": 1.2}
    else:
        aid = upload(client, "first.png", image_bytes(), "image/png")
        key, model, typ, port, config = "video.animate_image", "google.video.quality", "Image", "image", {}
        monkeypatch.setenv("GENERATION_PROVIDER_MODE", "live")
        class Models:
            def generate_videos(self, **kwargs):
                calls.append(kwargs)
                assert kwargs['source'].image.image_bytes == image_bytes()
                assert not kwargs['config'].reference_images
                assert kwargs['model'] == "veo-3.1-generate-001"
                return SimpleNamespace(name="projects/test/locations/us-central1/operations/test")
        provider = GoogleVideoProvider(GoogleProviderConfig("test"), client=SimpleNamespace(models=Models()))
        monkeypatch.setattr(provider, "wait_for_generated", lambda *a, **kw: [GeneratedBinary(clip, "video/mp4", "veo-3.1-generate-001", "google_test")])
        service = GoogleGenerationServices(text=object(), image=object(), video=provider, tts=object())
        monkeypatch.setattr("app.nodes.executors.video_generation.get_google_generation_services", lambda: service)
    nodes = [{"id": "source", "data": {"key": "asset.select", "contractVersion": 2,
              "config": {"artifact_id": aid, "artifact_type": typ}, "outputArtifactIds": [aid]}},
             {"id": "target", "data": {"key": key, "contractVersion": 1, "model": model, "config": config}}]
    edges = [{"id": "source-target", "source": "source", "target": "target", "sourceHandle": "artifact", "targetHandle": port}]
    if kind == "animate":
        nodes.append({"id": "prompt", "data": {"key": "prompt.input", "configText": "She smiles."}})
        edges.append({"id": "prompt-target", "source": "prompt", "target": "target", "sourceHandle": "prompt", "targetHandle": "prompt"})
    saved = client.post("/canvases", json={"name": "Start frame", "document": canonicalize_canvas_document(nodes, edges)}).json()
    with SessionLocal() as db:
        run_id = create_canvas_run(db, CanvasRunRequest(canvas_id=saved['id'], canvas_revision=saved['revision'], target_node_id="target")).id
    result = asyncio.run(canvas_activities.execute_canvas_node_activity(run_id, "target")) if temporal else execute_canvas_node(run_id, "target")
    artifact = client.get('/artifacts/' + result['artifact_ids'][0]).json()
    assert artifact['schema_id'] == ("image.video_frame.v1" if kind == "frame" else "video.image_animation.v1")
    assert artifact['input_artifact_ids'] == [aid]
    assert artifact['metadata']['input_artifact_roles'][aid] == ("source_video" if kind == "frame" else "first_frame")
    assert artifact['metadata']['definition_digest'] == node_registry.get(key, 1).definition_digest
    assert artifact['metadata']['normalized_config'] == node_registry.resolve_config(node_registry.get(key, 1), config)
    if kind == "frame":
        data = client.get('/artifacts/' + artifact['id'] + '/content').content
        im = Image.open(io.BytesIO(data)); red, green, blue = im.convert('RGB').getpixel((80, 48))
        assert im.size == (160, 96) and blue > 200 and red < 20
        assert '+ffmpeg:' in artifact['metadata']['execution_mode']
    else:
        assert artifact['metadata']['image_input_mode'] == 'first_frame'
        assert artifact['metadata']['cost_status'] == 'provider_billed_unreported'
        assert artifact['metadata']['execution_mode'] == 'image-animation.v1:live'
    repeated = execute_canvas_node(run_id, "target")
    assert repeated['artifact_ids'] == result['artifact_ids']
    assert len(calls) == (1 if kind == "animate" else 0)


def test_frame_zero_and_out_of_range_error(client, clip):
    aid = upload(client, "source.mp4", clip, "video/mp4")
    payload = {'canvas_id': 'test', 'node_id': 'frame', 'node_key': 'video.frame_extract', 'model_alias': 'local.frame-extract', 'inputs': [{'type': 'Video', 'artifact_ids': [aid]}]}
    result = client.post('/experiments', json=payload).json()
    assert result['status'] == 'SUCCEEDED'
    data = client.get('/artifacts/' + result['output_artifact_ids'][0] + '/content').content
    r, g, b = Image.open(io.BytesIO(data)).convert('RGB').getpixel((80, 48))
    assert r > 200 and b < 20
    failed = client.post('/experiments', json={**payload, 'parameters': {'timestamp_seconds': 2}}).json()
    assert failed['status'] == 'FAILED' and 'before the end' in failed['error']


def test_provider_preserves_legacy_reference_image_mode_and_checks_first_frame():
    calls = []
    provider = SimpleNamespace(submit=lambda **kw: calls.append(kw) or 'op', wait_for_generated=lambda *a, **kw: [])
    service = GoogleGenerationServices(text=object(), image=object(), video=provider, tts=object())
    kwargs = dict(logical_model='google.video.quality', prompt='Move', duration_seconds=8, candidate_count=1, aspect_ratio='9:16', resolution='1080p', seed=0,
                  image_inputs=[InputMedia('image', 'Image', b'png', 'image/png')], video_inputs=[])
    service.generate_videos(**kwargs)
    assert calls[-1]['reference_images'] == [(b'png', 'image/png')] and 'image_data' not in calls[-1]
    service.generate_videos(**kwargs, image_input_mode='first_frame')
    assert calls[-1]['reference_images'] == [] and calls[-1]['image_data'] == b'png'
    with pytest.raises(ValueError, match='one Image'):
        service.generate_videos(**{**kwargs, 'image_inputs': []}, image_input_mode='first_frame')


def test_google_submission_fingerprint_includes_starting_image_content():
    client = SimpleNamespace(models=SimpleNamespace(generate_videos=lambda **kw: SimpleNamespace(name='operations/test')))
    provider = GoogleVideoProvider(GoogleProviderConfig('test'), client=client)
    first = provider.submit(prompt='Move', image_data=b'first', duration_seconds=8)
    second = provider.submit(prompt='Move', image_data=b'second', duration_seconds=8)
    assert first.request_hash != second.request_hash


def test_fixture_animation_uses_same_result_contract(client):
    aid = upload(client, 'frame.png', image_bytes(), 'image/png')
    result = client.post('/experiments', json={'canvas_id':'c', 'node_id':'n', 'node_key':'video.animate_image', 'model_alias':'google.video.quality',
        'prompt':'She smiles', 'inputs':[{'type':'Image', 'artifact_ids':[aid]}]}).json()
    assert result['status'] == 'SUCCEEDED', result.get('error')
    artifact = client.get('/artifacts/' + result['output_artifact_ids'][0]).json()
    assert artifact['type'] == 'Video' and artifact['schema_id'] == 'video.image_animation.v1'
    assert artifact['metadata']['input_artifact_roles'][aid] == 'first_frame'


def test_ambiguous_animation_submission_cannot_be_billed_twice(client, monkeypatch):
    monkeypatch.setenv('GENERATION_PROVIDER_MODE', 'live')
    aid = upload(client, 'frame.png', image_bytes(), 'image/png')
    calls = []
    def fail(**kwargs):
        calls.append(kwargs)
        raise RuntimeError('connection interrupted')
    monkeypatch.setattr('app.nodes.executors.video_generation.get_google_generation_services', lambda: SimpleNamespace(generate_videos=fail))
    payload = {'canvas_id':'c', 'node_id':'n', 'node_key':'video.animate_image', 'model_alias':'google.video.quality',
               'prompt':'She smiles', 'inputs':[{'type':'Image', 'artifact_ids':[aid]}]}
    first = client.post('/experiments', json=payload).json()
    second = client.post('/experiments', json=payload).json()
    assert first['status'] == second['status'] == 'FAILED'
    assert 'inspect the provider operation' in first['error']
    assert 'unresolved outcome' in second['error']
    assert len(calls) == 1


def test_publish_keeps_start_image_chain_and_excludes_unused_nodes(client, clip):
    vid = upload(client, 'video.mp4', clip, 'video/mp4')
    img = upload(client, 'character.png', image_bytes(), 'image/png')
    nodes = [
        {'id':'video', 'data':{'key':'asset.select','contractVersion':2,'config':{'artifact_id':vid,'artifact_type':'Video'},'outputArtifactIds':[vid]}},
        {'id':'character', 'data':{'key':'asset.select','contractVersion':2,'config':{'artifact_id':img,'artifact_type':'Image'},'outputArtifactIds':[img]}},
        {'id':'frame', 'data':{'key':'video.frame_extract','model':'local.frame-extract'}},
        {'id':'edit', 'data':{'key':'prompt.input','configText':'Identity from the character, pose from the video frame.'}},
        {'id':'image', 'data':{'key':'image.generate','model':'openai.image.default'}},
        {'id':'motion', 'data':{'key':'prompt.input','configText':'Smile, then point up.'}},
        {'id':'animation', 'data':{'key':'video.animate_image','model':'google.video.quality'}},
        {'id':'unused', 'data':{'key':'video.frame_extract','model':'local.frame-extract'}},
        {'id':'note', 'data':{'key':'utility.sticky','configText':'Keep the character body proportions.'}},
    ]
    edges = [{'id':str(i),'source':s,'target':t,'sourceHandle':sp,'targetHandle':tp} for i,(s,t,sp,tp) in enumerate([
        ('video','frame','artifact','video'), ('character','edit','artifact','images'), ('frame','edit','image','images'),
        ('edit','image','prompt','prompt'), ('image','animation','image','image'), ('motion','animation','prompt','prompt')])]
    workflow = client.post('/workflows', json={'name':'Start-frame workflow'}).json()
    canvas = client.get('/canvases/' + workflow['draft_canvas_id']).json()
    contract = {'schema_version':'workflow.contract.draft.v1','inputs':[],'bindings':[],'outputs':[
        {'key':'video','label':'Video','node_id':'animation','port_key':'video','port_type':'media.video.v1','primary':True}]}
    saved = client.put('/canvases/' + canvas['id'], json={'name':canvas['name'],'document':canonicalize_canvas_document(nodes,edges),
        'expected_revision':canvas['revision'],'draft_contract':contract})
    assert saved.status_code == 200, saved.text
    result = client.post(f"/workflows/{workflow['id']}/publish",json={'expected_canvas_revision':saved.json()['revision']})
    assert result.status_code == 201, result.text
    version = result.json()
    assert {n['id'] for n in version['graph']['nodes']} == {'video','character','frame','edit','image','motion','animation'}
    assert version['warnings'] == ['Unused Canvas Node excluded: unused']
    assert len(client.get(f"/workflows/{workflow['id']}/versions/1/annotations").json()) == 1
