from __future__ import annotations

from sqlalchemy.orm import Session

from ...canvas_operations import _render_timeline
from ...nodes.contracts import NodeArtifactContent


class SqlAlchemyNodeMediaRuntime:
    def __init__(self, session: Session) -> None:
        self._session = session

    def render_timeline(self, timeline: NodeArtifactContent) -> bytes:
        return _render_timeline(self._session, timeline)  # type: ignore[arg-type]
