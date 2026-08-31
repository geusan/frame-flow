from __future__ import annotations

from typing import Any

from ..contracts import NodeExecutionContext, NodeExecutionResult


class LegacyCompatibilityExecutor:
    """Marker executor for contracts that still use the pre-registry runtime.

    The experiment dispatcher recognizes this adapter and invokes the existing
    provider/local implementation. It remains registered so every manifest has
    an explicit executor during the strangler migration.
    """

    def execute(
        self,
        context: NodeExecutionContext,
        resolved_node_config: dict[str, Any],
        typed_inputs: list[dict[str, Any]],
    ) -> NodeExecutionResult:
        del context, resolved_node_config, typed_inputs
        raise RuntimeError("legacy compatibility Nodes must use the legacy runtime adapter")
