from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import canvas_activities
from app.domain import ExperimentRunRequest
from app.experiments import request_fingerprint, resolve_model
from app.image_story_video import (
    IMAGE_STORY_VIDEO_REVISION,
    IMAGE_STORY_VIDEO_SCHEMA,
    RenderedImageStory,
    StoryMedia,
    parse_srt_cues,
    render_image_story,
)
from app.nodes import node_registry
from app.nodes.contracts import NodeExecutionContext
from app.nodes.executors import image_story_video as executor_module


STORY_SRT = """1
00:00:00,000 --> 00:00:00,500
A scholar heard frightened magpies.

2
00:00:00,500 --> 00:00:01,000
Their kindness returned before dawn.
""".encode()


def _fixture_image(path: Path, color: str) -> bytes:
    try:
        subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", f"color=c={color}:s=120x120",
                "-frames:v", "1", str(path),
            ],
            check=True,
            capture_output=True,
            timeout=90,
        )
    except FileNotFoundError:
        pytest.skip("ffmpeg is not installed")
    return path.read_bytes()


def _fixture_audio(path: Path) -> bytes:
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
            "-t", "1", "-c:a", "pcm_s16le", str(path),
        ],
        check=True,
        capture_output=True,
        timeout=90,
    )
    return path.read_bytes()


def _frame_rgb(video: bytes, path: Path, *, width: int, height: int) -> bytes:
    path.write_bytes(video)
    completed = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", "0.1", "-i", str(path),
            "-frames:v", "1", "-vf", "format=rgb24", "-f", "rawvideo", "pipe:1",
        ],
        check=True,
        capture_output=True,
        timeout=90,
    )
    assert len(completed.stdout) == width * height * 3
    return completed.stdout


def _pixel(frame: bytes, *, width: int, x: int, y: int) -> tuple[int, int, int]:
    offset = (y * width + x) * 3
    return tuple(frame[offset:offset + 3])


def test_image_story_manifest_is_registered_for_generic_web_and_versioned_ports(client):
    definition = node_registry.get("video.image_story", 1)
    assert definition is not None
    assert definition.lifecycle == "ACTIVE"
    assert definition.editor.kind == "generic"
    assert definition.execution.executor == "image-story-video"
    assert definition.execution.revision == IMAGE_STORY_VIDEO_REVISION
    assert [(port.key, port.type, port.required, port.multiple) for port in definition.ports.inputs] == [
        ("images", "media.image.v1", True, True),
        ("subtitle", "data.subtitle.v1", True, False),
        ("audio", "media.audio.v1", False, False),
    ]
    assert definition.ports.outputs[0].type == "media.video.v1"
    assert definition.artifact_contract.schema_id == IMAGE_STORY_VIDEO_SCHEMA
    assert node_registry.resolve_config(definition, {}) == {
        "aspect_ratio": "9:16",
        "resolution": "1080p",
        "fps": 24,
        "scene_timing": "subtitle_cues",
        "motion_preset": "alternate",
        "motion_amount": 0.12,
        "image_region_height_ratio": 0.62,
        "image_margin_ratio": 0.04,
        "background_color": "#11100E",
        "caption_font_family": "Noto Sans CJK KR",
        "caption_font_size": 58,
        "caption_color": "#F7F3E8",
        "caption_outline_color": "#000000",
        "caption_align": "center",
    }
    web_definition = next(item for item in client.get("/node-definitions").json() if item["type_key"] == "video.image_story")
    assert web_definition["editor"] == {"kind": "generic"}
    assert web_definition["config_schema"]["properties"]["image_region_height_ratio"]["x-workflow-input"]["enabled"] is True


def test_image_story_config_validation_and_request_hash_cover_render_contract():
    definition = node_registry.get("video.image_story", 1)
    assert definition is not None
    with pytest.raises(ValueError, match="must be at most 0.3"):
        node_registry.resolve_config(definition, {"motion_amount": 0.5})
    with pytest.raises(ValueError, match="invalid format"):
        node_registry.resolve_config(definition, {"background_color": "black"})

    payload = ExperimentRunRequest(
        canvas_id="canvas_story",
        node_id="story_video",
        node_key=definition.type_key,
        node_contract_version=1,
        prompt="",
        model_alias=definition.execution.model_alias,
        parameters={"motion_amount": 0.12},
        inputs=[{"type": "Image", "artifact_ids": ["image_1"]}],
    )
    model_alias, exact_model_id = resolve_model(payload.model_alias, payload.node_key, payload.node_contract_version)
    changed = payload.model_copy(update={"parameters": {"motion_amount": 0.2}})
    assert request_fingerprint(payload, model_alias, exact_model_id) != request_fingerprint(changed, model_alias, exact_model_id)
    changed_input = payload.model_copy(update={"inputs": [{"type": "Image", "artifact_ids": ["image_2"]}]})
    assert request_fingerprint(payload, model_alias, exact_model_id) != request_fingerprint(changed_input, model_alias, exact_model_id)


