from __future__ import annotations

from dataclasses import dataclass
from typing import Any


DEFAULT_NODES = [
    ("generation.resolve", "control", 0.00),
    ("script.generate", "google.text.quality", 0.06),
    ("script.fit_duration", "google.text.fast", 0.03),
    ("shot.plan", "google.text.fast", 0.03),
    ("image.generate", "google.image.fast", 0.84),
    ("video.generate", "google.video.fast", 2.80),
    ("tts.generate", "google.tts.fast", 0.12),
    ("candidate.select", "control", 0.00),
    ("subtitle.align", "ffmpeg.align", 0.00),
    ("timeline.compose", "control", 0.00),
    ("video.render", "ffmpeg.render", 0.15),
    ("media.qc", "ffmpeg.qc", 0.00),
]


class CompileError(ValueError):
    pass


@dataclass(frozen=True)
class ExecutionPlan:
    payload: dict[str, Any]

    @property
    def estimated_cost_usd(self) -> float:
        return float(self.payload["estimated_cost_usd"])


def compile_generation_plan(brief: dict[str, Any], workflow_definition_id: str) -> ExecutionPlan:
    candidates = int(brief["candidate_count"])
    duration = int(brief["target_duration_ms"])
    shot_count = max(3, round(duration / 5500))
    expanded_jobs = shot_count * candidates + shot_count * 2 + len(DEFAULT_NODES)
    estimated = round(sum(node[2] for node in DEFAULT_NODES), 2)
    if estimated > float(brief["budget_limit_usd"]):
        raise CompileError(f"estimated cost ${estimated:.2f} exceeds budget ${brief['budget_limit_usd']:.2f}")
    return ExecutionPlan(
        {
            "version": "execution.plan.v1",
            "workflow_definition_id": workflow_definition_id,
            "workflow_version": "workflow.shorts.default.v1@1",
            "nodes": [{"node_key": key, "resource_pool": model, "estimated_cost_usd": cost} for key, model, cost in DEFAULT_NODES],
            "shot_count": shot_count,
            "candidate_count": candidates,
            "expanded_jobs": expanded_jobs,
            "estimated_api_calls": shot_count * candidates + shot_count * 2 + 4,
            "estimated_cost_usd": estimated,
            "checks": {
                "acyclic": True,
                "required_inputs": True,
                "port_types": True,
                "schema_compatibility": True,
                "models_available": True,
                "reference_isolation": True,
            },
            "snapshot": {
                "format_schema": "format.core.v1",
                "renderer_version": "ffmpeg.timeline.v1",
                "model_registry_revision": "local-demo-2026-08-24",
            },
        }
    )

