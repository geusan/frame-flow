from __future__ import annotations

import base64
import hashlib
import io
import json
import wave
from types import SimpleNamespace

import pytest
from app.caption_documents import canonical_caption_document
from app.domain import ExperimentRunRequest
from app.experiments import request_fingerprint
from app.nodes import node_registry
from app.nodes.contracts import (
    NodeArtifactContent,
    NodeArtifactSnapshot,
    NodeExecutionContext,
    NodeExecutionResult,
)
from app.nodes.executors import practice
from app.nodes.output_ports import artifacts_for_output_port


class Store:
    def __init__(self):
        self.values = {}
        self.writes = []

    def add(self, kind, data, schema=None):
        key = f"art_{len(self.values) + 1}"
        r = NodeArtifactSnapshot(
            id=key, type=kind, schema_id=schema, sha256=hashlib.sha256(data).hexdigest()
        )
        self.values[key] = NodeArtifactContent(
            r,
            data,
            "image/png"
            if kind == "Image"
            else "audio/wav"
            if kind == "Audio"
            else "application/json",
        )
        return key

    def read(self, key):
        return self.values[key]

    def create(self, write):
        self.writes.append(write)
        key = self.add(write.artifact_type, write.content, write.schema_id)
        return SimpleNamespace(id=key, type=write.artifact_type)

    def flush(self):
        pass

    def content_url(self, key):
        return "/artifacts/" + key + "/content"


def ctx(key, store):
    d = node_registry.get(key, 1)
    return NodeExecutionContext(
        definition=d,
        prompt="",
        model_alias=d.execution.model_alias,
        request_hash="1" * 64,
        experiment_id="exp_test",
        artifact_store=store,
        media_runtime=SimpleNamespace(
            canonical_caption_document=lambda doc: canonical_caption_document(None, doc)
        ),
    )


def config(key, **values):
    return node_registry.resolve_config(node_registry.get(key, 1), values)


def inp(kind, key, port):
    return {"type": kind, "artifact_ids": [key], "target_port": port}


def track_config():
    return config("audio.practice_track")


def wav(seconds):
    import math
    import struct

    b = io.BytesIO()
    with wave.open(b, "wb") as w:
        w.setparams((1, 2, 48000, 0, "NONE", "not compressed"))
        w.writeframes(
            b"".join(
                struct.pack("<h", int(6000 * math.sin(i * 2 * math.pi * 440 / 48000)))
                for i in range(round(seconds * 48000))
            )
        )
    return b.getvalue()


def test_timing_accounts_for_voice_and_lead_and_has_at_least_45_silent_frames():
    for seconds in [0.1, 2.61, 5, 8]:
        t = practice.practice_timing(seconds, track_config())
        assert t["phase_seconds"] >= seconds + 0.35
        assert t["duration_seconds"] - t["content_end"] >= 1.5 - 1e-9
        assert t["replay_start"] + seconds < t["content_end"]
        assert t["question_seconds"] + t["answer_seconds"] == pytest.approx(
            t["duration_seconds"]
        )
        assert t["duration_seconds"] * 30 == pytest.approx(
            round(t["duration_seconds"] * 30)
        )


@pytest.mark.parametrize("seconds", [0, -1, float("nan"), float("inf"), 20])
def test_invalid_duration_fails_nonretryably(seconds):
    with pytest.raises(practice.PracticeValidationError) as e:
        practice.practice_timing(seconds, track_config())
    assert e.value.retryable is False


def test_track_real_audio_and_port_selection(tmp_path):
    store = Store()
    v = store.add("Audio", wav(1))
    b = store.add("Audio", wav(0.25))
    c = ctx("audio.practice_track", store)
    r = node_registry.execute(
        c, track_config(), [inp("Audio", v, "voice"), inp("Audio", b, "beat")]
    )
    assert isinstance(r, NodeExecutionResult)
    assert len(r.output_artifact_ids) == 2 and r.cost_usd == 0
    audio, timing = [store.read(k) for k in r.output_artifact_ids]
    t = json.loads(timing.data)
    with wave.open(io.BytesIO(audio.data)) as w:
        rate = w.getframerate()
        channels = w.getnchannels()
        samples = w.readframes(w.getnframes())
        assert len(samples) / (rate * channels * 2) == pytest.approx(
            t["duration_seconds"], abs=1 / rate
        )
        assert not any(samples[-int(1.49 * rate * channels * 2) :]), (
            "Ending must contain digital silence, including the beat"
        )
    assert artifacts_for_output_port(
        c.definition, c.definition.ports.outputs[1], [audio.record, timing.record]
    ) == [timing.id]
    assert store.writes[0].input_artifact_ids == [v, b]
    assert store.writes[1].schema_id == "practice.timing.v1"


