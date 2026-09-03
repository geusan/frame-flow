from __future__ import annotations

import asyncio
import hashlib
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import canvas_activities
from app.domain import ExperimentRunRequest
from app.experiments import request_fingerprint, resolve_model, resolved_executor_revision
from app.image_story_video import (
    IMAGE_STORY_VIDEO_REVISION,
    IMAGE_STORY_VIDEO_SCHEMA,
    MEDIA_STORY_VIDEO_REVISION,
    MEDIA_STORY_VIDEO_SCHEMA,
    RenderedImageStory,
    StoryMedia,
    _motion_filter,
    _wrap_caption_text,
    parse_srt_cues,
    render_image_story,
)
from app.nodes import node_registry
from app.nodes.contracts import NodeExecutionContext
from app.nodes.executors import image_story_video as executor_module
from app.nodes.executors import media_story_video as media_executor_module


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


def _fixture_video(path: Path) -> bytes:
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "color=c=green:s=160x90:r=24",
            "-t", "0.5", "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
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


def test_media_story_manifest_owns_frame_crop_clip_motion_and_caption_contract(client):
    definition = node_registry.get("video.media_story", 1)
    assert definition is not None
    assert definition.editor.kind == "generic"
    assert definition.execution.executor == "media-story-video"
    assert definition.execution.revision == MEDIA_STORY_VIDEO_REVISION
    assert [(port.key, port.type, port.multiple) for port in definition.ports.inputs] == [
        ("images", "media.image.v1", True),
        ("videos", "media.video.v1", True),
        ("subtitle", "data.subtitle.v1", False),
        ("audio", "media.audio.v1", False),
    ]
    config = node_registry.resolve_config(definition, {})
    assert {key: config[key] for key in (
        "frame_x", "frame_y", "frame_width", "frame_height", "media_fit",
        "crop_focus_x", "crop_focus_y", "motion_start_scale", "motion_end_scale",
        "motion_start_x", "motion_start_y", "motion_end_x", "motion_end_y",
        "caption_frame_x", "caption_frame_y", "caption_frame_width", "caption_frame_height",
    )} == {
        "frame_x": 0.04, "frame_y": 0.02, "frame_width": 0.92, "frame_height": 0.62,
        "media_fit": "cover", "crop_focus_x": 0.5, "crop_focus_y": 0.5,
        "motion_start_scale": 1, "motion_end_scale": 1.12,
        "motion_start_x": 0.5, "motion_start_y": 0.5,
        "motion_end_x": 0.5, "motion_end_y": 0.5,
        "caption_frame_x": 0.06, "caption_frame_y": 0.68,
        "caption_frame_width": 0.88, "caption_frame_height": 0.28,
    }
    assert definition.artifact_contract.schema_id == MEDIA_STORY_VIDEO_SCHEMA
    web_definition = next(item for item in client.get("/node-definitions").json() if item["type_key"] == "video.media_story")
    assert web_definition["config_schema"]["properties"]["media_fit"]["enum"] == ["cover", "contain"]
    payload = ExperimentRunRequest(
        canvas_id="canvas_media_story", node_id="media_story", node_key=definition.type_key,
        node_contract_version=1, model_alias=definition.execution.model_alias,
        parameters={"frame_x": 0.04}, inputs=[{"type": "Image", "artifact_ids": ["image_1"]}],
    )
    model_alias, exact_model_id = resolve_model(payload.model_alias, payload.node_key, 1)
    moved = payload.model_copy(update={"parameters": {"frame_x": 0.08}})
    assert request_fingerprint(payload, model_alias, exact_model_id) != request_fingerprint(moved, model_alias, exact_model_id)
    runtime_revision = resolved_executor_revision(definition.type_key, model_alias, 1, config)
    assert runtime_revision.startswith(f"{MEDIA_STORY_VIDEO_REVISION}+")
    assert len(runtime_revision) <= 64


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


def test_caption_text_wraps_korean_words_before_the_render_boundary():
    wrapped = _wrap_caption_text("낮에 죽은 구렁이의 짝이라며 선비를 단단히 휘감았습니다.", 18)
    lines = wrapped.splitlines()
    assert len(lines) >= 2
    assert " ".join(lines) == "낮에 죽은 구렁이의 짝이라며 선비를 단단히 휘감았습니다."


