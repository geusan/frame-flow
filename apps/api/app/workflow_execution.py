from __future__ import annotations

from typing import Any

from sqlalchemy import select

from .database import (
    ArtifactRecord,
    FormatRecord,
    GenerationBriefRecord,
    NodeRunRecord,
    RunRecord,
    SessionLocal,
)
from .domain import ExperimentRunRequest, NodeStatus
from .experiments import run_experiment
from .storage import get_storage, storage_location


MODEL_BY_NODE = {
    "generation.resolve": "local",
    "script.generate": "text.quality",
    "script.fit_duration": "local",
    "shot.plan": "local",
    "image.generate": "image.fast",
    "video.generate": "video.fast",
    "tts.generate": "tts.fast",
    "subtitle.align": "local",
    "timeline.compose": "local",
    "video.render": "local",
    "media.qc": "local",
}


def _artifact_input(db, artifact_ids: list[str], input_type: str) -> dict[str, Any]:
    existing = [artifact_id for artifact_id in artifact_ids if db.get(ArtifactRecord, artifact_id)]
    return {"type": input_type, "artifact_ids": existing}


def _node_artifacts(db, run_id: str, node_key: str) -> list[str]:
    node = db.scalar(select(NodeRunRecord).where(NodeRunRecord.run_id == run_id, NodeRunRecord.node_key == node_key))
    return list(node.output_artifact_ids or []) if node else []


def _selection_video_ids(db, run_id: str) -> list[str]:
    selection_ids = _node_artifacts(db, run_id, "candidate.select")
    if not selection_ids:
        return _node_artifacts(db, run_id, "video.generate")
    selection = db.get(ArtifactRecord, selection_ids[0])
    return list(selection.input_artifact_ids or []) if selection else []


def _artifact_text(db, artifact_ids: list[str]) -> str:
    if not artifact_ids:
        return ""
    artifact = db.get(ArtifactRecord, artifact_ids[0])
    if not artifact:
        return ""
    storage = get_storage()
    bucket, key = storage_location(artifact.uri, artifact.metadata_json)
    return storage.get_bytes(bucket=bucket, key=key).decode("utf-8", errors="replace").strip()


def _format_artifact_ids(db, format_id: str) -> list[str]:
    artifacts = db.scalars(select(ArtifactRecord).where(ArtifactRecord.type == "FormatProfile")).all()
    return [artifact.id for artifact in artifacts if str(artifact.metadata_json.get("format_id")) == format_id]