def test_srt_parser_preserves_ordered_timing_and_rejects_empty_subtitles():
    cues = parse_srt_cues(STORY_SRT)
    assert [(cue.start_ms, cue.end_ms, cue.text) for cue in cues] == [
        (0, 500, "A scholar heard frightened magpies."),
        (500, 1000, "Their kindness returned before dawn."),
    ]
    with pytest.raises(ValueError, match="valid SRT cues"):
        parse_srt_cues(b"not a subtitle")


def test_image_story_renderer_clips_images_and_reserves_the_external_caption_panel(tmp_path):
    red = _fixture_image(tmp_path / "red.png", "red")
    blue = _fixture_image(tmp_path / "blue.png", "blue")
    narration = _fixture_audio(tmp_path / "narration.wav")
    rendered = render_image_story(
        [StoryMedia(red, "image/png"), StoryMedia(blue, "image/png")],
        STORY_SRT,
        audio=StoryMedia(narration, "audio/wav"),
        aspect_ratio="9:16",
        resolution="720p",
        fps=24,
        scene_timing="subtitle_cues",
        motion_preset="alternate",
        motion_amount=0.12,
        image_region_height_ratio=0.62,
        image_margin_ratio=0.05,
        background_color="#11100E",
        caption_font_family="DejaVu Sans",
        caption_font_size=58,
        caption_color="#F7F3E8",
        caption_outline_color="#000000",
        caption_align="center",
        output_size_override=(180, 320),
    )
    assert rendered.width == 180
    assert rendered.height == 320
    assert rendered.fps == 24
    assert rendered.scene_count == 2
    assert rendered.cue_count == 2
    assert rendered.has_audio is True
    assert 950 <= rendered.duration_ms <= 1100
    assert rendered.data[4:8] == b"ftyp"

    frame = _frame_rgb(rendered.data, tmp_path / "story.mp4", width=180, height=320)
    image_pixel = _pixel(frame, width=180, x=90, y=80)
    outside_pixel = _pixel(frame, width=180, x=2, y=80)
    caption_panel_pixel = _pixel(frame, width=180, x=2, y=290)
    assert image_pixel[0] > 150 and image_pixel[1] < 90 and image_pixel[2] < 90
    assert max(outside_pixel) < 60
    assert max(caption_panel_pixel) < 60


def test_subtitle_cue_timing_requires_one_image_per_cue(tmp_path):
    red = _fixture_image(tmp_path / "red.png", "red")
    with pytest.raises(ValueError, match="one Story Image per Subtitle cue"):
        render_image_story(
            [StoryMedia(red, "image/png")],
            STORY_SRT,
            audio=None,
            aspect_ratio="9:16",
            resolution="720p",
            fps=24,
            scene_timing="subtitle_cues",
            motion_preset="still",
            motion_amount=0,
            image_region_height_ratio=0.62,
            image_margin_ratio=0.04,
            background_color="#11100E",
            caption_font_family="DejaVu Sans",
            caption_font_size=58,
            caption_color="#FFFFFF",
            caption_outline_color="#000000",
            caption_align="center",
            output_size_override=(180, 320),
        )


