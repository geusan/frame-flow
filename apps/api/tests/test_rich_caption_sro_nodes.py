from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.database import ArtifactRecord, SessionLocal
from app.domain import ExperimentRunRequest
from app.nodes import node_registry
from app.nodes.contracts import NodeExecutionContext
from app.nodes.executors import rich_caption_sro as rich_caption_module
from app.nodes.executors.rich_caption_sro import RichSubtitleLayoutExecutor, SubtitleDesignExecutor, VideoCaptionBurnExecutor
from app.service import create_artifact
from app.storage import get_storage, storage_location


def _context(db, type_key: str, version: int, node_id: str) -> NodeExecutionContext:
    definition = node_registry.get(type_key, version)
    assert definition is not None
    return NodeExecutionContext(
        db=db,
        payload=ExperimentRunRequest(
            canvas_id="rich_caption_sro_canvas",
            node_id=node_id,
            node_key=type_key,
            node_contract_version=version,
            prompt="",
            model_alias=definition.execution.model_alias,
            parameters={},
            inputs=[],
        ),
        definition=definition,
        request_hash=(node_id * 64)[:64],
        experiment_id=f"experiment_{node_id}",
    )


def _artifact_json(record: ArtifactRecord) -> dict:
    bucket, key = storage_location(record.uri, record.metadata_json)
    return json.loads(get_storage().get_bytes(bucket=bucket, key=key))


def test_rich_caption_sro_contracts_keep_design_layout_and_render_separate():
    design = node_registry.get("subtitle.design", 1)
    layout_v2 = node_registry.get("subtitle.layout", 2)
    layout_v3 = node_registry.get("subtitle.layout", 3)
    burn_v1 = node_registry.get("video.caption_burn", 1)
    burn_v2 = node_registry.get("video.caption_burn", 2)
    assert all((design, layout_v2, layout_v3, burn_v1, burn_v2))
    assert [port.type for port in design.ports.inputs] == ["data.subtitle.v1"]
    assert design.ports.outputs[0].type == "data.caption_document.v1"
    assert [port.type for port in layout_v2.ports.inputs] == ["data.caption_document.v1", "media.video.v1"]
    assert layout_v2.ports.outputs[0].type == "data.caption_layout.v2"
    assert [port.type for port in burn_v1.ports.inputs] == ["media.video.v1", "data.caption_layout.v2"]
    assert [port.type for port in layout_v3.ports.inputs] == ["data.caption_document.v1", "data.media_frame.v1"]
    assert layout_v3.ports.outputs[0].type == "data.caption_layout.v3"
    assert [port.type for port in burn_v2.ports.inputs] == ["media.video.v1", "data.caption_layout.v3"]
    assert burn_v1.config_schema["properties"] == burn_v2.config_schema["properties"] == {}
    assert design.execution.kind == "human_gate"
    assert design.execution.approval_schema["required"] == ["caption_document"]


def test_rich_caption_sro_executors_snapshot_each_boundary(client: TestClient, monkeypatch):
    del client
    monkeypatch.setattr(rich_caption_module, "_probe", lambda _: {
        "streams": [{"codec_type": "video", "width": 360, "height": 640}],
        "format": {"duration": "4.0"},
    })
    document_config = {
        "schema_version": "caption.document.v1",
        "default_style": {"font_size": 54, "color": "#FFFFFF"},
        "content": {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "[00:00-00:04] SRO caption"}]}]},
    }
    with SessionLocal() as db:
        subtitle = create_artifact(
            db, "Subtitle", schema_id="subtitle.srt.v1",
            content=b"1\n00:00:00,000 --> 00:00:04,000\nSRO caption\n",
            content_type="application/x-subrip", filename="subtitle.srt",
        )
        video = create_artifact(
            db, "Video", schema_id="video.source.v1",
            content=b"fixture-video", content_type="video/mp4", filename="video.mp4",
        )
        db.flush()
        design_result = SubtitleDesignExecutor().execute(
            _context(db, "subtitle.design", 1, "design"),
            {"caption_document": document_config},
            [{"type": "Subtitle", "artifact_ids": [subtitle.id]}],
        )
        document_record = db.get(ArtifactRecord, design_result.output_artifact_ids[0])
        assert document_record is not None
        document = _artifact_json(document_record)
        assert document_record.schema_id == "caption.document.v1"
        assert document["cues"][0]["runs"][0]["text"] == "SRO caption"

        layout_result = RichSubtitleLayoutExecutor().execute(
            _context(db, "subtitle.layout", 2, "layout"),
            {"aspect_ratio": "9:16", "frame_x": 0.06, "frame_y": 0.68, "frame_width": 0.88, "frame_height": 0.28, "align": "center"},
            [
                {"type": "CaptionDocument", "artifact_ids": [document_record.id]},
                {"type": "Video", "artifact_ids": [video.id]},
            ],
        )
        layout_record = db.get(ArtifactRecord, layout_result.output_artifact_ids[0])
        assert layout_record is not None
        layout = _artifact_json(layout_record)
        assert layout_record.schema_id == "subtitle.layout.v2"
        assert layout["source"]["artifact_id"] == document_record.id
        assert layout["canvas"]["video_sha256"] == video.sha256
        assert layout["frame"] == {"x": 0.06, "y": 0.68, "width": 0.88, "height": 0.28}

        monkeypatch.setattr(rich_caption_module, "_render_captioned_video", lambda *_: (b"captioned-video", {"width": 360, "height": 640}))
        burn_result = VideoCaptionBurnExecutor().execute(
            _context(db, "video.caption_burn", 1, "burn"),
            {},
            [
                {"type": "Video", "artifact_ids": [video.id]},
                {"type": "CaptionLayout", "artifact_ids": [layout_record.id]},
            ],
        )
        rendered = db.get(ArtifactRecord, burn_result.output_artifact_ids[0])
        assert rendered is not None
        assert rendered.schema_id == "video.captioned.v1"
        assert document_record.id in rendered.input_artifact_ids
        assert rendered.metadata_json["caption_layout"]["schema_version"] == "subtitle.layout.v2"


