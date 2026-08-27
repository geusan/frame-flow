from __future__ import annotations

from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import ArtifactEdgeRecord, ArtifactRecord, CanvasNodeRunRecord, ExperimentRunRecord, NodeRunRecord
from .storage import artifact_content_url


LineageDirection = Literal["ancestors", "descendants", "both"]


def artifact_lineage_graph(
    db: Session,
    root_artifact_id: str,
    *,
    direction: LineageDirection = "both",
    depth: int = 8,
) -> dict[str, object]:
    root = db.get(ArtifactRecord, root_artifact_id)
    if not root:
        raise ValueError("artifact not found")

    visited_ids = {root.id}
    frontier = {root.id}
    edge_by_id: dict[str, ArtifactEdgeRecord] = {}
    for _ in range(depth):
        if not frontier:
            break
        discovered: set[str] = set()
        if direction in {"ancestors", "both"}:
            parent_edges = db.scalars(
                select(ArtifactEdgeRecord).where(ArtifactEdgeRecord.child_artifact_id.in_(frontier))
            ).all()
            for edge in parent_edges:
                edge_by_id[edge.id] = edge
                discovered.add(edge.parent_artifact_id)
        if direction in {"descendants", "both"}:
            child_edges = db.scalars(
                select(ArtifactEdgeRecord).where(ArtifactEdgeRecord.parent_artifact_id.in_(frontier))
            ).all()
            for edge in child_edges:
                edge_by_id[edge.id] = edge
                discovered.add(edge.child_artifact_id)
        frontier = discovered - visited_ids
        visited_ids.update(discovered)

    artifacts = db.scalars(
        select(ArtifactRecord).where(ArtifactRecord.id.in_(visited_ids))
    ).all()
    artifact_by_id = {artifact.id: artifact for artifact in artifacts}
    experiment_ids = {
        str(artifact.metadata_json.get("experiment_id"))
        for artifact in artifacts
        if artifact.metadata_json.get("experiment_id")
    }
    experiment_by_id = {
        experiment.id: experiment
        for experiment in db.scalars(
            select(ExperimentRunRecord).where(ExperimentRunRecord.id.in_(experiment_ids))
        ).all()
    } if experiment_ids else {}
    producer_ids = {
        artifact.producer_node_run_id for artifact in artifacts if artifact.producer_node_run_id
    }
    canvas_node_by_id = {
        node.id: node
        for node in db.scalars(
            select(CanvasNodeRunRecord).where(CanvasNodeRunRecord.id.in_(producer_ids))
        ).all()
    } if producer_ids else {}
    node_run_by_id = {
        node.id: node
        for node in db.scalars(
            select(NodeRunRecord).where(NodeRunRecord.id.in_(producer_ids))
        ).all()
    } if producer_ids else {}
    ordered_ids = [root.id, *sorted(visited_ids - {root.id}, key=lambda item: artifact_by_id[item].created_at)]
    nodes = [
        _artifact_node(
            artifact_by_id[artifact_id],
            is_root=artifact_id == root.id,
            experiment=experiment_by_id.get(str(artifact_by_id[artifact_id].metadata_json.get("experiment_id") or "")),
            producer_node=canvas_node_by_id.get(artifact_by_id[artifact_id].producer_node_run_id or "")
            or node_run_by_id.get(artifact_by_id[artifact_id].producer_node_run_id or ""),
        )
        for artifact_id in ordered_ids
    ]
    edges = [_edge_payload(edge) for edge in sorted(
        edge_by_id.values(),
        key=lambda item: (item.created_at, item.ordinal, item.id),
    )]
    return {
        "root_artifact_id": root.id,
        "direction": direction,
        "depth": depth,
        "nodes": nodes,
        "edges": edges,
    }


def _artifact_node(
    artifact: ArtifactRecord,
    *,
    is_root: bool,
    experiment: ExperimentRunRecord | None,
    producer_node: CanvasNodeRunRecord | NodeRunRecord | None,
) -> dict[str, object]:
    storage = artifact.metadata_json.get("storage") or {}
    return {
        "id": artifact.id,
        "created_at": artifact.created_at,
        "type": artifact.type,
        "schema_id": artifact.schema_id,
        "filename": str(
            artifact.metadata_json.get("filename")
            or artifact.metadata_json.get("output", {}).get("title")
            or f"{artifact.type} · {artifact.id[:10]}"
        ),
        "content_type": str(storage.get("content_type") or "application/octet-stream"),
        "size_bytes": int(storage.get("size_bytes") or 0),
        "source": str(
            artifact.metadata_json.get("source")
            or ("generated" if artifact.producer_node_run_id or artifact.metadata_json.get("experiment_id") else "artifact")
        ),
        "url": artifact_content_url(artifact.id),
        "sha256": artifact.sha256,
        "producer_node_run_id": artifact.producer_node_run_id,
        "input_artifact_ids": artifact.input_artifact_ids or [],
        "metadata": artifact.metadata_json or {},
        "derivation": _derivation_payload(artifact, experiment, producer_node),
        "is_root": is_root,
    }


