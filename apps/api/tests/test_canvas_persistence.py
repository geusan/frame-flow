from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.contexts.canvases.domain import Canvas
from app.database import SessionLocal
from app.infrastructure.persistence import SqlAlchemyCanvasUnitOfWork


def _canvas(canvas_id: str = "canvas_repository") -> Canvas:
    now = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)
    return Canvas(
        id=canvas_id,
        created_at=now,
        updated_at=now,
        name="Repository Canvas",
        graph_document={"schema_version": "canvas.document.v1", "nodes": [], "edges": []},
        revision=3,
        draft_contract={"schema_version": "workflow.draft-contract.v1"},
    )


def test_canvas_repository_round_trips_domain_model(client: TestClient) -> None:
    del client
    canvas = _canvas()

    with SqlAlchemyCanvasUnitOfWork(SessionLocal) as uow:
        uow.canvases.add(canvas)
        uow.commit()

    with SqlAlchemyCanvasUnitOfWork(SessionLocal) as uow:
        loaded = uow.canvases.get(canvas.id)
        assert loaded == canvas
        assert uow.canvases.list_all() == [canvas]

        loaded.name = "Updated Canvas"
        loaded.revision = 4
        uow.canvases.save(loaded)
        uow.commit()

    with SqlAlchemyCanvasUnitOfWork(SessionLocal) as uow:
        loaded = uow.canvases.get(canvas.id)
        assert loaded is not None
        assert loaded.name == "Updated Canvas"
        assert loaded.revision == 4


def test_canvas_unit_of_work_rolls_back_without_commit(client: TestClient) -> None:
    del client
    canvas = _canvas("canvas_rolled_back")

    with SqlAlchemyCanvasUnitOfWork(SessionLocal) as uow:
        uow.canvases.add(canvas)

    with SqlAlchemyCanvasUnitOfWork(SessionLocal) as uow:
        assert uow.canvases.get(canvas.id) is None


def test_canvas_repository_delete_is_explicit(client: TestClient) -> None:
    del client
    canvas = _canvas("canvas_deleted")

    with SqlAlchemyCanvasUnitOfWork(SessionLocal) as uow:
        uow.canvases.add(canvas)
        uow.commit()

    with SqlAlchemyCanvasUnitOfWork(SessionLocal) as uow:
        assert uow.canvases.delete(canvas.id) is True
        assert uow.canvases.delete("missing") is False
        uow.commit()

    with SqlAlchemyCanvasUnitOfWork(SessionLocal) as uow:
        assert uow.canvases.get(canvas.id) is None
