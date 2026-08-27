from pathlib import Path

from worker.media import build_provenance_manifest, quality_check, render_timeline


def test_ffmpeg_vertical_golden_contract(tmp_path: Path):
    timeline = {
        "version": "timeline.v1",
        "width": 270,
        "height": 480,
        "fps": 24,
        "duration_ms": 600,
        "video_tracks": [],
        "audio_tracks": [],
        "caption_tracks": [],
        "effects": [],
    }
    result = render_timeline(timeline, tmp_path / "preview.mp4")
    qc = quality_check(result, target_width=270, target_height=480, target_duration_ms=600, tolerance_ms=100)
    assert qc.passed
    assert len(qc.sha256) == 64


def test_provenance_explicitly_denies_reference_original_use():
    manifest = build_provenance_manifest(
        final_artifact_id="art_final",
        format_id="fmt_1",
        parent_reference_ids=["ref_1"],
        prompt_versions=["prompt@4"],
        model_ids=["veo-3.1-fast-generate-001"],
        artifact_ids=["art_clip"],
        qc_report_artifact_id="art_qc",
    )
    assert manifest["reference_originals_used"] is False
    assert manifest["reference_isolation_enforced"] is True

