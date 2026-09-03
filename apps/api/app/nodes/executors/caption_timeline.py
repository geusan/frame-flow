from __future__ import annotations

import json
from typing import Any

from ...canvas_operations import _read_artifacts, _timeline
from ...caption_documents import canonical_caption_document
from ...service import create_artifact
from ...storage import artifact_content_url
from ..contracts import NodeExecutionContext, NodeExecutionResult
from .text_support import input_lineage


CAPTION_TIMELINE_REVISION = "caption-timeline.v1"


class CaptionTimelineExecutor:
    def execute(
        self,
        context: NodeExecutionContext,
        resolved_node_config: dict[str, Any],
        typed_inputs: list[dict[str, Any]],
    ) -> NodeExecutionResult:
        if context.definition.execution.revision != CAPTION_TIMELINE_REVISION:
            raise RuntimeError("Caption Timeline executor revision does not match its Node Definition")
        document = canonical_caption_document(
            context.db,
            dict(resolved_node_config.get("caption_document") or {}),
        )
        config = {**resolved_node_config, "caption_document": document}
        artifacts = _read_artifacts(context.db, typed_inputs)
        timeline = _timeline(artifacts, config)
        content = json.dumps(timeline, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        input_artifact_ids, input_roles = input_lineage(context, typed_inputs)
        artifact = create_artifact(
            context.db,
            context.definition.artifact_contract.primary_type,
            schema_id=context.definition.artifact_contract.schema_id,
            input_artifact_ids=input_artifact_ids,
            input_artifact_roles=input_roles,
            metadata={
                "experiment_id": context.experiment_id,
                "request_hash": context.request_hash,
                "execution_mode": CAPTION_TIMELINE_REVISION,
                "immutable": True,
                "source": "caption_timeline",
                "provider": "local",
                "normalized_config": config,
                "font_snapshots": document["fonts"],
                "output_role": context.definition.artifact_contract.output_role,
            },
            content=content,
            content_type="application/json",
            filename="rich-caption-timeline.json",
        )
        context.db.flush()
        return NodeExecutionResult(
            output={
                "kind": "json",
                "title": f"Rich caption timeline · {len(document['cues'])} cues",
                "text": json.dumps(timeline, ensure_ascii=False, indent=2),
                "url": artifact_content_url(artifact.id),
            },
            output_artifact_ids=[artifact.id],
            provider_request_id=f"local_{context.request_hash[:20]}",
            metadata={
                "artifact_type": context.definition.artifact_contract.primary_type,
                "schema_id": context.definition.artifact_contract.schema_id,
                "input_artifact_ids": input_artifact_ids,
                "lineage_roles": input_roles,
                "retryable": False,
                "executor_revision": CAPTION_TIMELINE_REVISION,
            },
        )
