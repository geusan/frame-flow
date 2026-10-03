from __future__ import annotations

import hashlib

from ..contracts import NodeArtifactWrite, NodeExecutionResult


class PromptCombineError(ValueError):
    retryable = False


def prompt_part(typed_inputs, port):
    matches = [item for item in typed_inputs if item.get("target_port") == port]
    if len(matches) != 1:
        raise PromptCombineError(f"Prompt combination requires exactly one '{port}' input")
    item = matches[0]
    for key in ("config_text", "output_text"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value, list(dict.fromkeys([*(item.get("artifact_ids") or []), *([item["artifact_id"]] if item.get("artifact_id") else [])]))
    raise PromptCombineError(f"Prompt combination input '{port}' is empty")


class PromptCombineExecutor:
    def execute(self, context, config, typed_inputs):
        fixed, fixed_ids = prompt_part(typed_inputs, "fixed")
        variable, variable_ids = prompt_part(typed_inputs, "variable")
        text = fixed + config["separator"] + variable
        ids = list(dict.fromkeys([*fixed_ids, *variable_ids]))
        roles = {id: context.definition.artifact_contract.input_roles["prompt.text.v1"] for id in ids}
        store = context.require_artifact_store()
        artifact = store.create(NodeArtifactWrite(
            artifact_type="Text", schema_id=context.definition.artifact_contract.schema_id,
            content=text.encode(), content_type="text/plain", filename="combined-prompt.txt",
            input_artifact_ids=ids, input_artifact_roles=roles,
            metadata={"source": "node_executor_registry", "immutable": True,
                      "experiment_id": context.experiment_id, "request_hash": context.request_hash,
                      "definition_digest": context.definition.definition_digest,
                      "execution_mode": context.definition.execution.revision,
                      "executor_revision": context.definition.execution.revision,
                      "provider": "local", "model_alias": context.model_alias,
                      "normalized_config": config, "output_role": "combined_prompt",
                      "input_ports": {"fixed": fixed_ids, "variable": variable_ids},
                      "fixed_prompt_sha256": hashlib.sha256(fixed.encode()).hexdigest(),
                      "variable_prompt_sha256": hashlib.sha256(variable.encode()).hexdigest(), "cost_status": "local"},
        ))
        store.flush()
        return NodeExecutionResult(
            output={"kind": "text", "title": "Character + situation prompt", "text": text},
            output_artifact_ids=[artifact.id], provider_request_id="local_" + context.request_hash[:20], cost_usd=0,
            metadata={"artifact_type": "Text", "schema_id": context.definition.artifact_contract.schema_id,
                      "input_artifact_ids": ids, "lineage_roles": roles, "retryable": False},
        )
