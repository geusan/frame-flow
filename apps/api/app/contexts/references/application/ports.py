from __future__ import annotations

from typing import Any, Protocol

from .use_cases import CreateReferenceSetCommand, ImportReferenceCommand, InspectReferencesCommand


class ReferenceOperations(Protocol):
    def inspect(self, command: InspectReferencesCommand) -> list[Any]: ...

    def import_reference(self, command: ImportReferenceCommand) -> dict[str, Any]: ...

    def list_references(self) -> list[dict[str, Any]]: ...

    def create_set(self, command: CreateReferenceSetCommand) -> dict[str, Any]: ...
