from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ...contexts.administration.application import AdministrationApplication
from ...nodes import node_registry
from ...nodes.port_types import port_type_registry
from ..dependencies import get_administration_application


router = APIRouter(tags=["system"])


@router.get("/health")
def health(
    application: AdministrationApplication = Depends(get_administration_application),
) -> dict[str, Any]:
    return application.health()


@router.get("/node-definitions")
def list_node_definitions(include_inactive: bool = False) -> list[dict[str, Any]]:
    return [definition.public_payload() for definition in node_registry.list(lifecycle=None if include_inactive else "ACTIVE")]


@router.get("/node-port-types")
def list_node_port_types() -> dict[str, Any]:
    return port_type_registry.model_dump(mode="json")


@router.get("/workspace/summary")
def workspace_summary(
    application: AdministrationApplication = Depends(get_administration_application),
) -> dict[str, Any]:
    return application.workspace_summary()
