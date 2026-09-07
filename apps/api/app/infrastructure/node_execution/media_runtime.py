from __future__ import annotations

from sqlalchemy.orm import Session

from ...canvas_operations import _render_timeline
from ...caption_documents import canonical_caption_document, materialize_caption_fonts
from ...nodes.contracts import NodeArtifactContent


class SqlAlchemyNodeMediaRuntime:
    def __init__(self, session: Session) -> None:
        self._session = session

    def render_timeline(self, timeline: NodeArtifactContent) -> bytes:
        return _render_timeline(self._session, timeline)  # type: ignore[arg-type]

    def canonical_caption_document(self, document: dict) -> dict:
        return canonical_caption_document(self._session, document)

    def materialize_caption_fonts(self, document: dict, directory: object) -> None:
        materialize_caption_fonts(self._session, document, directory)  # type: ignore[arg-type]
