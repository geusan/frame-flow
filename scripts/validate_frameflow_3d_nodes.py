#!/usr/bin/env python3
"""Execute cleanup -> Blender retarget -> render through Frameflow's real Node Registry."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--blender-executable", type=Path, required=True)
    parser.add_argument("--rigged-character", type=Path, required=True)
    parser.add_argument("--motion", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    blender = args.blender_executable.resolve()
    if not blender.is_file():
        raise RuntimeError(f"Blender executable does not exist: {blender}")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/api"))
    with tempfile.TemporaryDirectory(prefix="frameflow-node-spike-") as temporary:
        os.environ["DATABASE_URL"] = f"sqlite:///{Path(temporary) / 'frameflow.db'}"
        os.environ["STORAGE_PROVIDER"] = "memory"
        os.environ["APP_ENV"] = "test"
        os.environ["GENERATION_PROVIDER_MODE"] = "fixture"
        os.environ["BLENDER_EXECUTABLE"] = str(blender)
        os.environ["BLENDER_EXECUTION_PROVIDER"] = "local"

        from sqlalchemy import select

        from app.database import ArtifactEdgeRecord, ArtifactRecord, Base, SessionLocal, engine
        from app.domain import ExperimentRunRequest, NodeStatus
        from app.experiments import run_experiment
        from app.service import create_artifact
        from app.storage import get_storage, storage_location

        Base.metadata.create_all(bind=engine)
        progress: list[dict[str, object]] = []

        def report(value: int, message: str) -> None:
            progress.append({"progress": value, "message": message})

        with SessionLocal() as db:
            rig = create_artifact(
                db, "CharacterRigged", schema_id="character.rigged.glb.v1",
                metadata={"immutable": True, "filename": "fixture-character.glb"},
                content=args.rigged_character.read_bytes(), content_type="model/gltf-binary",
                filename="fixture-character.glb",
            )
            raw_motion = create_artifact(
                db, "MotionRaw", schema_id="humanoid.motion.v1",
                metadata={"immutable": True, "filename": "known-motion.json"},
                content=args.motion.read_bytes(), content_type="application/json", filename="known-motion.json",
            )
            db.commit()

            cleanup_request = ExperimentRunRequest(
                canvas_id="validation", node_id="cleanup", node_key="motion.humanoid.cleanup",
                model_alias="local.humanoid-motion-cleanup", parameters={},
                inputs=[{"type": "MotionRaw", "artifact_ids": [raw_motion.id]}],
            )
            cleanup = run_experiment(db, cleanup_request, progress_callback=report)
            if cleanup.status != NodeStatus.SUCCEEDED:
                raise RuntimeError(cleanup.error or "Frameflow Motion Cleanup failed")

            retarget_request = ExperimentRunRequest(
                canvas_id="validation", node_id="retarget", node_key="motion.humanoid.retarget",
                model_alias="local.blender-retarget",
                parameters={"rig_profile": "semantic", "root_motion": True, "scale_mode": "preserve", "fps": 24},
                inputs=[
                    {"type": "CharacterRigged", "artifact_ids": [rig.id]},
                    {"type": "MotionClean", "artifact_ids": cleanup.output_artifact_ids},
                ],
            )
            retarget = run_experiment(db, retarget_request, progress_callback=report)
            if retarget.status != NodeStatus.SUCCEEDED:
                raise RuntimeError(retarget.error or "Frameflow Motion Retarget failed")
            cached_retarget = run_experiment(db, retarget_request, progress_callback=report)
            if not cached_retarget.cache_hit or cached_retarget.output_artifact_ids != retarget.output_artifact_ids:
                raise RuntimeError("Frameflow did not reuse the cached retarget Artifacts")

            render_request = ExperimentRunRequest(
                canvas_id="validation", node_id="render", node_key="video.blender_render",
                model_alias="local.blender-render",
                parameters={
                    "resolution": "preview", "width": 1080, "height": 1920, "fps": 24,
                    "render_style": "toon", "camera_preset": "full_body", "background": "#181A20",
                    "samples": 8, "quality": "preview", "timeout_seconds": 600,
                },
                inputs=[{"type": "AnimatedCharacter", "artifact_ids": retarget.output_artifact_ids}],
            )
            rendered = run_experiment(db, render_request, progress_callback=report)
            if rendered.status != NodeStatus.SUCCEEDED:
                raise RuntimeError(rendered.error or "Frameflow Blender Render failed")
            video = db.get(ArtifactRecord, rendered.output_artifact_ids[0])
            if not video or video.type != "VideoPreview":
                raise RuntimeError("Frameflow Blender Render returned the wrong Artifact contract")
            bucket, key = storage_location(video.uri, video.metadata_json)
            video_bytes = get_storage().get_bytes(bucket=bucket, key=key)
            if video_bytes[4:8] != b"ftyp":
                raise RuntimeError("Frameflow Blender Render output is not an MP4")
            (output / "frameflow-preview.mp4").write_bytes(video_bytes)
            edges = db.scalars(select(ArtifactEdgeRecord)).all()
            summary = {
                "cleanup": {"experiment_id": cleanup.id, "artifact_ids": cleanup.output_artifact_ids},
                "retarget": {
                    "experiment_id": retarget.id, "artifact_ids": retarget.output_artifact_ids,
                    "cache_hit_verified": cached_retarget.cache_hit,
                },
                "render": {
                    "experiment_id": rendered.id, "artifact_id": video.id, "type": video.type,
                    "schema_id": video.schema_id, "sha256": video.sha256,
                    "size_bytes": len(video_bytes), "metadata": video.metadata_json,
                },
                "lineage_edge_count": len(edges),
                "progress": progress,
            }
            (output / "frameflow-validation-summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True))
            print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
