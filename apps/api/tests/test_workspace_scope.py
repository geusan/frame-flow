from dataclasses import replace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.access import AccessDenied, Principal, RuntimeAdapters, WorkspaceContext, execution_scope
from app.database import ArtifactRecord, Base, CanvasRecord, SessionLocal, WorkspaceRecord
from app.factory import AppConfig, create_app
from app.scoped_session import workspace_session_factory


class Identity:
    async def authenticate(self, headers, cookies, method):
        if not headers.get("authorization"):
            raise AccessDenied(401, "authentication_required")
        return Principal(headers["authorization"])


class Authorization:
    def __init__(self):
        self.disabled = set()
    async def authorize(self, principal, workspace_hint, operation, request_id):
        if workspace_hint not in {"a", "b"} or principal.id != workspace_hint:
            raise AccessDenied()
        return WorkspaceContext(principal, workspace_hint, request_id,action="edit")
    def revalidate(self, context):
        if context.principal.id in self.disabled:
            raise AccessDenied()


@pytest.fixture
def runtime():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all([WorkspaceRecord(id=key, name=key, status="active") for key in ("a", "b")])
        db.commit()
    auth = Authorization()
    adapters = RuntimeAdapters(Identity(), auth, object(), workspace_session_factory(engine, auth.revalidate), lambda context: None)
    yield adapters, engine
    engine.dispose()


def context(workspace):
    return WorkspaceContext(Principal(workspace), workspace, uuid4().hex,action="edit")


def test_direct_repository_query_get_write_and_raw_sql_cannot_escape_scope(runtime):
    adapters, engine = runtime
    for workspace in ("a", "b"):
        with execution_scope(context(workspace), adapters), SessionLocal() as db:
            db.add(CanvasRecord(id=f"canvas-{workspace}", name=workspace, graph_json={}))
            db.commit()
    with execution_scope(context("a"), adapters), SessionLocal() as db:
        assert [row.id for row in db.scalars(select(CanvasRecord))] == ["canvas-a"]
        assert db.get(CanvasRecord, "canvas-b") is None
        with pytest.raises(AccessDenied):
            db.execute(text("SELECT * FROM canvases"))
        db.add(CanvasRecord(id="spoof", name="spoof", graph_json={}, workspace_id="b"))
        with pytest.raises(AccessDenied):
            db.commit()


def test_nested_json_reference_to_foreign_artifact_is_rejected(runtime):
    adapters, engine = runtime
    with execution_scope(context("b"), adapters), SessionLocal() as db:
        db.add(ArtifactRecord(id="foreign-artifact", type="Image", uri="memory://bucket/image", sha256="a" * 64))
        db.commit()
    with execution_scope(context("a"), adapters), SessionLocal() as db:
        db.add(CanvasRecord(id="nested", name="test", graph_json={"nodes": [{"config": {"artifact_id": "foreign-artifact"}}]}))
        with pytest.raises(AccessDenied):
            db.commit()


def test_context_does_not_survive_request_and_membership_is_revalidated(runtime):
    adapters, _ = runtime
    ctx = context("a")
    with execution_scope(ctx, adapters), SessionLocal() as db:
        adapters.authorization.disabled.add("a")
        with pytest.raises(AccessDenied):
            db.scalars(select(CanvasRecord))
    from app.access import current_scope
    assert current_scope() is None


def test_factory_requires_adapters_hides_docs_and_checks_every_core_route(runtime):
    adapters, _ = runtime
    with pytest.raises(ValueError):
        create_app(AppConfig(profile="service"))
    app = create_app(AppConfig(profile="service", title="Test"), adapters=adapters)
    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok"}
        assert client.get("/openapi.json").status_code == 404
        assert client.get("/canvases").status_code == 401
        assert client.get("/canvases", headers={"authorization": "a", "x-workspace-id": "b"}).status_code == 403
        created = client.post("/canvases", json={"name": "Scoped"}, headers={"authorization": "a", "x-workspace-id": "a"})
        assert created.status_code == 201, created.text
        identifier = created.json()["id"]
        assert client.get(f"/canvases/{identifier}", headers={"authorization": "b", "x-workspace-id": "b"}).status_code == 404
        assert client.get("/canvases", headers={"authorization": "b", "x-workspace-id": "b"}).json() == []