def test_image_motion_preserves_source_aspect_ratio_with_center_cover_crop():
    filter_graph = _motion_filter(
        motion="zoom_in",
        amount=0.12,
        frames=120,
        width=994,
        height=1190,
        fps=24,
    )
    assert "force_original_aspect_ratio=increase" in filter_graph
    assert "crop=1114:1334" in filter_graph
    assert "zoompan=" in filter_graph


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
    assert rendered.renderer_environment["fingerprint"].startswith("sha256:")
    assert [scene["motion"] for scene in rendered.motion_plan] == ["zoom_in", "pan_right"]
    assert 950 <= rendered.duration_ms <= 1100
    assert rendered.data[4:8] == b"ftyp"

    frame = _frame_rgb(rendered.data, tmp_path / "story.mp4", width=180, height=320)
    image_pixel = _pixel(frame, width=180, x=90, y=80)
    outside_pixel = _pixel(frame, width=180, x=2, y=80)
    caption_panel_pixel = _pixel(frame, width=180, x=2, y=290)
    assert image_pixel[0] > 150 and image_pixel[1] < 90 and image_pixel[2] < 90
    assert max(outside_pixel) < 60
    assert max(caption_panel_pixel) < 60


def test_media_story_renderer_accepts_ordered_image_and_video_sources_with_explicit_frames(tmp_path):
    red = _fixture_image(tmp_path / "red.png", "red")
    green = _fixture_video(tmp_path / "green.mp4")
    rendered = render_image_story(
        [StoryMedia(red, "image/png", "image"), StoryMedia(green, "video/mp4", "video")],
        STORY_SRT,
        audio=None,
        aspect_ratio="9:16",
        resolution="720p",
        fps=24,
        scene_timing="equal",
        motion_preset="custom",
        motion_amount=0.12,
        image_region_height_ratio=0.62,
        image_margin_ratio=0,
        background_color="#11100E",
        caption_font_family="DejaVu Sans",
        caption_font_size=58,
        caption_color="#FFFFFF",
        caption_outline_color="#000000",
        caption_align="center",
        output_size_override=(180, 320),
        frame_x=0.05,
        frame_y=0.05,
        frame_width=0.9,
        frame_height=0.55,
        media_fit="cover",
        crop_focus_x=0.5,
        crop_focus_y=0.5,
        motion_start_scale=1,
        motion_end_scale=1.08,
        motion_start_x=0.4,
        motion_start_y=0.5,
        motion_end_x=0.6,
        motion_end_y=0.5,
        caption_frame_x=0.08,
        caption_frame_y=0.66,
        caption_frame_width=0.84,
        caption_frame_height=0.28,
    )
    assert rendered.scene_count == 2
    assert rendered.width == 180 and rendered.height == 320
    assert rendered.data[4:8] == b"ftyp"
    assert [scene["source_kind"] for scene in rendered.motion_plan] == ["image", "video"]
    assert all(scene["motion"] == "custom" for scene in rendered.motion_plan)


def test_media_story_rejects_overlapping_or_out_of_canvas_frames(tmp_path):
    red = _fixture_image(tmp_path / "red.png", "red")
    config = {
        "audio": None, "aspect_ratio": "9:16", "resolution": "720p", "fps": 24,
        "scene_timing": "equal", "motion_preset": "still", "motion_amount": 0,
        "image_region_height_ratio": 0.62, "image_margin_ratio": 0,
        "background_color": "#11100E", "caption_font_family": "DejaVu Sans",
        "caption_font_size": 58, "caption_color": "#FFFFFF", "caption_outline_color": "#000000",
        "caption_align": "center", "output_size_override": (180, 320),
        "frame_x": 0.05, "frame_y": 0.05, "frame_width": 0.9, "frame_height": 0.6,
        "caption_frame_x": 0.05, "caption_frame_y": 0.6,
        "caption_frame_width": 0.9, "caption_frame_height": 0.35,
    }
    with pytest.raises(ValueError, match="must not overlap"):
        render_image_story([StoryMedia(red, "image/png")], STORY_SRT.replace(b"\n\n2\n00:00:00,500 --> 00:00:01,000\nTheir kindness returned before dawn.", b""), **config)


