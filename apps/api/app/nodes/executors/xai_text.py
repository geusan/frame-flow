from __future__ import annotations

import os
from typing import Any

from ...project_skills import project_skill_system_prompt
from ...providers_xai import XAI_LIVE_REVISION, get_xai_text_services
from ...service import create_artifact
from ..contracts import NodeExecutionContext, NodeExecutionResult
from ..port_types import port_type_registry


class XAITextCapabilityExecutor:
    def supports(self, context: NodeExecutionContext) -> bool:
        return (
            context.definition.execution.kind == "provider"
            and context.payload.model_alias.startswith("xai.text.")
            and os.getenv("GENERATION_PROVIDER_MODE", "live").strip().lower() == "live"
        )

    def execute(
        self,
        context: NodeExecutionContext,
        resolved_node_config: dict[str, Any],
        typed_inputs: list[dict[str, Any]],
    ) -> NodeExecutionResult:
        if not self.supports(context):
            raise RuntimeError("xAI text capability does not support this execution context")
        prompt = context.payload.prompt.strip()
        if not prompt:
            raise ValueError("xAI text generation requires a connected Prompt")
        artifact_contract = context.definition.artifact_contract
        skill_id = str(resolved_node_config.get("skill_id") or "")
        instructions = (
            project_skill_system_prompt(skill_id, str(resolved_node_config.get("skill_version") or "") or None)
            if skill_id
            else "Write only the final narration script for a short-form video. Preserve factual meaning, use natural spoken language, and do not add meta commentary."
            if artifact_contract.primary_type == "Script"
            else "Transform the user's prompt as requested. Return only the useful final text without meta commentary."
        )
        generated = get_xai_text_services().generate(
            model_alias=context.payload.model_alias,
            prompt=prompt,
            instructions=instructions,
            reasoning_effort="high",
            timeout_seconds=300,
            prompt_cache_key=context.request_hash,
        )
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
                "execution_mode": XAI_LIVE_REVISION,
                "immutable": True,
                "source": "node_executor_registry",
                "provider": "xai",
                "model_alias": context.payload.model_alias,
                "exact_model_id": generated.exact_model_id,
                "normalized_config": resolved_node_config,
                "output_role": artifact_contract.output_role,
                "usage": {"input_tokens": generated.input_tokens, "output_tokens": generated.output_tokens},
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
