from __future__ import annotations

import struct
import io
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from app.canvas_runs import record_canvas_approval
from app.caption_documents import canonical_caption_document, caption_document_to_ass, materialize_caption_fonts
from app.database import CanvasNodeRunRecord, CanvasRunRecord, FontRecord, SessionLocal
from app.domain import NodeStatus


def test_renderer_uses_file_family_without_mutating_frozen_font_snapshot(client: TestClient, tmp_path):
    from fontTools.ttLib import TTFont
    with TTFont(io.BytesIO(minimal_font()), recalcTimestamp=False, recalcBBoxes=False) as font_file:
        font_file["name"].setName("Renderer Fixture Medium", 1, 3, 1, 0x0409)
        font_file["OS/2"].usWeightClass = 500
        output = io.BytesIO()
        font_file.save(output)
    response = client.post("/fonts", files={"file": ("face.ttf", output.getvalue(), "font/ttf")})
    assert response.status_code == 201
    font = response.json()
    assert font["family_name"] == "Frameflow Test Sans"
    with SessionLocal() as db:
        document = canonical_caption_document(db, {
            "schema_version": "caption.document.v1",
            "default_style": {"font_id": font["id"], "font_size": 54, "color": "#FFFFFF"},
            "content": {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "[00:00-00:03] 실제 글꼴"}]}]},
        })
        before = deepcopy(document)
        aliases = materialize_caption_fonts(db, document, tmp_path / "fonts")
        ass = caption_document_to_ass(document, width=640, height=360, track_style={"align": "center"}, font_family_names=aliases)
    assert aliases[font["id"]] == "Renderer Fixture Medium"
    assert r"\fnRenderer Fixture Medium" in ass
    assert r"\b500\i0" in ass
    assert "Style: Caption,Renderer Fixture Medium," in ass
    assert document == before
    assert next((tmp_path / "fonts").glob("*.ttf")).read_bytes() == output.getvalue()


def _name_table() -> bytes:
    values = [(1, "Frameflow Test Sans"), (2, "Regular"), (6, "FrameflowTestSans-Regular"), (16, "Frameflow Test Sans")]
    strings = b""
    records = []
    for name_id, value in values:
        encoded = value.encode("utf-16-be")
        records.append(struct.pack(">HHHHHH", 3, 1, 0x0409, name_id, len(encoded), len(strings)))
        strings += encoded
    return struct.pack(">HHH", 0, len(records), 6 + 12 * len(records)) + b"".join(records) + strings


def minimal_font() -> bytes:
    head = bytearray(54)
    struct.pack_into(">H", head, 18, 1000)
    hhea = bytearray(36)
    struct.pack_into(">hhh", hhea, 4, 800, -200, 100)
    os2 = bytearray(96)
    struct.pack_into(">H", os2, 4, 400)
    struct.pack_into(">hhh", os2, 68, 780, -220, 80)
    struct.pack_into(">hh", os2, 86, 500, 700)
    tables = [(b"OS/2", bytes(os2)), (b"head", bytes(head)), (b"hhea", bytes(hhea)), (b"name", _name_table())]
    offset = 12 + 16 * len(tables)
    records = []
    payload = bytearray()
    for tag, table in tables:
        padding = (-offset) % 4
        payload.extend(b"\0" * padding)
        offset += padding
        records.append(struct.pack(">4sIII", tag, 0, offset, len(table)))
        payload.extend(table)
        offset += len(table)
    return struct.pack(">4sHHHH", b"\x00\x01\x00\x00", len(tables), 0, 0, 0) + b"".join(records) + bytes(payload)


