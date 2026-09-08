#!/usr/bin/env python3
"""Run real dance video validation and MediaPipe extraction through Node Registry."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fps", type=float, default=8)
    args = parser.parse_args()
    repository = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repository / "apps/api"))
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="frameflow-motion-node-spike-") as temporary:
        os.environ["DATABASE_URL"] = f"sqlite:///{Path(temporary) / 'frameflow.db'}"
        os.environ["STORAGE_PROVIDER"] = "memory"
        os.environ["APP_ENV"] = "test"
        os.environ["GENERATION_PROVIDER_MODE"] = "fixture"

        from app.database import ArtifactRecord, Base, SessionLocal, engine
        from app.domain import ExperimentRunRequest, NodeStatus
        from app.experiments import run_experiment
        from app.service import create_artifact
        from app.storage import get_storage, storage_location

        Base.metadata.create_all(bind=engine)
        progress = []
        with SessionLocal() as db:
            source = create_artifact(
                db, "Video", metadata={"immutable": True, "filename": args.video.name},
                content=args.video.read_bytes(), content_type="video/mp4", filename=args.video.name,
            )
            db.commit()
            validated = run_experiment(
                db,
                ExperimentRunRequest(
                    canvas_id="dance-validation", node_id="video", node_key="motion.video.validate",
                    model_alias="local.motion-video-validation", parameters={},
                    inputs=[{"type": "Video", "artifact_ids": [source.id]}],
                ),
                progress_callback=lambda value, message: progress.append({"progress": value, "message": message}),
            )
            if validated.status != NodeStatus.SUCCEEDED:
                raise RuntimeError(validated.error or "Motion Video Input node failed")
            extracted = run_experiment(
                db,
                ExperimentRunRequest(
                    canvas_id="dance-validation", node_id="extract", node_key="motion.humanoid.extract",
                    model_alias="local.mediapipe-humanoid",
                    parameters={"fps": args.fps, "include_hands": False, "include_face": False},
                    inputs=[{"type": "MotionSourceVideo", "artifact_ids": validated.output_artifact_ids}],
                ),
                progress_callback=lambda value, message: progress.append({"progress": value, "message": message}),
            )
            if extracted.status != NodeStatus.SUCCEEDED:
                raise RuntimeError(extracted.error or "Humanoid Motion Extraction node failed")
            raw = db.get(ArtifactRecord, extracted.output_artifact_ids[0])
            if not raw or raw.type != "MotionRaw":
                raise RuntimeError("Motion Extraction returned the wrong primary Artifact")
            bucket, key = storage_location(raw.uri, raw.metadata_json)
            content = get_storage().get_bytes(bucket=bucket, key=key)
            output.write_bytes(content)
            motion = json.loads(content)
            summary = {
                "video_validation_experiment": validated.id,
                "motion_extraction_experiment": extracted.id,
                "artifact_type": raw.type,
                "schema_id": raw.schema_id,
                "sha256": raw.sha256,
                "frame_count": len(motion["frames"]),
                "duration_seconds": motion["duration_seconds"],
                "invalid_frame_ratio": motion["metadata"]["invalid_frame_ratio"],
                "coverage": motion["metadata"]["coverage"],
                "root_trajectory_source": motion["metadata"]["root_trajectory_source"],
                "progress": progress,
            }
            output.with_suffix(".summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True))
            print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
