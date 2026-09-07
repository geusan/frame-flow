from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .ports import FormatOperations


@dataclass(frozen=True)
class CreateExtractionRecipeCommand:
    values: dict[str, Any]


@dataclass(frozen=True)
class CreateFormatRunCommand:
    values: dict[str, Any]


@dataclass(frozen=True)
class CreateVariantsCommand:
    format_id: str
    values: dict[str, Any]


@dataclass(frozen=True)
class MergeFormatsCommand:
    values: dict[str, Any]


class FormatApplication:
    def __init__(self, operations: "FormatOperations") -> None:
        self._operations = operations

    def create_recipe(self, command: CreateExtractionRecipeCommand) -> dict[str, Any]:
        return self._operations.create_recipe(command)

    def create_run(self, command: CreateFormatRunCommand) -> dict[str, Any]:
        return self._operations.create_run(command)

    def get(self, format_id: str) -> dict[str, Any]:
        return self._operations.get(format_id)

    def list(self) -> list[dict[str, Any]]:
        return self._operations.list()

    def create_variants(self, command: CreateVariantsCommand) -> list[dict[str, Any]]:
        return self._operations.create_variants(command)

    def merge(self, command: MergeFormatsCommand) -> dict[str, Any]:
        return self._operations.merge(command)
