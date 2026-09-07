from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .ports import AdministrationOperations


@dataclass(frozen=True)
class FontRegistrationCommand:
    filename: str
    content_type: str
    content: bytes
    display_name: str | None
    license_name: str
    created_by: str


@dataclass(frozen=True)
class FontUpdateCommand:
    font_id: str
    values: dict[str, Any]


@dataclass(frozen=True)
class ProviderSettingsCommand:
    provider: str
    enabled: bool
    auth_method: str | None
    values: dict[str, str] = field(default_factory=dict)
    clear_fields: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SkillRegistrationCommand:
    filename: str
    content: bytes
    created_by: str
    expected_id: str | None = None


class AdministrationApplication:
    def __init__(self, operations: "AdministrationOperations") -> None:
        self._operations = operations

    def list_fonts(self, include_retired: bool = False) -> list[dict[str, Any]]:
        return self._operations.list_fonts(include_retired)

    def register_font(self, command: FontRegistrationCommand) -> dict[str, Any]:
        return self._operations.register_font(command)

    def update_font(self, command: FontUpdateCommand) -> dict[str, Any]:
        return self._operations.update_font(command)

    def list_provider_settings(self) -> list[dict[str, Any]]:
        return self._operations.list_provider_settings()

    def update_provider_settings(self, command: ProviderSettingsCommand) -> dict[str, Any]:
        return self._operations.update_provider_settings(command)

    def list_models(self) -> list[dict[str, Any]]:
        return self._operations.list_models()

    def list_skills(self, include_disabled: bool = False) -> list[dict[str, Any]]:
        return self._operations.list_skills(include_disabled)

    def register_skill(self, command: SkillRegistrationCommand) -> dict[str, Any]:
        return self._operations.register_skill(command)

    def list_skill_versions(self, skill_id: str) -> list[dict[str, Any]]:
        return self._operations.list_skill_versions(skill_id)

    def activate_skill_version(self, skill_id: str, version_number: int) -> dict[str, Any]:
        return self._operations.activate_skill_version(skill_id, version_number)

    def set_skill_enabled(self, skill_id: str, enabled: bool) -> dict[str, Any]:
        return self._operations.set_skill_enabled(skill_id, enabled)

    def health(self) -> dict[str, Any]:
        return self._operations.health()

    def workspace_summary(self) -> dict[str, Any]:
        return self._operations.workspace_summary()
