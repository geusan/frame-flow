from __future__ import annotations

import html
import io
import math
import struct
import subprocess
import tempfile
import wave
from pathlib import Path


def render_image_svg(prompt: str, exact_model_id: str, digest: str) -> bytes:
    title = html.escape(prompt.strip()[:56] or "Untitled experiment")
    model = html.escape(exact_model_id)
    hue = int(digest[:4], 16) % 360
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 720 960">
    <defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop stop-color="hsl({hue} 42% 20%)"/><stop offset="1" stop-color="hsl({(hue + 70) % 360} 48% 50%)"/></linearGradient></defs>
    <rect width="720" height="960" fill="url(#g)"/><circle cx="570" cy="180" r="230" fill="#fff" opacity=".1"/>
    <path d="M0 760 C170 610 320 760 480 570 S650 500 720 420 V960 H0Z" fill="#090b10" opacity=".48"/>
    <text x="48" y="820" fill="#fff" font-family="Arial,sans-serif" font-size="34" font-weight="700">{title}</text>
    <text x="50" y="872" fill="#fff" opacity=".72" font-family="Arial,sans-serif" font-size="20">{model}</text>
    <text x="50" y="910" fill="#fff" opacity=".52" font-family="monospace" font-size="16">experiment {digest[:12]}</text>
    </svg>'''
    return svg.encode()


def render_video_mp4(digest: str, duration_seconds: int = 6) -> bytes:
    color = digest[:6]
    frequency = 220 + int(digest[6:10], 16) % 220
    with tempfile.TemporaryDirectory(prefix="frameflow-preview-") as temp_dir:
        output = Path(temp_dir) / "preview.mp4"
        command = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"color=c=0x{color}:s=360x640:r=24:d={duration_seconds}",
            "-f", "lavfi", "-i", f"sine=frequency={frequency}:sample_rate=24000:duration={duration_seconds}",
            "-shortest", "-c:v", "libx264", "-preset", "veryfast", "-crf", "30",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "64k", "-movflags", "+faststart",
            str(output),
        ]
        try:
            subprocess.run(command, check=True, capture_output=True, text=True, timeout=45)
        except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            detail = getattr(exc, "stderr", None) or str(exc)
            raise RuntimeError(f"could not create fixture video: {detail}") from exc
        return output.read_bytes()


def render_audio_wav(digest: str, duration_seconds: int = 3, sample_rate: int = 24_000) -> bytes:
    frequency = 180 + int(digest[:6], 16) % 260
    frames = bytearray()
    total_samples = duration_seconds * sample_rate
    for index in range(total_samples):
        fade = min(1.0, index / 1_200, (total_samples - index) / 1_200)
        sample = int(3_200 * fade * math.sin(2 * math.pi * frequency * index / sample_rate))
        frames.extend(struct.pack("<h", sample))
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(frames)
    return buffer.getvalue()
