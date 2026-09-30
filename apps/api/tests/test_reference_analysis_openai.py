import json
from types import SimpleNamespace as NS

import pytest

from app.nodes import node_registry
from app.reference_analysis import _normalize_text_tracks, _semantic_schema
from app.reference_analysis_openai import OpenAIReferenceAnalyzer, OpenAIReferenceRecognizer, _strict
from app.media_preview import render_video_mp4


def test_v2_contract_defaults_and_old_digest():
    old = node_registry.get('reference.decompose', 1)
    new = node_registry.get('reference.decompose', 2)
    assert old.definition_digest == 'sha256:50af1faae50f9a800cab0021468820087dd277d9c11e4dc61596cdc357103c96'
    assert old.execution.provider == 'local+google'
    assert new.execution.model_alias == 'openai.chat.latest'
    assert new.editor.kind == 'generic'
    assert new.ports == old.ports
    config = node_registry.resolve_config(new, {})
    assert config['sample_interval_seconds'] == 2
    with pytest.raises(ValueError):
        node_registry.resolve_config(new, {'max_frames': 0})
    assert node_registry.runtime_revision(old, {}) != node_registry.runtime_revision(new, config)


def test_openai_transcription_uses_segment_timestamps_and_language():
    seen = {}
    def create(**kwargs):
        seen.update(kwargs)
        return NS(language='ja', segments=[NS(start=0.2, end=1.4, text=' 旅行です。 ')], _request_id='speech-request')
    adapter = OpenAIReferenceRecognizer(NS(audio=NS(transcriptions=NS(create=create))))
    result = adapter.transcribe(b'wav', language_code='ja-JP', duration_ms=1000)
    assert seen['model'] == 'whisper-1'
    assert seen['language'] == 'ja'
    assert seen['response_format'] == 'verbose_json'
    assert result.segments[0].start_ms == 200
    assert result.segments[0].end_ms == 1000
    assert adapter.request_ids == ['speech-request']


def test_visual_request_has_real_frames_and_no_inferred_audio():
    calls = []
    payload = {'actions': [], 'text_tracks': [], 'music_intervals': [], 'sound_effects': []}
    def create(**kwargs):
        calls.append(kwargs)
        return NS(id='resp-test', output_text=json.dumps(payload))
    analyzer = OpenAIReferenceAnalyzer(logical_model='openai.chat.latest', sample_interval_seconds=.5,
                                      max_frames=10, client=NS(responses=NS(create=create)))
    result = analyzer.analyze(render_video_mp4('abcdef123456', 1), 'video/mp4', duration_ms=1000,
                              shots=[], language_code='auto', has_audio=False, transcript_text='source words')
    request = calls[0]
    assert request['model'] == 'chat-latest' and request['store'] is False
    images = [x for x in request['input'][0]['content'] if x['type'] == 'input_image']
    assert 1 <= len(images) <= 10
    assert all(x['image_url'].startswith('data:image/jpeg;base64,') for x in images)
    assert request['text']['format']['strict']
    assert result.music_intervals == result.sound_effects == []
    assert analyzer.provenance['audio_model'] is None
    assert 'source words' in request['input'][0]['content'][0]['text']


def test_audio_events_are_grounded_in_audio_and_offset(monkeypatch, tmp_path):
    from app import reference_analysis_openai as module
    def media(command, **kwargs):
        from pathlib import Path
        Path(command[-1]).write_bytes(b'compressed audio')
    monkeypatch.setattr(module, '_run', media)
    requests = []
    def create(**kwargs):
        requests.append(kwargs)
        assert kwargs['messages'][0]['content'][1]['type'] == 'input_audio'
        return NS(id='audio-request', choices=[NS(message=NS(content=json.dumps({'music_intervals': [], 'sound_effects': [
            {'start_ms': 0, 'end_ms': 200, 'label': 'click', 'confidence': .8}]})))])
    analyzer = OpenAIReferenceAnalyzer(logical_model='openai.chat.latest', sample_interval_seconds=2,
                                      max_frames=120, client=NS(chat=NS(completions=NS(create=create))))
    music,effects,ids = analyzer._audio_events(tmp_path/'source.mp4', tmp_path, 46000)
    assert len(requests) == 2 and len(ids) == 2
    assert effects[1]['start_ms'] == 45000
    assert music == []