def test_ambiguous_audio_inputs_are_rejected():
    store = Store()
    a = store.add("Audio", wav(0.1))
    c = ctx("audio.practice_track", store)
    with pytest.raises(practice.PracticeValidationError):
        node_registry.execute(c, {}, [{"type": "Audio", "artifact_ids": [a]}])


def test_motion_and_guide_consume_same_timing_and_end_captions_before_pause():
    store = Store()
    t = practice.practice_timing(2.5, track_config())
    tid = store.add("PracticeTiming", json.dumps(t).encode(), "practice.timing.v1")
    image = store.add("Image", b"png")
    for phase in ["question", "answer"]:
        r = node_registry.execute(
            ctx("image.practice_motion", store),
            {"phase": phase},
            [inp("PracticeTiming", tid, "timing"), inp("Image", image, "image")],
        )
        data = json.loads(store.read(r.output_artifact_ids[0]).data)
        assert data["schema_version"] == "image.motion.v4"
        assert data["source"]["artifact_id"] == image
        assert data["duration_seconds"] == t[phase + "_seconds"]
    r = node_registry.execute(
        ctx("subtitle.practice_guide", store),
        {},
        [inp("PracticeTiming", tid, "timing")],
    )
    d = json.loads(store.read(r.output_artifact_ids[0]).data)
    assert len(d["cues"]) == 2
    assert d["cues"][-1]["end_ms"] == round(t["content_end"] * 1000)
    assert d["cues"][0]["start_ms"] == round(t["phase_seconds"] * 1000)


LESSON = {
    "ja": "好きです。",
    "ko": "좋아해요.",
    "target": {
        "surface": "好き",
        "reading": "すき",
        "base": "好き",
        "base_reading": "すき",
        "ko": "좋아하다",
        "pos": "adjective",
    },
}


def test_lesson_cannot_silently_replace_user_sentences():
    assert (
        practice.parse_lesson(json.dumps(LESSON), LESSON["ja"], LESSON["ko"]) == LESSON
    )
    with pytest.raises(practice.PracticeValidationError):
        practice.parse_lesson(json.dumps(LESSON), "違う。", LESSON["ko"])
    wrong = {**LESSON, "target": {**LESSON["target"], "surface": "嫌い"}}
    with pytest.raises(practice.PracticeValidationError):
        practice.parse_lesson(json.dumps(wrong), LESSON["ja"], LESSON["ko"])


def test_screen_pins_renderer_and_records_lineage(monkeypatch, tmp_path):
    token = tmp_path / "token"
    token.write_text("test")
    monkeypatch.setenv("STUDY_SCREEN_TOKEN_FILE", str(token))
    calls = []

    def render(req, timeout):
        calls.append(json.loads(req.data))
        return io.BytesIO(
            json.dumps(
                {
                    "renderer_revision": "test-revision",
                    "width": 2340,
                    "height": 5064,
                    "question": base64.b64encode(b"\x89PNG\r\n\x1a\nfixture").decode(),
                }
            ).encode()
        )

    monkeypatch.setattr(practice.urllib.request, "urlopen", render)
    s = Store()
    a = s.add("Text", json.dumps(LESSON).encode())
    c = ctx("image.study_screen", s)
    cfg = {
        "japanese": LESSON["ja"],
        "korean": LESSON["ko"],
        "renderer_revision": "test-revision",
    }
    r = node_registry.execute(c, cfg, [inp("Text", a, "lesson")])
    assert r.output["kind"] == "image"
    assert calls == [LESSON]
    assert s.writes[0].input_artifact_ids == [a]
    assert s.writes[0].metadata["renderer_revision"] == "test-revision"
    with pytest.raises(practice.PracticeValidationError):
        node_registry.execute(
            c, {**cfg, "renderer_revision": "different"}, [inp("Text", a, "lesson")]
        )


def test_missing_renderer_is_retryable(monkeypatch, tmp_path):
    monkeypatch.setenv("STUDY_SCREEN_TOKEN_FILE", str(tmp_path / "missing"))
    s = Store()
    a = s.add("Text", json.dumps(LESSON).encode())
    with pytest.raises(practice.PracticeRuntimeError) as e:
        node_registry.execute(
            ctx("image.study_screen", s),
            {"japanese": LESSON["ja"], "korean": LESSON["ko"]},
            [inp("Text", a, "lesson")],
        )
    assert e.value.retryable


