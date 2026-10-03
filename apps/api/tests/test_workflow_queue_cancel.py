import pytest

from app.database import CanvasRunRecord, SessionLocal
from app.domain import NodeStatus


@pytest.mark.parametrize("status", [NodeStatus.SUCCEEDED, NodeStatus.FAILED, NodeStatus.CANCELED])
def test_cancel_keeps_terminal_workflow_run_unchanged(client, monkeypatch, status):
    from app.infrastructure.persistence import run_operations

    async def unexpected_temporal_call():
        raise AssertionError("Terminal runs must not request Temporal cancellation")

    monkeypatch.setattr(run_operations, "uses_temporal", lambda: True)
    monkeypatch.setattr(run_operations, "temporal_client", unexpected_temporal_call)
    with SessionLocal() as db:
        run = CanvasRunRecord(id="queue-terminal", canvas_id="queue-canvas", name="Queue", status=status, progress=100, graph_snapshot={"nodes": [], "edges": []})
        db.add(run)
        db.commit()
    response = client.post("/canvas-runs/queue-terminal/cancel")
    assert response.status_code == 200
    assert response.json()["status"] == status.value
    with SessionLocal() as db:
        stored = db.get(CanvasRunRecord, "queue-terminal")
        assert stored.status == status
        assert stored.canceled_at is None


def test_cancel_active_run_is_idempotent(client, monkeypatch):
    from app.infrastructure.persistence import run_operations

    monkeypatch.setattr(run_operations, "uses_temporal", lambda: False)
    with SessionLocal() as db:
        db.add(CanvasRunRecord(id="queue-active", canvas_id="queue-canvas", name="Queue", status=NodeStatus.RUNNING, progress=20, graph_snapshot={"nodes": [], "edges": []}))
        db.commit()
    first = client.post("/canvas-runs/queue-active/cancel")
    assert first.status_code == 200
    assert first.json()["status"] == "CANCELED"
    with SessionLocal() as db:
        canceled_at = db.get(CanvasRunRecord, "queue-active").canceled_at
    second = client.post("/canvas-runs/queue-active/cancel")
    assert second.status_code == 200
    with SessionLocal() as db:
        assert db.get(CanvasRunRecord, "queue-active").canceled_at == canceled_at
