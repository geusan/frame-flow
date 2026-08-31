from __future__ import annotations

from typing import Any

from ...local_subscription_agents import LOCAL_SUBSCRIPTION_AGENT_REVISION, run_local_subscription_agent
from ...provider_settings import get_provider_record, provider_auth_method_key, provider_is_configured
from ...providers import model_id_for_alias
from ...service import create_artifact
from ...storage import artifact_content_url
from ..contracts import NodeExecutionContext, NodeExecutionResult


LOCAL_SUBSCRIPTION_AGENT_SCHEMA = "agent.response.v1"


class LocalSubscriptionAgentExecutor:
    def execute(
        self,
        context: NodeExecutionContext,
        resolved_node_config: dict[str, Any],
        typed_inputs: list[dict[str, Any]],
    ) -> NodeExecutionResult:
        if context.definition.execution.revision != LOCAL_SUBSCRIPTION_AGENT_REVISION:
            raise RuntimeError("Local subscription agent revision does not match its Node Definition")
        prompt = context.payload.prompt.strip()
        if not prompt:
            raise ValueError("Local Subscription Agent requires a connected Prompt")

        model_alias = str(resolved_node_config["model_alias"])
        provider_key, required_auth_method = (
            ("openai", "chatgpt_oauth")
            if model_alias.startswith("chatgpt.local.")
            else ("claude", "setup_token")
        )
        provider_record = get_provider_record(context.db, provider_key)
        if not provider_record or provider_auth_method_key(provider_record) != required_auth_method:
            raise RuntimeError(f"Select {required_auth_method} for the {provider_key} provider in Settings")
        if not provider_is_configured(provider_record):
            raise RuntimeError(f"The {provider_key} local subscription is not ready on the execution host")

        setup_token = str((provider_record.secrets or {}).get("setup_token") or "") if provider_key == "claude" else ""
        exact_model_id = model_id_for_alias(model_alias)
        if not exact_model_id:
            raise ValueError(f"Local subscription model alias is not registered: {model_alias}")
        executed = run_local_subscription_agent(
            model_alias=model_alias,
            prompt=prompt,
            instructions=str(resolved_node_config["instructions"]),
            timeout_seconds=int(resolved_node_config["timeout_seconds"]),
            setup_token=setup_token,
        )

        input_artifact_ids = _input_artifact_ids(typed_inputs)
        input_roles = {artifact_id: "supporting_input" for artifact_id in input_artifact_ids}
        artifact = create_artifact(
            context.db,
            "Text",
            schema_id=LOCAL_SUBSCRIPTION_AGENT_SCHEMA,
            input_artifact_ids=input_artifact_ids,
            input_artifact_roles=input_roles,
            metadata={
                "experiment_id": context.experiment_id,
                "request_hash": context.request_hash,
                "execution_mode": LOCAL_SUBSCRIPTION_AGENT_REVISION,
                "immutable": True,
                "source": "local_subscription_agent",
                "provider": provider_key,
                "client": executed.client,
                "model_alias": model_alias,
                "exact_model_id": exact_model_id,
                "normalized_config": resolved_node_config,
                **executed.metadata,
            },
            content=executed.text.encode(),
            content_type="text/plain",
            filename="agent-response.txt",
        )
        context.db.flush()
        return NodeExecutionResult(
            output={
                "kind": "text",
                "title": "Local subscription response",
                "text": executed.text,
                "url": artifact_content_url(artifact.id),
            },
            output_artifact_ids=[artifact.id],
            provider_request_id=executed.provider_request_id,
            cost_usd=0.0,
            metadata={
                "artifact_type": "Text",
                "schema_id": LOCAL_SUBSCRIPTION_AGENT_SCHEMA,
                "input_artifact_ids": input_artifact_ids,
                "lineage_roles": input_roles,
                "retryable": False,
                "client": executed.client,
                "exact_model_id": exact_model_id,
            },
        )


def _input_artifact_ids(typed_inputs: list[dict[str, Any]]) -> list[str]:
    artifact_ids: list[str] = []
    for item in typed_inputs:
        values = [*(item.get("artifact_ids") or []), *([item.get("artifact_id")] if item.get("artifact_id") else [])]
        for artifact_id in values:
            normalized = str(artifact_id)
            if normalized not in artifact_ids:
                artifact_ids.append(normalized)
    return artifact_ids
