from functools import lru_cache

from ..contexts.canvases.application import CanvasApplication
from ..domain import utc_now
from ..infrastructure.persistence import SqlAlchemyCanvasUnitOfWork
from ..service import new_id


@lru_cache(maxsize=1)
def get_canvas_application() -> CanvasApplication:
    return CanvasApplication(
        uow_factory=SqlAlchemyCanvasUnitOfWork,
        id_generator=new_id,
        clock=utc_now,
    )
