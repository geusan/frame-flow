from __future__ import annotations

import subprocess
from pathlib import Path

from app.reference_analysis import analyze_reference_video


def test_reference_analysis_detects_a_real_cut_and_handles_silent_video(tmp_path: Path):
    source = tmp_path / "cut-source.mp4"
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "color=c=red:s=160x240:r=24:d=1",
        "-f", "lavfi", "-i", "color=c=blue:s=160x240:r=24:d=1",
        "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v]",
        "-map", "[v]", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source),
    ], check=True, capture_output=True, text=True, timeout=60)

    result = analyze_reference_video(
        source.read_bytes(),
        "video/mp4",
        scene_threshold=0.18,
    ).manifest

    assert result["source"]["has_audio"] is False
    assert result["components"]["speech"] == "not_applicable"
    assert result["components"]["music_separation"] == "not_applicable"
    assert result["speech"]["segments"] == []
    assert result["audio"]["music_intervals"] == []
    assert result["audio"]["sound_effects"] == []
    assert len(result["visual"]["shots"]) == 2
    assert result["visual"]["shots"][1]["start_ms"] == 1000
    assert result["visual"]["shots"][1]["transition_in"] == "hard_cut"
