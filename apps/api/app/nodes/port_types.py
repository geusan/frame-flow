from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator


PORT_TYPE_PATTERN = r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+\.v[1-9][0-9]*$"


class PortTypeDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=PORT_TYPE_PATTERN)
    label: str = Field(min_length=1)
    legacy_type: str = Field(min_length=1)
    compatible_with: list[str] = Field(default_factory=list)


class PortTypeRegistry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    types: list[PortTypeDefinition] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_registry(self) -> "PortTypeRegistry":
        if self.schema_version != "port-types.v1":
            raise ValueError("unsupported Port Type Registry schema")
        ids = [item.id for item in self.types]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate Port type ID")
        known = set(ids)
        unknown = sorted({target for item in self.types for target in item.compatible_with if target not in known})
        if unknown:
            raise ValueError(f"unknown compatible Port types: {', '.join(unknown)}")
        return self

    @property
    def ids(self) -> set[str]:
        return {item.id for item in self.types}

    def get(self, type_id: str) -> PortTypeDefinition | None:
        return next((item for item in self.types if item.id == type_id), None)

    def compatible(self, source_type: str, target_type: str) -> bool:
        if source_type == target_type:
            return True
        source = self.get(source_type)
        return bool(source and target_type in source.compatible_with)


@lru_cache(maxsize=1)
def load_port_type_registry() -> PortTypeRegistry:
    path = Path(__file__).with_name("port_types.v1.json")
    return PortTypeRegistry.model_validate(json.loads(path.read_text()))


port_type_registry = load_port_type_registry()
