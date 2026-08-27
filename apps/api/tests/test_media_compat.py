import subprocess
from pathlib import Path

from app.media_compat import ensure_browser_video
from app.media_preview import render_video_mp4


def test_h264_video_is_reused_without_transcoding():
    source = render_video_mp4("abcdef1234567890", duration_seconds=1)
    result = ensure_browser_video(source, "video/mp4")
    assert result.transcoded is False
    assert result.video_codec == "h264"
    assert result.content == source
    assert result.duration_ms > 0


def test_hevc_video_is_transcoded_to_h264(tmp_path: Path):
    source = tmp_path / "source.mp4"
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "color=c=black:s=64x64:d=0.25",
        "-c:v", "libx265", "-tag:v", "hvc1", "-pix_fmt", "yuv420p",
        "-x265-params", "pools=1:log-level=error", str(source),
    ], check=True, capture_output=True, text=True, timeout=60)
    result = ensure_browser_video(source.read_bytes(), "video/mp4")
    assert result.transcoded is True
    assert result.video_codec == "h264"
    assert result.content_type == "video/mp4"
    assert result.content != source.read_bytes()
