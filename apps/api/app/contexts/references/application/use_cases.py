from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .ports import ReferenceOperations


@dataclass(frozen=True)
class InspectReferencesCommand:
    urls: list[str]


@dataclass(frozen=True)
class ImportReferenceCommand:
    values: dict[str, Any]


@dataclass(frozen=True)
class CreateReferenceSetCommand:
    name: str
    reference_ids: list[str]


class ReferenceApplication:
    def __init__(self, operations: "ReferenceOperations") -> None:
        self._operations = operations

    def inspect(self, command: InspectReferencesCommand) -> list[Any]:
        return self._operations.inspect(command)

    def import_reference(self, command: ImportReferenceCommand) -> dict[str, Any]:
        return self._operations.import_reference(command)

    def list_references(self) -> list[dict[str, Any]]:
        return self._operations.list_references()

    def create_set(self, command: CreateReferenceSetCommand) -> dict[str, Any]:
        return self._operations.create_set(command)
