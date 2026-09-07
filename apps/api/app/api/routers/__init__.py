"""FastAPI routers grouped by bounded context."""

from .artifacts import router as artifacts_router
from .canvases import router as canvases_router
from .formats import router as formats_router
from .fonts import router as fonts_router
from .generation import router as generation_router
from .references import router as references_router
from .runs import router as runs_router
from .settings import router as settings_router
from .skills import router as skills_router
from .system import router as system_router
from .workflows import router as workflows_router

__all__ = [
    "artifacts_router",
    "canvases_router",
    "formats_router",
    "fonts_router",
    "generation_router",
    "references_router",
    "runs_router",
    "settings_router",
    "skills_router",
    "system_router",
    "workflows_router",
]
