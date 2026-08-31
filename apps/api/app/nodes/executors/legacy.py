from __future__ import annotations

from typing import Any

from ..contracts import NodeExecutionContext, NodeExecutionResult, NodeExecutor


class LegacyCompatibilityExecutor:
    """Capability registry for immutable contracts naming the legacy executor."""

    def __init__(self, capabilities: tuple[NodeExecutor, ...] = ()) -> None:
        self._capabilities = capabilities

    def supports(self, context: NodeExecutionContext) -> bool:
        return any(_supports(capability, context) for capability in self._capabilities)

    def execute(
        self,
        context: NodeExecutionContext,
        resolved_node_config: dict[str, Any],
        typed_inputs: list[dict[str, Any]],
    ) -> NodeExecutionResult:
        capability = next((item for item in self._capabilities if _supports(item, context)), None)
        if not capability:
            raise RuntimeError("legacy compatibility capability is not registered yet")
        return capability.execute(context, resolved_node_config, typed_inputs)


def _supports(executor: NodeExecutor, context: NodeExecutionContext) -> bool:
    supports = getattr(executor, "supports", None)
    return bool(supports(context)) if callable(supports) else False