def test_frame_aware_caption_layout_snapshots_shared_media_frame_for_burn_v2(client: TestClient, monkeypatch):
    del client
    document_config = {
        "schema_version": "caption.document.v1",
        "default_style": {"font_size": 54, "color": "#FFFFFF"},
        "content": {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "[00:00-00:04] Frame-aware caption"}]}]},
    }
    media_frame_payload = {
        "schema_version": "layout.media_frame.v1",
        "canvas": {"aspect_ratio": "9:16", "resolution": "1080p", "background_color": "#11100E"},
        "frame": {"x": 0, "y": 0.1305, "width": 1, "height": 0.6346, "media_fit": "cover"},
    }
    with SessionLocal() as db:
        subtitle = create_artifact(
            db, "Subtitle", schema_id="subtitle.srt.v1",
            content=b"1\n00:00:00,000 --> 00:00:04,000\nFrame-aware caption\n",
            content_type="application/x-subrip", filename="subtitle.srt",
        )
        video = create_artifact(
            db, "Video", schema_id="video.source.v1",
            content=b"fixture-video", content_type="video/mp4", filename="video.mp4",
        )
        media_frame = create_artifact(
            db, "MediaFrame", schema_id="layout.media_frame.v1",
            content=json.dumps(media_frame_payload).encode(), content_type="application/json", filename="media-frame.json",
        )
        db.flush()
        design_result = SubtitleDesignExecutor().execute(
            _context(db, "subtitle.design", 1, "frame_design"),
            {"caption_document": document_config},
            [{"type": "Subtitle", "artifact_ids": [subtitle.id]}],
        )
        document_record = db.get(ArtifactRecord, design_result.output_artifact_ids[0])
        assert document_record is not None

        layout_result = RichSubtitleLayoutExecutor().execute(
            _context(db, "subtitle.layout", 3, "frame_layout"),
            {"frame_x": 0.06, "frame_y": 0.78, "frame_width": 0.88, "frame_height": 0.18, "align": "center"},
            [
                {"type": "CaptionDocument", "artifact_ids": [document_record.id]},
                {"type": "MediaFrame", "artifact_ids": [media_frame.id]},
            ],
        )
        layout_record = db.get(ArtifactRecord, layout_result.output_artifact_ids[0])
        assert layout_record is not None
        layout = _artifact_json(layout_record)
        assert layout_record.schema_id == "subtitle.layout.v3"
        assert layout["canvas"] == {
            "media_frame_artifact_id": media_frame.id,
            "media_frame_sha256": media_frame.sha256,
            "aspect_ratio": "9:16",
            "resolution": "1080p",
            "background_color": "#11100E",
            "width": 1080,
            "height": 1920,
        }
        assert layout["media_frame"] == media_frame_payload["frame"]
        assert layout["caption_frame"] == {"x": 0.06, "y": 0.78, "width": 0.88, "height": 0.18}
        assert media_frame.id in layout_record.input_artifact_ids

        monkeypatch.setattr(rich_caption_module, "_render_captioned_video", lambda *_: (b"captioned-video", {"width": 1080, "height": 1920}))
        burn_result = VideoCaptionBurnExecutor().execute(
            _context(db, "video.caption_burn", 2, "frame_burn"),
            {},
            [
                {"type": "Video", "artifact_ids": [video.id]},
                {"type": "CaptionLayout", "artifact_ids": [layout_record.id]},
            ],
        )
        rendered = db.get(ArtifactRecord, burn_result.output_artifact_ids[0])
        assert rendered is not None
        assert rendered.schema_id == "video.captioned.v2"
        assert layout_record.id in rendered.input_artifact_ids
        assert rendered.metadata_json["caption_layout"]["schema_version"] == "subtitle.layout.v3"
