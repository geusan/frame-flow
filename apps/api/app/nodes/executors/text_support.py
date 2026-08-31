from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ...project_skills import project_skill_system_prompt
from ...service import create_artifact
from ..contracts import NodeExecutionContext, NodeExecutionResult
from ..port_types import port_type_registry


@dataclass(frozen=True)
class TextProviderResult:
    text: str
    provider_request_id: str
    exact_model_id: str
    cost_usd: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


def text_instructions(context: NodeExecutionContext, config: dict[str, Any]) -> str:
    skill_id = str(config.get("skill_id") or "")
    if skill_id:
        return project_skill_system_prompt(skill_id, str(config.get("skill_version") or "") or None)
    if context.definition.artifact_contract.primary_type == "Script":
        return "Write only the final narration script for a short-form video. Preserve factual meaning, use natural spoken language, and do not add meta commentary."
    return "Transform the user's prompt as requested. Return only the useful final text without meta commentary."


def complete_text_execution(
    context: NodeExecutionContext,
    config: dict[str, Any],
    typed_inputs: list[dict[str, Any]],
    generated: TextProviderResult,
    *,
    provider: str,
    execution_revision: str,
) -> NodeExecutionResult:
    artifact_contract = context.definition.artifact_contract
    input_artifact_ids, input_roles = _input_lineage(context, typed_inputs)
    title = (
        "Generated script"
        if artifact_contract.primary_type == "Script"
        else "Generated master prompt"
        if artifact_contract.schema_id == "prompt.master.v1"
        else "Generated text"
    )
    filename = "script.txt" if artifact_contract.primary_type == "Script" else "master-prompt.txt" if artifact_contract.schema_id == "prompt.master.v1" else "result.txt"
    artifact = create_artifact(
        context.db,
        artifact_contract.primary_type,
        schema_id=artifact_contract.schema_id,
        input_artifact_ids=input_artifact_ids,
        input_artifact_roles=input_roles,
        metadata={
            "experiment_id": context.experiment_id,
            "request_hash": context.request_hash,
            "execution_mode": execution_revision,
            "immutable": True,
            "source": "node_executor_registry",
            "provider": provider,
            "model_alias": context.payload.model_alias,
            "exact_model_id": generated.exact_model_id,
            "normalized_config": config,
            "output_role": artifact_contract.output_role,
            **generated.metadata,
        },
        content=generated.text.encode(),
        content_type="text/plain",
        filename=filename,
    )
    context.db.flush()
    return NodeExecutionResult(
        output={"kind": "text", "title": title, "text": generated.text},
        output_artifact_ids=[artifact.id],
        provider_request_id=generated.provider_request_id,
        cost_usd=generated.cost_usd,
        metadata={
            "artifact_type": artifact_contract.primary_type,
            "schema_id": artifact_contract.schema_id,
            "input_artifact_ids": input_artifact_ids,
            "lineage_roles": input_roles,
            "retryable": False,
            "exact_model_id": generated.exact_model_id,
        },
    )


def _input_lineage(context: NodeExecutionContext, typed_inputs: list[dict[str, Any]]) -> tuple[list[str], dict[str, str]]:
    artifact_ids: list[str] = []
    roles: dict[str, str] = {}
    for item in typed_inputs:
        legacy_type = str(item.get("type") or "")
        port = next(
            (candidate for candidate in context.definition.ports.inputs if port_type_registry.get(candidate.type).legacy_type == legacy_type),
            None,
        )
        role = context.definition.artifact_contract.input_roles.get(port.type, "supporting_input") if port else "supporting_input"
        values = [*(item.get("artifact_ids") or []), *([item.get("artifact_id")] if item.get("artifact_id") else [])]
        for value in values:
            artifact_id = str(value)
            if artifact_id not in artifact_ids:
                artifact_ids.append(artifact_id)
                roles[artifact_id] = role
    return artifact_ids, roles
