from __future__ import annotations

import re

from ..contracts import NodeArtifactWrite, NodeExecutionResult


class PromptSectionError(ValueError):
    retryable = False


def extract_prompt_section(document: str, heading: str) -> str:
    """Select one ATX Markdown section; never fall back to the whole document."""
    target = " ".join(heading.split()).casefold()
    if not target:
        raise PromptSectionError("Section heading must not be blank")
    lines = document.splitlines()
    headings = []
    fence = None
    for index, line in enumerate(lines):
        boundary = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if boundary:
            marker, suffix = boundary.groups()
            if fence is None:
                fence = marker
            elif marker[0] == fence[0] and len(marker) >= len(fence) and not suffix.strip():
                fence = None
            continue
        if fence:
            continue
        match = re.match(r"^ {0,3}(#{1,6})[ \t]+(.+?)\s*$", line)
        if match:
            title = re.sub(r"[ \t]+#+[ \t]*$", "", match[2])
            headings.append((index, len(match[1]), " ".join(title.split()).casefold()))
    matches = [item for item in headings if item[2] == target]
    if len(matches) != 1:
        raise PromptSectionError(f"Expected exactly one Prompt section '{heading}', found {len(matches)}")
    start, level, _ = matches[0]
    end = next((index for index, depth, _ in headings if index > start and depth <= level), len(lines))
    result = "\n".join(lines[start + 1:end]).strip()
    if not result:
        raise PromptSectionError(f"Prompt section '{heading}' is empty")
    return result


class PromptSectionExecutor:
    def execute(self, context, config, typed_inputs):
        text = extract_prompt_section(context.prompt, config["heading"])
        direct = [item for item in typed_inputs if item.get("target_port") == "prompt"]
        if not direct:
            direct = [item for item in typed_inputs if item.get("type") == "Prompt"]
        artifact_ids = list(dict.fromkeys(str(id) for item in direct for id in [*(item.get("artifact_ids") or []), *([item["artifact_id"]] if item.get("artifact_id") else [])]))
        roles = {id: context.definition.artifact_contract.input_roles["prompt.text.v1"] for id in artifact_ids}
        store = context.require_artifact_store()
        artifact = store.create(NodeArtifactWrite(
            artifact_type=context.definition.artifact_contract.primary_type,
            schema_id=context.definition.artifact_contract.schema_id,
            content=text.encode(), content_type="text/plain", filename="selected-prompt.txt",
            input_artifact_ids=artifact_ids, input_artifact_roles=roles,
            metadata={"source": "node_executor_registry", "immutable": True,
                      "experiment_id": context.experiment_id, "request_hash": context.request_hash,
                      "definition_digest": context.definition.definition_digest,
                      "execution_mode": context.definition.execution.revision,
                      "executor_revision": context.definition.execution.revision,
                      "provider": "local", "model_alias": context.model_alias,
                      "normalized_config": config, "output_role": "selected_prompt", "cost_status": "local"},
        ))
        store.flush()
        return NodeExecutionResult(
            output={"kind": "text", "title": "Final generation prompt", "text": text},
            output_artifact_ids=[artifact.id], provider_request_id="local_" + context.request_hash[:20], cost_usd=0,
            metadata={"artifact_type": "Text", "schema_id": context.definition.artifact_contract.schema_id,
                      "input_artifact_ids": artifact_ids, "lineage_roles": roles, "retryable": False},
        )