def test_contract_fields_and_renderer_revision_affect_cache_keys():
    c = {
        "japanese": LESSON["ja"],
        "korean": LESSON["ko"],
        "state": "question",
        "renderer_revision": "a",
    }
    d = node_registry.get("image.study_screen", 1)

    def fingerprint(cfg):
        p = ExperimentRunRequest(
            canvas_id="test",
            node_id="screen",
            node_key=d.type_key,
            node_contract_version=1,
            model_alias=d.execution.model_alias,
            parameters=cfg,
        )
        return request_fingerprint(p, d.execution.model_alias, d.execution.revision)

    assert fingerprint(c) != fingerprint({**c, "state": "answer"})
    assert fingerprint(c) != fingerprint({**c, "renderer_revision": "b"})
    for key in [
        "image.study_screen",
        "audio.practice_track",
        "image.practice_motion",
        "subtitle.practice_guide",
    ]:
        d = node_registry.get(key, 1)
        assert d.editor.kind == "generic"
        assert d.execution.kind == "local"


def test_runtime_revisions_fit_persisted_execution_mode_column():
    for key in ["image.study_screen", "audio.practice_track"]:
        d = node_registry.get(key, 1)
        cfg = config(key)
        assert len(node_registry.runtime_revision(d, cfg)) <= 64


def test_registry_library_exposes_generic_editors_and_typed_timing(client):
    library = {d["type_key"]: d for d in client.get("/node-definitions").json()}
    screen = library["image.study_screen"]
    assert screen["editor"]["kind"] == "generic"
    assert (
        screen["config_schema"]["properties"]["japanese"]["x-workflow-input"]["type"]
        == "string"
    )
    assert screen["config_schema"]["properties"]["korean"]["x-workflow-input"][
        "enabled"
    ]
    track = library["audio.practice_track"]
    assert [p["type"] for p in track["ports"]["outputs"]] == [
        "media.audio.v1",
        "data.practice_timing.v1",
    ]


def test_timing_schema_and_damaged_input_rejection():
    from pathlib import Path

    from jsonschema import validate

    schema = json.loads(
        (
            Path(__file__).parents[3]
            / "packages/schemas/practice.timing.v1.schema.json"
        ).read_text()
    )
    t = practice.practice_timing(2.5, track_config())
    validate(t, schema)
    store = Store()
    t["duration_seconds"] = t["content_end"]
    a = store.add("PracticeTiming", json.dumps(t).encode(), "practice.timing.v1")
    with pytest.raises(practice.PracticeValidationError):
        node_registry.execute(
            ctx("subtitle.practice_guide", store),
            {},
            [inp("PracticeTiming", a, "timing")],
        )


def test_canvas_dispatch_routes_practice_audio_and_timing_separately():
    from app.canvas_runs import _experiment_payload

    artifacts = {
        "sound": SimpleNamespace(id="sound", type="Audio"),
        "timing": SimpleNamespace(id="timing", type="PracticeTiming"),
    }
    source = SimpleNamespace(
        canvas_node_id="track",
        node_key="audio.practice_track",
        output_artifact_ids=["sound", "timing"],
        output_payload={},
    )
    target = SimpleNamespace(
        canvas_node_id="target",
        node_key="subtitle.practice_guide",
        output_artifact_ids=[],
        output_payload={},
    )
    run = SimpleNamespace(
        canvas_id="test",
        node_runs=[source, target],
        graph_snapshot={
            "source": "stored_canvas",
            "nodes": [
                {
                    "id": "track",
                    "data": {
                        "key": "audio.practice_track",
                        "contractVersion": 1,
                        "outputType": "Audio",
                    },
                },
                {"id": "target", "data": {"key": "subtitle.practice_guide"}},
            ],
            "edges": [
                {
                    "source": "track",
                    "target": "target",
                    "sourceHandle": "timing",
                    "targetHandle": "timing",
                }
            ],
        },
    )
    db = SimpleNamespace(get=lambda _model, key: artifacts[key])
    payload = _experiment_payload(
        db,
        run,
        target,
        {"key": "subtitle.practice_guide", "contractVersion": 1, "config": {}},
    )
    assert payload.inputs[0]["artifact_ids"] == ["timing"]
    assert payload.inputs[0]["type"] == "PracticeTiming"


def test_short_sentence_preserves_minimum_pause_after_frame_and_aac_rounding():
    t = practice.practice_timing(2.250958, track_config())
    # Reproduces the short-sentence failure after the existing 24fps concat and AAC mux.
    worst_end = t["duration_seconds"] - 1 / 24 - 1024 / 48000
    assert worst_end - t["content_end"] >= 1.5


def test_malformed_lesson_fence_is_a_validation_error():
    with pytest.raises(practice.PracticeValidationError):
        practice.parse_lesson("```", LESSON["ja"], LESSON["ko"])
