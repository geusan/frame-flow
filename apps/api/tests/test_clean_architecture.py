from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from app.domain import ExperimentRunRequest
from app.nodes import node_registry


API_ROOT = Path(__file__).parents[1] / "app"
REPOSITORY_ROOT = Path(__file__).parents[3]


def _python_sources(root: Path) -> list[Path]:
    return [path for path in root.rglob("*.py") if "__pycache__" not in path.parts]


def test_application_contexts_do_not_depend_on_framework_or_infrastructure() -> None:
    forbidden = (
        "from fastapi",
        "from sqlalchemy",
        "import sqlalchemy",
        "infrastructure.",
        "from ...database",
        "from ....database",
    )
    for path in _python_sources(API_ROOT / "contexts"):
        source = path.read_text()
        for dependency in forbidden:
            assert dependency not in source, f"{path}: {dependency}"


def test_http_routers_do_not_open_database_sessions() -> None:
    for path in _python_sources(API_ROOT / "api" / "routers"):
        source = path.read_text()
        assert "from sqlalchemy" not in source, path
        assert "get_db" not in source, path
        assert "SessionLocal" not in source, path


def test_node_executors_depend_on_ports_not_legacy_persistence_modules() -> None:
    for path in _python_sources(API_ROOT / "nodes" / "executors"):
        source = path.read_text()
        assert "context.db" not in source, path
        assert "from sqlalchemy" not in source, path
        assert "from ...database" not in source, path
        assert "from ...canvas_operations" not in source, path


def test_provider_capabilities_do_not_interpret_canvas_node_keys() -> None:
    for filename in ("providers_generation.py", "providers_openai.py", "providers_fal.py"):
        source = (API_ROOT / filename).read_text()
        assert "payload.node_key" not in source, filename
        assert "ExperimentRunRequest" not in source, filename


def test_registered_experiments_have_no_central_execution_fallback() -> None:
    source = (API_ROOT / "experiments.py").read_text()
    assert "execute_canvas_operation" not in source
    assert "execute_live_provider" not in source
    assert "execute_fixture" not in source


def test_human_gate_schedulers_do_not_branch_on_type_key() -> None:
    for filename in ("canvas_runs.py", "canvas_temporal.py", "workflow_runtime_service.py"):
        source = (API_ROOT / filename).read_text()
        assert '== "candidate.select"' not in source, filename
        assert "node.node_key ==" not in source, filename


def test_all_active_executable_contracts_have_registry_capabilities(monkeypatch) -> None:
    monkeypatch.setenv("GENERATION_PROVIDER_MODE", "fixture")
    for definition in node_registry.list(lifecycle="ACTIVE"):
        if definition.execution.kind == "source":
            continue
        payload = ExperimentRunRequest(
            canvas_id="architecture",
            node_id="node",
            node_key=definition.type_key,
            node_contract_version=definition.contract_version,
            model_alias=definition.execution.model_alias,
            parameters={},
            inputs=[],
        )
        context = SimpleNamespace(
            definition=definition,
            model_alias=payload.model_alias,
            prompt=payload.prompt,
        )
        assert node_registry.can_execute(context), (
            f"{definition.type_key}@{definition.contract_version} has no executor capability"
        )


def test_web_uses_registry_templates_for_production_nodes() -> None:
    canvas_model = (REPOSITORY_ROOT / "packages/studio/src/lib/canvas-model.ts").read_text()
    canvas_view = (REPOSITORY_ROOT / "packages/studio/src/components/views/generation-canvas.tsx").read_text()
    assert "export const nodeTemplates" not in canvas_model
    assert "legacyNodeTemplates" not in canvas_model
    assert "execute_canvas_operation" not in (REPOSITORY_ROOT / "apps/api/app/canvas_operations.py").read_text()
    assert "latestNodeTemplates(definitions" in canvas_view
    assert "createNodeFromTemplate(templateId: string, position: XYPosition, sequence: number, templates: NodeTemplate[])" in canvas_model
