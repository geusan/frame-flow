from functools import lru_cache

from ..contexts.canvases.application import CanvasApplication
from ..contexts.workflows.application import WorkflowApplication
from ..domain import utc_now
from ..infrastructure.persistence import (
    LegacySqlAlchemyWorkflowOperations,
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
def get_workflow_application() -> WorkflowApplication:
    return WorkflowApplication(LegacySqlAlchemyWorkflowOperations())