def register_test_font(client: TestClient) -> dict:
    response = client.post(
        "/fonts",
        files={"file": ("frameflow-test.ttf", minimal_font(), "font/ttf")},
        data={"license_name": "Test fixture license"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_font_registry_stores_an_immutable_face_and_mutable_visual_profile(client: TestClient):
    font = register_test_font(client)
    assert font["created"] is True
    assert font["family_name"] == "Frameflow Test Sans"
    assert font["postscript_name"] == "FrameflowTestSans-Regular"
    assert font["metrics"]["units_per_em"] == 1000
    assert font["css_family"].startswith("ff-font-font-")

    duplicate = client.post(
        "/fonts",
        files={"file": ("renamed.ttf", minimal_font(), "font/ttf")},
    )
    assert duplicate.status_code == 201
    assert duplicate.json()["created"] is False
    assert duplicate.json()["id"] == font["id"]

    updated = client.patch(f"/fonts/{font['id']}", json={
        "display_name": "Caption Fixture",
        "size_adjust": 1.1,
        "baseline_shift": -0.04,
    })
    assert updated.status_code == 200, updated.text
    assert updated.json()["display_name"] == "Caption Fixture"
    assert updated.json()["size_adjust"] == 1.1
    assert updated.json()["sha256"] == font["sha256"]
    assert updated.json()["profile_version"] == 2
    assert updated.json()["supersedes_id"] == font["id"]

    listed = client.get("/fonts").json()
    assert [item["id"] for item in listed] == [updated.json()["id"]]
    content = client.get(f"/artifacts/{font['artifact_id']}/content")
    assert content.status_code == 200
    assert content.content == minimal_font()


def test_caption_document_snapshots_fonts_and_compiles_inline_ass_marks(client: TestClient):
    font = register_test_font(client)
    font = client.patch(f"/fonts/{font['id']}", json={"size_adjust": 1.1}).json()
    document = {
        "schema_version": "caption.document.v1",
        "default_style": {"font_size": 54, "color": "#FFFFFF"},
        "content": {
            "type": "doc",
            "content": [{
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "[00:00-00:03] 안녕 "},
                    {
                        "type": "text",
                        "text": "강조",
                        "marks": [
                            {"type": "bold"},
                            {"type": "italic"},
                            {"type": "textStyle", "attrs": {
                                "color": "#FF3366",
                                "fontId": font["id"],
                                "fontFamily": font["css_family"],
                                "fontSize": "64px",
                            }},
                        ],
                    },
                ],
            }],
        },
    }
    with SessionLocal() as db:
        canonical = canonical_caption_document(db, document)
        ass = caption_document_to_ass(
            canonical,
            width=1080,
            height=1920,
            track_style={"x": 0.5, "y": 0.82, "align": "center", "font_size": 54},
        )
    assert canonical["cues"][0]["start_ms"] == 0
    assert canonical["cues"][0]["end_ms"] == 3000
    assert canonical["cues"][0]["runs"][1]["text"] == "강조"
    assert canonical["fonts"][0]["sha256"] == font["sha256"]
    assert r"\fnFrameflow Test Sans" in ass
    assert r"\fs70.4" in ass
    assert r"\c&H006633FF" in ass
    assert r"\b1\i1" in ass
    assert "WrapStyle: 1" in ass
    assert r"\q1" in ass
    assert r"\q2" not in ass


def test_caption_ass_wraps_by_words_inside_the_frame_and_preserves_manual_breaks(client: TestClient):
    del client
    document = {
        "schema_version": "caption.document.v1",
        "default_style": {"font_size": 54, "color": "#FFFFFF"},
        "content": {
            "type": "doc",
            "content": [{
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "[00:00-00:03] 단어 단위 자동 줄바꿈"},
                    {"type": "hardBreak"},
                    {"type": "text", "text": "수동 줄바꿈"},
                ],
            }],
        },
    }
    with SessionLocal() as db:
        canonical = canonical_caption_document(db, document)
        ass = caption_document_to_ass(
            canonical,
            width=1000,
            height=1000,
            track_style={
                "align": "center",
                "frame": {"x": 0.1, "y": 0.7, "width": 0.8, "height": 0.2},
            },
        )
    assert r"\q1" in ass
    assert r"\N" in ass
    assert ",Caption,,132,132,0,," in ass