def _payload_for_node(db, run: RunRecord, node: NodeRunRecord) -> ExperimentRunRequest:
    brief_id = str((run.execution_plan or {}).get("brief_id") or "")
    brief = db.get(GenerationBriefRecord, brief_id)
    if not brief:
        raise ValueError(f"generation run has no valid brief: {run.id}")
    brief_data = dict(brief.payload or {})
    format_record = db.get(FormatRecord, brief.format_id)
    topic = str(brief_data.get("topic") or brief.topic)
    key_message = str(brief_data.get("key_message") or "")
    additional = str(brief_data.get("additional_prompt") or "")
    base_prompt = "\n".join(part for part in [topic, key_message, additional] if part).strip()
    target_seconds = max(1, round(int(brief_data.get("target_duration_ms") or 38_000) / 1000))
    parameters: dict[str, Any] = {
        "target_duration_seconds": target_seconds,
        "aspect_ratio": brief_data.get("aspect_ratio") or "9:16",
        "language": brief_data.get("language") or "ko-KR",
        "duration_seconds": 6,
        "resolution": "1080p",
        "voice_name": "Kore",
        "output_count": int(brief_data.get("candidate_count") or 1),
    }
    inputs: list[dict[str, Any]] = []
    prompt = base_prompt

    if node.node_key == "generation.resolve":
        inputs = [
            {"type": "Text", "label": "Generation brief", "description": base_prompt, "artifact_ids": []},
            _artifact_input(db, _format_artifact_ids(db, brief.format_id), "FormatProfile"),
        ]
    elif node.node_key == "script.generate":
        inputs = [_artifact_input(db, _node_artifacts(db, run.id, "generation.resolve"), "GenerationSpec")]
        prompt = f"Write a {target_seconds}-second {parameters['language']} narration script. Topic: {topic}. Key message: {key_message}. {additional}".strip()
    elif node.node_key == "script.fit_duration":
        inputs = [_artifact_input(db, _node_artifacts(db, run.id, "script.generate"), "Script")]
    elif node.node_key == "shot.plan":
        inputs = [_artifact_input(db, _node_artifacts(db, run.id, "script.fit_duration"), "Script")]
    elif node.node_key == "image.generate":
        inputs = [_artifact_input(db, _node_artifacts(db, run.id, "shot.plan"), "ShotPlan")]
        prompt = f"Create an original cinematic vertical image for: {base_prompt}. Do not include text or logos."
    elif node.node_key == "video.generate":
        inputs = [_artifact_input(db, _node_artifacts(db, run.id, "image.generate"), "Image")]
        prompt = f"Create an original cinematic shot with natural subject and camera motion for: {base_prompt}."
    elif node.node_key == "tts.generate":
        script_ids = _node_artifacts(db, run.id, "script.fit_duration")
        inputs = [_artifact_input(db, script_ids, "Script")]
        prompt = _artifact_text(db, script_ids) or base_prompt
    elif node.node_key == "subtitle.align":
        inputs = [
            _artifact_input(db, _node_artifacts(db, run.id, "tts.generate"), "Audio"),
            _artifact_input(db, _node_artifacts(db, run.id, "script.fit_duration"), "Script"),
        ]
    elif node.node_key == "timeline.compose":
        inputs = [
            _artifact_input(db, _selection_video_ids(db, run.id), "Video"),
            _artifact_input(db, _node_artifacts(db, run.id, "subtitle.align"), "Subtitle"),
        ]
    elif node.node_key == "video.render":
        inputs = [_artifact_input(db, _node_artifacts(db, run.id, "timeline.compose"), "Timeline")]
    elif node.node_key == "media.qc":
        inputs = [_artifact_input(db, _node_artifacts(db, run.id, "video.render"), "Video")]

    if format_record:
        parameters["format_id"] = format_record.id
    return ExperimentRunRequest(
        canvas_id=f"generation-run:{run.id}", node_id=node.id, node_key=node.node_key,
        prompt=prompt, model_alias=MODEL_BY_NODE[node.node_key], parameters=parameters, inputs=inputs,
    )


def execute_workflow_node(run_id: str, node_key: str) -> dict[str, Any]:
    with SessionLocal() as db:
        run = db.get(RunRecord, run_id)
        node = db.scalar(select(NodeRunRecord).where(NodeRunRecord.run_id == run_id, NodeRunRecord.node_key == node_key))
        if not run or not node:
            raise ValueError(f"run or node was not found: {run_id}/{node_key}")
        if run.status == NodeStatus.CANCELED:
            raise RuntimeError("generation run was canceled")
        if node.status == NodeStatus.SUCCEEDED:
            return {"node_run_id": node.id, "artifact_ids": node.output_artifact_ids, "cache_hit": True}
        node.status = NodeStatus.RUNNING
        node.attempt_count += 1
        run.status = NodeStatus.RUNNING
        db.commit()
        payload = _payload_for_node(db, run, node)
        experiment = run_experiment(db, payload)
        if experiment.status != NodeStatus.SUCCEEDED:
            node.status = NodeStatus.FAILED
            node.progress = 0
            db.commit()
            raise RuntimeError(experiment.error or f"workflow node failed: {node_key}")
        node.provider_request_id = experiment.provider_request_id
        node.request_hash = experiment.request_hash
        node.output_artifact_ids = list(experiment.output_artifact_ids or [])
        node.status = NodeStatus.SUCCEEDED
        node.progress = 100
        node.cost_usd = experiment.cost_usd
        for artifact_id in node.output_artifact_ids:
            artifact = db.get(ArtifactRecord, artifact_id)
            if artifact:
                artifact.producer_node_run_id = node.id
        run.actual_cost_usd = round(sum(item.cost_usd for item in run.node_runs), 2)
        run.progress = min(99, round((node.ordinal + 1) / len(run.node_runs) * 100))
        db.commit()
        return {
            "node_run_id": node.id,
            "artifact_ids": node.output_artifact_ids,
            "cache_hit": experiment.cache_hit,
            "provider_request_id": node.provider_request_id,
        }
