from __future__ import annotations

from sqlalchemy.orm import Session

import tempfile
from pathlib import Path

from ...canvas_operations import (
    _build_subtitles,
    _duration_seconds,
    _edit_videos,
    _extract_speech_audio,
    _probe,
    _qc_report,
    _replace_audio,
    _render_timeline,
    _segments_to_srt,
    _synthesized_wav,
    _timeline,
    _write_artifact,
)
from ...caption_documents import canonical_caption_document, materialize_caption_fonts
from ...nodes.contracts import NodeArtifactContent


class SqlAlchemyNodeMediaRuntime:
    def __init__(self, session: Session) -> None:
        self._session = session

    def render_timeline(self, timeline: NodeArtifactContent) -> bytes:
        return _render_timeline(self._session, timeline)  # type: ignore[arg-type]

    def build_timeline(self, artifacts: list[NodeArtifactContent], config: dict) -> dict:
        return _timeline(artifacts, config)  # type: ignore[arg-type]

    def edit_videos(self, artifacts: list[NodeArtifactContent], config: dict) -> bytes:
        return _edit_videos(artifacts, config)  # type: ignore[arg-type]

    def replace_audio(
        self,
        video: NodeArtifactContent,
        audio: NodeArtifactContent,
        subtitle: NodeArtifactContent | None = None,
        *,
        language: str = "und",
    ) -> bytes:
        return _replace_audio(video, audio, subtitle, language=language)  # type: ignore[arg-type]

    def media_duration(self, artifact: NodeArtifactContent) -> float:
        with tempfile.TemporaryDirectory(prefix="frameflow-media-duration-") as temp_dir:
            path = _write_artifact(Path(temp_dir), artifact, 0)  # type: ignore[arg-type]
            return _duration_seconds(_probe(path))

    def extract_speech_audio(self, video: NodeArtifactContent) -> tuple[bytes, int]:
        return _extract_speech_audio(video)  # type: ignore[arg-type]

    def synthesized_wav(self, speech: object) -> bytes:
        return _synthesized_wav(speech)  # type: ignore[arg-type]

    def build_subtitles(self, script: str, duration: float) -> bytes:
        return _build_subtitles(script, duration)

    def segments_to_srt(self, segments: list) -> bytes:
        return _segments_to_srt(segments)

    def quality_report(self, video: NodeArtifactContent, config: dict) -> dict:
        return _qc_report(video, config)  # type: ignore[arg-type]

    def canonical_caption_document(self, document: dict) -> dict:
        return canonical_caption_document(self._session, document)

    def materialize_caption_fonts(self, document: dict, directory: object) -> dict[str, str]:
        return materialize_caption_fonts(self._session, document, directory)  # type: ignore[arg-type]