def test_caption_document_ignores_the_first_break_after_the_timestamp(client: TestClient):
    del client
    document = {
        "schema_version": "caption.document.v1",
        "default_style": {"font_size": 54, "color": "#FFFFFF"},
        "content": {
            "type": "doc",
            "content": [{
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "[00:00-05:00]"},
                    {"type": "hardBreak"},
                    {"type": "text", "text": "자막1"},
                    {"type": "hardBreak"},
                    {"type": "text", "text": "자막2"},
                    {"type": "hardBreak"},
                    {"type": "text", "text": "자막3"},
                ],
            }],
        },
    }
    with SessionLocal() as db:
        canonical = canonical_caption_document(db, document)
        ass = caption_document_to_ass(
            canonical,
            width=1000,
            height=1000,
            track_style={"x": 0.5, "y": 0.8, "align": "center"},
        )
    text = "".join(run["text"] for run in canonical["cues"][0]["runs"])
    assert text == "자막1\n자막2\n자막3"
    assert r"자막1\N자막2\N자막3" in ass
    assert r"\N자막1" not in ass


def test_caption_document_rejects_lines_without_timestamps(client: TestClient):
    del client
    document = {
        "schema_version": "caption.document.v1",
        "default_style": {"font_size": 54, "color": "#FFFFFF"},
        "content": {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "자막만 있음"}]}]},
    }
    with SessionLocal() as db:
        with pytest.raises(ValueError, match=r"\[MM:SS-MM:SS\]"):
            canonical_caption_document(db, document)


def test_registered_font_can_be_retired_without_deleting_its_artifact(client: TestClient):
    font = register_test_font(client)
    response = client.patch(f"/fonts/{font['id']}", json={"lifecycle": "RETIRED"})
    assert response.status_code == 200
    assert response.json()["lifecycle"] == "RETIRED"
    assert client.get("/fonts").json() == []
    assert len(client.get("/fonts?include_retired=true").json()) == 1
    with SessionLocal() as db:
        record = db.get(FontRecord, font["id"])
        assert record is not None
        assert record.artifact_id == font["artifact_id"]


def _approval_run(run_id: str, node_id: str) -> None:
    with SessionLocal() as db:
        run = CanvasRunRecord(
            id=run_id,
            canvas_id=f"canvas_{run_id}",
            name="Rich caption approval",
            status=NodeStatus.WAITING_INPUT,
            progress=0,
            graph_snapshot={
                "source": "stored_canvas",
                "nodes": [{
                    "id": node_id,
                    "data": {
                        "key": "timeline.compose",
                        "contractVersion": 2,
                        "waitForInput": True,
                        "config": {},
                    },
                }],
                "edges": [],
            },
        )
        run.node_runs.append(CanvasNodeRunRecord(
            id=f"canvasnode_{run_id}",
            run_id=run.id,
            canvas_node_id=node_id,
            node_key="timeline.compose",
            ordinal=0,
            status=NodeStatus.WAITING_INPUT,
            progress=100,
        ))
        db.add(run)
        db.commit()


def test_rich_caption_human_gate_validates_and_snapshots_approval_config(client: TestClient):
    del client
    document = {
        "schema_version": "caption.document.v1",
        "default_style": {"font_size": 54, "color": "#FFFFFF"},
        "content": {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "[00:00-00:03] 자막"}]}]},
    }
    _approval_run("canvasrun_rich_caption", "layout")
    parameters = {
        "caption_x": 0.5,
        "caption_y": 0.82,
        "caption_align": "center",
        "caption_font_size": 54,
        "caption_document": document,
    }
    record_canvas_approval("canvasrun_rich_caption", "layout", parameters)
    with SessionLocal() as db:
        run = db.get(CanvasRunRecord, "canvasrun_rich_caption")
        assert run is not None
        data = run.graph_snapshot["nodes"][0]["data"]
        assert data["config"] == parameters
        assert data["inputApproved"] is True


def test_rich_caption_human_gate_rejects_incomplete_approval(client: TestClient):
    del client
    _approval_run("canvasrun_invalid_caption", "layout")
    with pytest.raises(ValueError, match="caption_document"):
        record_canvas_approval("canvasrun_invalid_caption", "layout", {
            "caption_x": 0.5,
            "caption_y": 0.82,
            "caption_align": "center",
            "caption_font_size": 54,
        })
