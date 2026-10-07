"""Explicit Core assembly. The standalone local entrypoint remains compatible."""
from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .access import AccessDenied, RuntimeAdapters, execution_scope


@dataclass(frozen=True)
class AppConfig:
    profile: str = "local"
    title: str = "Frameflow Control Plane"
    origins: tuple[str, ...] = ("http://localhost:3000", "http://127.0.0.1:3000")

    def __post_init__(self):
        if self.profile not in {"local", "service"}:
            raise ValueError("Unknown Core application profile")


def create_app(config: AppConfig | None = None, *, adapters: RuntimeAdapters | None = None, lifespan=None) -> FastAPI:
    config = config or AppConfig()
    protected = config.profile == "service"
    if protected and (adapters is None or any(getattr(adapters, name, None) is None for name in ("identity", "authorization", "credentials", "sessions", "storage"))):
        raise ValueError("Service profile requires complete runtime adapters")
    from .api.routers import artifacts_router, canvases_router, fonts_router, formats_router, generation_router, references_router, runs_router, settings_router, skills_router, system_router, workflows_router
    from .billing import request_cost_scope

    app = FastAPI(title=config.title, version="0.1.0", lifespan=lifespan,
                  docs_url=None if protected else "/docs", redoc_url=None if protected else "/redoc", openapi_url=None if protected else "/openapi.json")

    @app.exception_handler(AccessDenied)
    async def access_failure(_: Request, exc: AccessDenied):
        return JSONResponse({"error": exc.code}, status_code=exc.status)

    @app.middleware("http")
    async def record_request_costs(request, call_next):
        with request_cost_scope():
            return await call_next(request)

    async def bind_runtime(request: Request):
        if not protected:
            yield
            return
        principal = await adapters.identity.authenticate(request.headers, request.cookies, request.method)
        operation = request.scope["route"].endpoint.__name__
        context = await adapters.authorization.authorize(principal, request.headers.get("x-workspace-id"), operation, getattr(request.state,"correlation_id",None) or uuid4().hex)
        with execution_scope(context, adapters):
            request.state.workspace_context = context
            yield

    app.add_middleware(CORSMiddleware, allow_origins=list(config.origins),
                       allow_origin_regex=None if protected else r"http://(localhost|127\.0\.0\.1):3\d{3}",
                       allow_credentials=True, allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"], allow_headers=["Content-Type", "X-CSRF-Token", "X-Workspace-Id"])
    if protected:
        @app.get("/health")
        def liveness():
            return {"status": "ok"}
        system_router = APIRouter(routes=[route for route in system_router.routes if getattr(route, "path", None) != "/health"])
    dependencies = [Depends(bind_runtime)]
    for router in (artifacts_router, canvases_router, fonts_router, formats_router, generation_router, references_router, runs_router, settings_router, skills_router, system_router, workflows_router):
        app.include_router(router, dependencies=dependencies)
    return app