def test_strict_schema_and_japanese_caption_matching():
    schema = _strict(_semantic_schema())
    assert schema['additionalProperties'] is False
    assert schema['properties']['text_tracks']['items']['properties']['positions']['items']['additionalProperties'] is False
    tracks = _normalize_text_tracks([{'text':'旅行です','kind':'overlay_text','end_ms':1000}],1000,'これは旅行です')
    assert tracks[0]['kind'] == 'speech_caption'


def test_v2_experiment_contract_cache_and_v1_compatibility(client):
    uploaded = client.post('/artifacts/upload', files={'file':('clip.mp4',render_video_mp4('123abc456789',1),'video/mp4')}).json()
    request = {'canvas_id':'reference-v2-test','node_id':'analysis','node_key':'reference.decompose',
               'node_contract_version':2,'model_alias':'openai.chat.latest',
               'parameters':{'separate_music':False},'inputs':[{'type':'Video','artifact_ids':[uploaded['artifact_id']]}]}
    response = client.post('/experiments',json=request)
    assert response.status_code == 201, response.text
    result = response.json();assert result['status'] == 'SUCCEEDED',result
    artifact = client.get('/artifacts/'+result['output_artifact_ids'][0]).json()
    assert artifact['type'] == 'ReferenceAnalysis'
    assert uploaded['artifact_id'] in artifact['input_artifact_ids']
    assert artifact['metadata']['runtime_snapshot']['analyzer_revision'] == 'reference-analysis.openai.v2'
    assert client.post('/experiments',json=request).json()['cache_hit']
    old = client.post('/experiments',json={**request,'node_contract_version':1,'model_alias':'reference-analysis.pipeline'}).json()
    assert old['status'] == 'SUCCEEDED' and old['request_hash'] != result['request_hash']


@pytest.mark.parametrize('temporal', [False, True])
def test_v2_stored_canvas_local_temporal_parity(client, monkeypatch, temporal):
    import asyncio
    from app import canvas_activities
    from app.canvas_documents import canonicalize_canvas_document
    from app.canvas_runs import create_canvas_run, execute_canvas_node
    from app.database import SessionLocal
    from app.domain import CanvasRunRequest
    monkeypatch.setattr(canvas_activities, 'refresh_provider_environment', lambda: None)
    monkeypatch.setattr(canvas_activities.activity, 'heartbeat', lambda *_: None)
    source_id = client.post('/artifacts/upload',files={'file':('video.mp4',render_video_mp4('abcdef123456',1),'video/mp4')}).json()['artifact_id']
    nodes = [
        {'id':'source','position':{'x':0,'y':0},'data':{'key':'asset.select','contractVersion':1,'config':{'artifact_id':source_id,'artifact_type':'Video'},'outputArtifactIds':[source_id]}},
        {'id':'analysis','position':{'x':300,'y':0},'data':{'key':'reference.decompose','contractVersion':2,'model':'openai.chat.latest','provider':'openai','config':{'separate_music':False}}},
    ]
    doc = canonicalize_canvas_document(nodes,[{'id':'video','source':'source','target':'analysis','targetHandle':'input-Video-0'}])
    saved = client.post('/canvases',json={'name':'Reference v2','document':doc}).json()
    with SessionLocal() as db:
        run = create_canvas_run(db,CanvasRunRequest(canvas_id=saved['id'],canvas_revision=saved['revision'],target_node_id='analysis'))
        db.commit();run_id=run.id
    result = asyncio.run(canvas_activities.execute_canvas_node_activity(run_id,'analysis')) if temporal else execute_canvas_node(run_id,'analysis')
    assert len(result['artifact_ids']) == 1,result
    artifact = client.get('/artifacts/'+result['artifact_ids'][0]).json()
    assert artifact['type'] == 'ReferenceAnalysis'
    assert artifact['metadata']['runtime_snapshot']['analyzer_revision']=='reference-analysis.openai.v2'
    assert artifact['metadata']['definition_digest']==node_registry.get('reference.decompose',2).definition_digest


def test_openai_visual_failure_is_explicit_and_does_not_fallback():
    from app.reference_analysis import ReferenceAnalysisError
    def fail(**kwargs):
        raise RuntimeError('provider unavailable')
    analyzer = OpenAIReferenceAnalyzer(logical_model='openai.chat.latest',sample_interval_seconds=2,max_frames=10,
                                      client=NS(responses=NS(create=fail)))
    with pytest.raises(ReferenceAnalysisError,match='OpenAI visual reference analysis failed'):
        analyzer.analyze(render_video_mp4('abcdef123456',1),'video/mp4',duration_ms=1000,shots=[],language_code='auto',has_audio=False)
