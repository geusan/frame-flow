from fastapi.routing import APIRoute

from app.api.routers.canvases import router as canvases_router
from app.api.routers.runs import router as runs_router
from app.api.routers.workflows import router as workflows_router
from app.main import app


CANVAS_OPERATIONS = {
    ("GET", "/canvases"),
    ("POST", "/canvases"),
    ("POST", "/canvases/import"),
    ("GET", "/canvases/{canvas_id}"),
    ("GET", "/canvases/{canvas_id}/export"),
    ("PUT", "/canvases/{canvas_id}"),
    ("DELETE", "/canvases/{canvas_id}"),
}

WORKFLOW_OPERATIONS = {
    ("POST", "/workflows"),
    ("GET", "/workflows"),
    ("GET", "/workflows/{workflow_id}"),
    ("PATCH", "/workflows/{workflow_id}"),
    ("POST", "/workflows/{workflow_id}/publish"),
    ("POST", "/workflows/{workflow_id}/runs"),
    ("GET", "/workflows/{workflow_id}/versions"),
    ("GET", "/workflows/{workflow_id}/versions/{version_number}"),
    ("GET", "/workflows/{workflow_id}/annotations"),
    ("POST", "/workflows/{workflow_id}/annotations"),
    ("GET", "/workflows/{workflow_id}/versions/{version_number}/annotations"),
    ("POST", "/workflows/{workflow_id}/versions/{version_number}/annotations"),
    ("PATCH", "/workflow-annotations/{annotation_id}"),
    ("DELETE", "/workflow-annotations/{annotation_id}"),
    ("POST", "/workflows/{workflow_id}/archive"),
    ("POST", "/workflows/{workflow_id}/activate"),
    ("GET", "/workflow-runs"),
}

RUN_OPERATIONS = {
    ("POST", "/experiments"),
    ("GET", "/experiments"),
    ("POST", "/experiments/{experiment_id}/baseline"),
    ("POST", "/canvas-runs"),
    ("GET", "/canvas-runs/{run_id}"),
    ("GET", "/canvas-runs/{run_id}/events"),
    ("POST", "/canvas-runs/{run_id}/cancel"),
    ("POST", "/canvas-runs/{run_id}/nodes/{canvas_node_id}/select"),
    ("POST", "/canvas-runs/{run_id}/nodes/{canvas_node_id}/approve"),
    ("POST", "/generation-runs"),
    ("GET", "/runs/{run_id}"),
    ("GET", "/runs"),
    ("POST", "/runs/{run_id}/cancel"),
    ("GET", "/runs/{run_id}/events"),
    ("POST", "/node-runs/{node_run_id}/retry"),
    ("POST", "/node-runs/{node_run_id}/regenerate"),
    ("POST", "/node-runs/{node_run_id}/fork"),
    ("POST", "/node-runs/{node_run_id}/select"),
}


def _operations(routes: list[object]) -> list[tuple[str, str, str]]:
    operations: list[tuple[str, str, str]] = []
    for route in routes:
        if isinstance(route, APIRoute):
            operations.extend(
                (method, route.path, route.endpoint.__module__)
                for method in route.methods
            )
            continue
        included_router = getattr(route, "original_router", None)
        nested_routes = getattr(included_router, "routes", None)
        if nested_routes is None:
            nested_routes = getattr(route, "routes", None)
        if nested_routes is not None:
            operations.extend(_operations(nested_routes))
    return operations


def test_canvas_endpoints_are_owned_by_the_canvas_router() -> None:
    operations = _operations(canvases_router.routes)

    assert {(method, path) for method, path, _ in operations} == CANVAS_OPERATIONS
    assert {module for _, _, module in operations} == {"app.api.routers.canvases"}


def test_canvas_router_is_registered_once_in_the_http_app() -> None:
    operations = _operations(app.routes)

    for method, path in CANVAS_OPERATIONS:
        assert sum(
            registered_method == method and registered_path == path
            for registered_method, registered_path, _ in operations
        ) == 1


def test_workflow_endpoints_are_owned_by_the_workflow_router() -> None:
    operations = _operations(workflows_router.routes)

    assert {(method, path) for method, path, _ in operations} == WORKFLOW_OPERATIONS
    assert {module for _, _, module in operations} == {"app.api.routers.workflows"}


def test_workflow_router_is_registered_once_in_the_http_app() -> None:
    operations = _operations(app.routes)

    for method, path in WORKFLOW_OPERATIONS:
        assert sum(
            registered_method == method and registered_path == path
            for registered_method, registered_path, _ in operations
        ) == 1


def test_run_endpoints_are_owned_by_the_run_router() -> None:
    operations = _operations(runs_router.routes)

    assert {(method, path) for method, path, _ in operations} == RUN_OPERATIONS
    assert {module for _, _, module in operations} == {"app.api.routers.runs"}


def test_run_router_is_registered_once_in_the_http_app() -> None:
    operations = _operations(app.routes)

    for method, path in RUN_OPERATIONS:
        assert sum(
            registered_method == method and registered_path == path
            for registered_method, registered_path, _ in operations
        ) == 1
