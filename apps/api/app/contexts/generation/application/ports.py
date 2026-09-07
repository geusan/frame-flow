from __future__ import annotations

from typing import Any, Protocol

from .use_cases import CreateGenerationBriefCommand


class GenerationOperations(Protocol):
    def create_brief(self, command: CreateGenerationBriefCommand) -> dict[str, Any]: ...
