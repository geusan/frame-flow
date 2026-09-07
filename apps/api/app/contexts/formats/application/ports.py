from __future__ import annotations

from typing import Any, Protocol

from .use_cases import (
    CreateExtractionRecipeCommand,
    CreateFormatRunCommand,
    CreateVariantsCommand,
    MergeFormatsCommand,
)


class FormatOperations(Protocol):
    def create_recipe(self, command: CreateExtractionRecipeCommand) -> dict[str, Any]: ...

    def create_run(self, command: CreateFormatRunCommand) -> dict[str, Any]: ...

    def get(self, format_id: str) -> dict[str, Any]: ...

    def list(self) -> list[dict[str, Any]]: ...

    def create_variants(self, command: CreateVariantsCommand) -> list[dict[str, Any]]: ...

    def merge(self, command: MergeFormatsCommand) -> dict[str, Any]: ...