def _derivation_payload(
    artifact: ArtifactRecord,
    experiment: ExperimentRunRecord | None,
    producer_node: CanvasNodeRunRecord | NodeRunRecord | None,
) -> dict[str, object]:
    capture = artifact.metadata_json.get("capture") or {}
    source = str(artifact.metadata_json.get("source") or "")
    if capture:
        timestamp_ms = int(capture.get("timestamp_ms") or 0)
        scene_search = capture.get("scene_search") or {}
        search_prompt = str(scene_search.get("search_prompt") or "").strip()
        description = f"Captured the source video at {timestamp_ms / 1000:.3f}s with accurate FFmpeg seeking."
        if search_prompt:
            description = (
                f"Selected this scene for the prompt “{search_prompt[:180]}” and captured it at "
                f"{timestamp_ms / 1000:.3f}s. Match score: {float(scene_search.get('search_score') or 0):.2f}."
            )
        return {
            "operation": experiment.node_key if experiment else "video.frame.capture",
            "title": "Extracted video frame" if experiment else "Captured video frame",
            "description": description,
            "prompt": (experiment.prompt or None) if experiment else (search_prompt or None),
            "model_alias": experiment.model_alias if experiment else str(scene_search.get("search_model_alias") or scene_search.get("search_model") or "local.ffmpeg"),
            "exact_model_id": experiment.exact_model_id if experiment else str(scene_search.get("search_model") or capture.get("operation") or "ffmpeg-accurate-seek.v1"),
            "parameters": {**(experiment.parameters if experiment else {}), **capture},
            "request_hash": experiment.request_hash if experiment else None,
            "execution_mode": experiment.execution_mode if experiment else "local-media.v1",
        }
    if experiment:
        editing_image = experiment.node_key == "image.edit"
        return {
            "operation": experiment.node_key,
            "title": "AI edited image" if editing_image else _operation_title(experiment.node_key),
            "description": f"Edited the source image with the recorded instruction: {experiment.prompt.strip().replace(chr(10), ' ')[:180]}" if editing_image else _operation_description(experiment.node_key, experiment.prompt),
            "prompt": experiment.prompt or None,
            "model_alias": experiment.model_alias,
            "exact_model_id": experiment.exact_model_id,
            "parameters": experiment.parameters or {},
            "request_hash": experiment.request_hash,
            "execution_mode": experiment.execution_mode,
        }
    if source == "image_manual_edit":
        edit_document = artifact.metadata_json.get("image_edit") or {}
        return {
            "operation": "image.manual_edit",
            "title": "Manually edited image",
            "description": "Applied deterministic browser canvas transforms and adjustments to the source image.",
            "prompt": None,
            "model_alias": "local.browser-canvas",
            "exact_model_id": "canvas-2d.v1",
            "parameters": edit_document,
            "request_hash": None,
            "execution_mode": "browser-canvas.v1",
        }
    if source == "canvas_url_import":
        return {
            "operation": "asset.url.import",
            "title": "Imported from URL",
            "description": f"Downloaded with {artifact.metadata_json.get('downloader_provider') or 'the configured downloader'} and stored as an immutable video asset.",
            "prompt": None,
            "model_alias": artifact.metadata_json.get("downloader_provider"),
            "exact_model_id": None,
            "parameters": {"source_url": artifact.metadata_json.get("source_url")},
            "request_hash": None,
            "execution_mode": "video-downloader.v1",
        }
    if source == "canvas_upload":
        return {
            "operation": "asset.file.upload",
            "title": "Uploaded file",
            "description": "Uploaded directly to the Canvas asset store.",
            "prompt": None,
            "model_alias": None,
            "exact_model_id": None,
            "parameters": {},
            "request_hash": None,
            "execution_mode": "upload.v1",
        }
    node_key = str(getattr(producer_node, "node_key", "") or "artifact.derived")
    return {
        "operation": node_key,
        "title": _operation_title(node_key),
        "description": f"Created from {len(artifact.input_artifact_ids or [])} input artifact(s)." if artifact.input_artifact_ids else "Stored as a root artifact.",
        "prompt": None,
        "model_alias": None,
        "exact_model_id": None,
        "parameters": {},
        "request_hash": getattr(producer_node, "request_hash", None),
        "execution_mode": None,
    }


def _operation_title(node_key: str) -> str:
    return {
        "image.generate": "Generated image",
        "image.edit": "AI edited image",
        "video.generate": "Generated video",
        "video.edit": "Edited video",
        "video.change_voice": "Replaced video audio",
        "video.translate": "Translated video",
        "subtitle.align": "Aligned subtitles",
        "timeline.compose": "Composed timeline",
        "video.render": "Rendered video",
    }.get(node_key, node_key.replace(".", " ").replace("_", " ").title())


def _operation_description(node_key: str, prompt: str) -> str:
    prompt_summary = prompt.strip().replace("\n", " ")[:180]
    if node_key == "image.generate":
        return f"Generated an image from the recorded prompt: {prompt_summary}"
    if node_key == "video.generate":
        return f"Generated a video from the recorded prompt and connected media: {prompt_summary}"
    if prompt_summary:
        return f"Ran {node_key} with the recorded configuration: {prompt_summary}"
    return f"Ran {node_key} with the recorded input artifacts and parameters."


def _edge_payload(edge: ArtifactEdgeRecord) -> dict[str, object]:
    return {
        "id": edge.id,
        "created_at": edge.created_at,
        "parent_artifact_id": edge.parent_artifact_id,
        "child_artifact_id": edge.child_artifact_id,
        "role": edge.role,
        "ordinal": edge.ordinal,
        "operation_id": edge.operation_id,
        "metadata": edge.metadata_json or {},
    }