def test_identical_renderer_inputs_and_config_produce_identical_mp4_bytes(tmp_path):
    image = StoryMedia(_fixture_image(tmp_path / "stable.png", "purple"), "image/png")
    subtitle = b"1\n00:00:00,000 --> 00:00:00,500\nStable caption.\n"
    config = {
        "audio": None, "aspect_ratio": "9:16", "resolution": "720p", "fps": 24,
        "scene_timing": "equal", "motion_preset": "zoom_in", "motion_amount": 0.08,
        "image_region_height_ratio": 0.62, "image_margin_ratio": 0.04,
        "background_color": "#11100E", "caption_font_family": "DejaVu Sans",
        "caption_font_size": 58, "caption_color": "#FFFFFF", "caption_outline_color": "#000000",
        "caption_align": "center", "output_size_override": (90, 160),
    }
    first = render_image_story([image], subtitle, **config)
    second = render_image_story([image], subtitle, **config)
    assert hashlib.sha256(first.data).hexdigest() == hashlib.sha256(second.data).hexdigest()
    assert first.motion_plan == second.motion_plan
    assert first.renderer_environment == second.renderer_environment


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
    assert result.metadata["renderer_revision"].startswith(f"{IMAGE_STORY_VIDEO_REVISION}+")
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


def test_media_story_registry_executor_preserves_mixed_media_order_and_lineage(monkeypatch):
    definition = node_registry.get("video.media_story", 1)
    assert definition is not None
    artifacts = {
        "image_1": SimpleNamespace(id="image_1", type="Image", uri="memory://bucket/image-1", metadata_json={"storage": {"bucket": "bucket", "key": "image-1", "content_type": "image/png"}}),
        "video_1": SimpleNamespace(id="video_1", type="Video", uri="memory://bucket/video-1", metadata_json={"storage": {"bucket": "bucket", "key": "video-1", "content_type": "video/mp4"}}),
        "subtitle_1": SimpleNamespace(id="subtitle_1", type="Subtitle", uri="memory://bucket/subtitle-1", metadata_json={"storage": {"bucket": "bucket", "key": "subtitle-1", "content_type": "application/x-subrip"}}),
    }

    class FakeDb:
        def get(self, _, artifact_id):
            return artifacts.get(artifact_id)

        def flush(self):
            return None

    class FakeStorage:
        def get_bytes(self, *, bucket, key):
            return {"image-1": b"image", "video-1": b"video", "subtitle-1": STORY_SRT}[key]

    captured = {}
    monkeypatch.setattr(media_executor_module, "get_storage", lambda: FakeStorage())

    def fake_render(sources, subtitle, **kwargs):
        captured.update({"sources": sources, "subtitle": subtitle, "kwargs": kwargs})
        return RenderedImageStory(b"rendered", 1080, 1920, 24, 1000, 2, 2, False)

    monkeypatch.setattr(media_executor_module, "render_image_story", fake_render)
    monkeypatch.setattr(media_executor_module, "create_artifact", lambda *args, **kwargs: captured.update({"artifact": kwargs}) or SimpleNamespace(id="final_media"))
    monkeypatch.setattr(media_executor_module, "artifact_content_url", lambda artifact_id: f"http://api/{artifact_id}")
    context = NodeExecutionContext(
        db=FakeDb(),
        payload=ExperimentRunRequest(
            canvas_id="canvas", node_id="media", node_key=definition.type_key,
            node_contract_version=1, model_alias=definition.execution.model_alias,
        ),
        definition=definition,
        request_hash="abcdef0123456789",
        experiment_id="experiment_media",
    )
    result = node_registry.execute(context, {}, [
        {"type": "Image", "artifact_ids": ["image_1"]},
        {"type": "Video", "artifact_ids": ["video_1"]},
        {"type": "Subtitle", "artifact_ids": ["subtitle_1"]},
    ])
    assert [(source.kind, source.data) for source in captured["sources"]] == [
        ("image", b"image"), ("video", b"video"),
    ]
    assert captured["kwargs"]["frame_x"] == 0.04
    assert captured["kwargs"]["media_fit"] == "cover"
    assert captured["artifact"]["input_artifact_ids"] == ["image_1", "video_1", "subtitle_1"]
    assert captured["artifact"]["input_artifact_roles"] == {
        "image_1": "story_image", "video_1": "story_video", "subtitle_1": "timed_caption",
    }
    assert result.output_artifact_ids == ["final_media"]
    assert result.metadata["schema_id"] == MEDIA_STORY_VIDEO_SCHEMA
    assert result.metadata["retryable"] is False


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
