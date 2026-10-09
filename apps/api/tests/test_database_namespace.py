from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import Session
import pytest

from app.database_models import build_models
from app.database_namespace import configure_table_prefix


def test_independent_model_namespaces_preserve_foreign_keys_and_data():
    engine = create_engine("sqlite://")
    first, second = build_models("first_"), build_models("second_")
    first["Base"].metadata.create_all(engine)
    second["Base"].metadata.create_all(engine)
    for models, value in ((first, "first canvas"), (second, "second canvas")):
        with Session(engine) as db:
            db.add(models["WorkspaceRecord"](id="same-id", name=value, status="active"))
            db.add(models["CanvasRecord"](id="same-canvas", name=value, workspace_id="same-id", graph_json={}))
            db.commit()
    with Session(engine) as db:
        assert db.get(first["CanvasRecord"], "same-canvas").name == "first canvas"
        assert db.get(second["CanvasRecord"], "same-canvas").name == "second canvas"
    assert {fk["referred_table"] for fk in inspect(engine).get_foreign_keys("first_canvases")} == {"first_workspaces"}
    engine.dispose()


def test_runtime_namespace_cannot_change_after_orm_import():
    with pytest.raises(RuntimeError, match="fixed"):
        configure_table_prefix("changed_")


def test_namespace_rejects_sql_identifiers_from_untrusted_input():
    with pytest.raises(ValueError):
        build_models("unsafe; DROP TABLE users_")
