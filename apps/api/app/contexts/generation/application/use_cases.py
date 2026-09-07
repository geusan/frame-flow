from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .ports import GenerationOperations


@dataclass(frozen=True)
class CreateGenerationBriefCommand:
    values: dict[str, Any]


class GenerationApplication:
    def __init__(self, operations: "GenerationOperations") -> None:
        self._operations = operations

    def create_brief(self, command: CreateGenerationBriefCommand) -> dict[str, Any]:
        return self._operations.create_brief(command)
