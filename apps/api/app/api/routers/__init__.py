"""FastAPI routers grouped by bounded context."""

from .canvases import router as canvases_router

__all__ = ["canvases_router"]
