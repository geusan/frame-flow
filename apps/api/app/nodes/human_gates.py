from __future__ import annotations

from typing import Literal

from .contracts import NodeDefinition


HumanGateMode = Literal["approve", "select_artifact"]


def human_gate_mode(definition: NodeDefinition | None) -> HumanGateMode | None:
    if definition is None or definition.execution.kind != "human_gate":
        return None
    if definition.execution.approval_schema is not None:
        return "approve"
    output_types = {port.type for port in definition.ports.outputs}
    selects_existing_artifact = any(
        port.multiple and port.type in output_types
        for port in definition.ports.inputs
    )
    return "select_artifact" if selects_existing_artifact else "approve"
