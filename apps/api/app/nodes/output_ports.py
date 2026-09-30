from __future__ import annotations

from typing import Iterable, Protocol

from .contracts import NodeDefinition, NodePort
from .port_types import port_type_registry


class OutputArtifact(Protocol):
    id: str
    type: str


def selected_output_port(definition: NodeDefinition, handle: str | None) -> NodePort | None:
    if not handle or handle == "output":
        return definition.ports.outputs[0]
    return next((port for port in definition.ports.outputs if handle in {port.key, f"output-{port.key}"}), None)


def artifacts_for_output_port(definition: NodeDefinition, port: NodePort, artifacts: Iterable[OutputArtifact]) -> list[str]:
    """Resolve current typed artifact contracts without coupling to persistence."""
    artifact_type = port_type_registry.get(port.type).legacy_type
    allowed_types = {artifact_type}
    if port == definition.ports.outputs[0]:
        allowed_types.add(definition.artifact_contract.primary_type)
    if artifact_type == "Video":
        allowed_types.update({"FinalVideo", "VideoPreview"})
    return [artifact.id for artifact in artifacts if artifact_type in {"ReferenceAsset", "Any"} or artifact.type in allowed_types]
