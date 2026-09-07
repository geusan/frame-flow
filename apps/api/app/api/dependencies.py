from functools import lru_cache

from ..contexts.artifacts.application import ArtifactApplication
from ..contexts.canvases.application import CanvasApplication
from ..contexts.runs.application import RunApplication
from ..contexts.workflows.application import WorkflowApplication
from ..domain import utc_now
from ..infrastructure.persistence import (
    LegacySqlAlchemyArtifactOperations,
    LegacySqlAlchemyWorkflowOperations,
    LegacySqlAlchemyRunOperations,
    SqlAlchemyCanvasUnitOfWork,
)
from ..service import new_id


@lru_cache(maxsize=1)
def get_canvas_application() -> CanvasApplication:
    return CanvasApplication(
        uow_factory=SqlAlchemyCanvasUnitOfWork,
        id_generator=new_id,
        clock=utc_now,
    )


@lru_cache(maxsize=1)
def get_artifact_application() -> ArtifactApplication:
    return ArtifactApplication(LegacySqlAlchemyArtifactOperations())


@lru_cache(maxsize=1)
def get_workflow_application() -> WorkflowApplication:
    return WorkflowApplication(LegacySqlAlchemyWorkflowOperations())


@lru_cache(maxsize=1)
def get_run_application() -> RunApplication:
    return RunApplication(LegacySqlAlchemyRunOperations())