def test_registry_executor_records_final_video_metadata_and_ordered_lineage(monkeypatch):
    definition = node_registry.get("video.image_story", 1)
    assert definition is not None
    artifacts = {
        "image_1": SimpleNamespace(id="image_1", type="Image", uri="memory://bucket/image-1", metadata_json={"storage": {"bucket": "bucket", "key": "image-1", "content_type": "image/png"}}),
        "image_2": SimpleNamespace(id="image_2", type="Image", uri="memory://bucket/image-2", metadata_json={"storage": {"bucket": "bucket", "key": "image-2", "content_type": "image/png"}}),
        "subtitle_1": SimpleNamespace(id="subtitle_1", type="Subtitle", uri="memory://bucket/subtitle-1", metadata_json={"storage": {"bucket": "bucket", "key": "subtitle-1", "content_type": "application/x-subrip"}}),
        "audio_1": SimpleNamespace(id="audio_1", type="Audio", uri="memory://bucket/audio-1", metadata_json={"storage": {"bucket": "bucket", "key": "audio-1", "content_type": "audio/wav"}}),
    }

    class FakeDb:
        flushed = False

        def get(self, _, artifact_id):
            return artifacts.get(artifact_id)

        def flush(self):
            self.flushed = True

    class FakeStorage:
        def get_bytes(self, *, bucket, key):
            assert bucket == "bucket"
            return {"image-1": b"one", "image-2": b"two", "subtitle-1": STORY_SRT, "audio-1": b"audio"}[key]

    db = FakeDb()
    captured: dict[str, object] = {}
    monkeypatch.setattr(executor_module, "get_storage", lambda: FakeStorage())

    def fake_render(images, subtitle_content, *, audio, **config):
        captured.update({"images": images, "subtitle": subtitle_content, "audio": audio, "config": config})
        return RenderedImageStory(b"video", 1080, 1920, 24, 8000, 2, 2, True)

    monkeypatch.setattr(executor_module, "render_image_story", fake_render)

    def fake_create_artifact(_, artifact_type, **kwargs):
        captured.update({"artifact_type": artifact_type, "artifact_kwargs": kwargs})
        return SimpleNamespace(id="final_1")

    monkeypatch.setattr(executor_module, "create_artifact", fake_create_artifact)
    monkeypatch.setattr(executor_module, "artifact_content_url", lambda artifact_id: f"http://api/artifacts/{artifact_id}/content")
    payload = ExperimentRunRequest(
        canvas_id="canvas_story",
        node_id="story_video",
        node_key=definition.type_key,
        node_contract_version=1,
        model_alias=definition.execution.model_alias,
        inputs=[],
    )
    context = NodeExecutionContext(
        db=db,
        payload=payload,
        definition=definition,
        request_hash="abcdef0123456789",
        experiment_id="experiment_story",
    )
    result = node_registry.execute(context, {}, [
        {"type": "Image", "artifact_ids": ["image_1"]},
        {"type": "Image", "artifact_ids": ["image_2"]},
        {"type": "Subtitle", "artifact_ids": ["subtitle_1"]},
        {"type": "Audio", "artifact_ids": ["audio_1"]},
    ])
    assert [media.data for media in captured["images"]] == [b"one", b"two"]
    assert captured["subtitle"] == STORY_SRT
    assert captured["audio"].data == b"audio"
    assert result.output_artifact_ids == ["final_1"]
    assert result.metadata["retryable"] is False
    assert result.metadata["renderer_revision"] == IMAGE_STORY_VIDEO_REVISION
    artifact_kwargs = captured["artifact_kwargs"]
    assert captured["artifact_type"] == "FinalVideo"
    assert artifact_kwargs["schema_id"] == IMAGE_STORY_VIDEO_SCHEMA
    assert artifact_kwargs["input_artifact_ids"] == ["image_1", "image_2", "subtitle_1", "audio_1"]
    assert artifact_kwargs["input_artifact_roles"] == {
        "image_1": "story_image",
        "image_2": "story_image",
        "subtitle_1": "timed_caption",
        "audio_1": "narration_audio",
    }
    assert artifact_kwargs["metadata"]["normalized_config"]["scene_timing"] == "subtitle_cues"
    assert db.flushed is True


def test_temporal_image_story_uses_the_shared_canvas_node_dispatch(monkeypatch):
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(canvas_activities, "refresh_provider_environment", lambda: None)
    monkeypatch.setattr(
        canvas_activities,
        "execute_canvas_node",
        lambda run_id, node_id: calls.append((run_id, node_id)) or {"artifact_ids": ["story_video_1"]},
    )
    monkeypatch.setattr(canvas_activities.activity, "heartbeat", lambda *_: None)
    result = asyncio.run(canvas_activities.execute_canvas_node_activity("run_story", "image_story"))
    assert result == {"artifact_ids": ["story_video_1"]}
    assert calls == [("run_story", "image_story")]
