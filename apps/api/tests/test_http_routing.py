from fastapi.routing import APIRoute

from app.api.routers.artifacts import router as artifacts_router
from app.api.routers.canvases import router as canvases_router
from app.api.routers.fonts import router as fonts_router
from app.api.routers.formats import router as formats_router
from app.api.routers.generation import router as generation_router
from app.api.routers.references import router as references_router
from app.api.routers.runs import router as runs_router
from app.api.routers.settings import router as settings_router
from app.api.routers.skills import router as skills_router
from app.api.routers.system import router as system_router
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
    ("POST", "/workflows/{workflow_id}/versions/{version_number}/restore-draft"),
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
    ("GET", "/costs"),
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

ARTIFACT_OPERATIONS = {
    ("GET", "/artifacts"),
    ("GET", "/characters"),
    ("POST", "/characters/{character_id}/lora-training"),
    ("GET", "/characters/{character_id}/lora-training"),
    ("GET", "/artifacts/{artifact_id}"),
    ("POST", "/artifacts/{artifact_id}/audio-asset"),
    ("GET", "/artifacts/{artifact_id}/lineage"),
    ("POST", "/artifacts/{artifact_id}/scene-search"),
    ("POST", "/artifacts/{artifact_id}/capture-frame"),
    ("GET", "/artifacts/{artifact_id}/frame-preview"),
    ("POST", "/artifacts/upload-url"),
    ("POST", "/artifacts/import-url"),
    ("POST", "/artifacts/upload"),
    ("POST", "/artifacts/{artifact_id}/image-edits"),
    ("GET", "/artifacts/{artifact_id}/download-url"),
    ("GET", "/artifacts/{artifact_id}/content"),
}

REFERENCE_OPERATIONS = {
    ("POST", "/references/inspect"),
    ("POST", "/references/import"),
    ("GET", "/references"),
    ("POST", "/reference-sets"),
}

FORMAT_OPERATIONS = {
    ("POST", "/extraction-recipes"),
    ("POST", "/format-runs"),
    ("GET", "/formats/{format_id}"),
    ("GET", "/formats"),
    ("POST", "/formats/{format_id}/variants"),
    ("POST", "/formats/merge"),
}

GENERATION_OPERATIONS = {
    ("POST", "/generation-briefs"),
}

SETTINGS_OPERATIONS = {
    ("GET", "/settings/providers"),
    ("PUT", "/settings/providers/{provider}"),
    ("GET", "/settings/storage"),
    ("POST", "/settings/storage/profiles"),
    ("POST", "/settings/storage/profiles/{profile_id}/test"),
    ("POST", "/settings/storage/profiles/{profile_id}/activate"),
    ("GET", "/settings/storage/profiles/{profile_id}/migration-plan"),
    ("POST", "/settings/storage/migrate"),
    ("PUT", "/settings/storage/profiles/{profile_id}/credentials"),
    ("GET", "/models"),
}

FONT_OPERATIONS = {
    ("GET", "/fonts"),
    ("POST", "/fonts"),
    ("GET", "/fonts/google"),
    ("POST", "/fonts/google/import"),
    ("GET", "/fonts/noonnu"),
    ("GET", "/fonts/noonnu/{font_id}"),
    ("POST", "/fonts/noonnu/import"),
    ("PATCH", "/fonts/{font_id}"),
}

SKILL_OPERATIONS = {
    ("GET", "/skills"),
    ("POST", "/skills"),
    ("POST", "/skills/{skill_id}/versions"),
    ("GET", "/skills/{skill_id}/versions"),
    ("POST", "/skills/{skill_id}/versions/{version_number}/activate"),
    ("PUT", "/skills/{skill_id}/installation"),
}

SYSTEM_OPERATIONS = {
    ("GET", "/health"),
    ("GET", "/node-definitions"),
    ("GET", "/node-port-types"),
    ("GET", "/workspace/summary"),
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


def test_artifact_endpoints_are_owned_by_the_artifact_router() -> None:
    operations = _operations(artifacts_router.routes)

    assert {(method, path) for method, path, _ in operations} == ARTIFACT_OPERATIONS
    assert {module for _, _, module in operations} == {"app.api.routers.artifacts"}


def test_artifact_router_is_registered_once_in_the_http_app() -> None:
    operations = _operations(app.routes)

    for method, path in ARTIFACT_OPERATIONS:
        assert sum(
            registered_method == method and registered_path == path
            for registered_method, registered_path, _ in operations
        ) == 1


def test_reference_endpoints_are_owned_by_the_reference_router() -> None:
    operations = _operations(references_router.routes)

    assert {(method, path) for method, path, _ in operations} == REFERENCE_OPERATIONS
    assert {module for _, _, module in operations} == {"app.api.routers.references"}


def test_reference_router_is_registered_once_in_the_http_app() -> None:
    operations = _operations(app.routes)

    for method, path in REFERENCE_OPERATIONS:
        assert sum(
            registered_method == method and registered_path == path
            for registered_method, registered_path, _ in operations
        ) == 1


def test_format_endpoints_are_owned_by_the_format_router() -> None:
    operations = _operations(formats_router.routes)

    assert {(method, path) for method, path, _ in operations} == FORMAT_OPERATIONS
    assert {module for _, _, module in operations} == {"app.api.routers.formats"}


def test_format_router_is_registered_once_in_the_http_app() -> None:
    operations = _operations(app.routes)

    for method, path in FORMAT_OPERATIONS:
        assert sum(
            registered_method == method and registered_path == path
            for registered_method, registered_path, _ in operations
        ) == 1


def test_generation_endpoints_are_owned_by_the_generation_router() -> None:
    operations = _operations(generation_router.routes)

    assert {(method, path) for method, path, _ in operations} == GENERATION_OPERATIONS
    assert {module for _, _, module in operations} == {"app.api.routers.generation"}


def test_generation_router_is_registered_once_in_the_http_app() -> None:
    operations = _operations(app.routes)

    for method, path in GENERATION_OPERATIONS:
        assert sum(
            registered_method == method and registered_path == path
            for registered_method, registered_path, _ in operations
        ) == 1


def test_settings_endpoints_are_owned_by_the_settings_router() -> None:
    operations = _operations(settings_router.routes)

    assert {(method, path) for method, path, _ in operations} == SETTINGS_OPERATIONS
    assert {module for _, _, module in operations} == {"app.api.routers.settings"}


def test_settings_router_is_registered_once_in_the_http_app() -> None:
    operations = _operations(app.routes)

    for method, path in SETTINGS_OPERATIONS:
        assert sum(
            registered_method == method and registered_path == path
            for registered_method, registered_path, _ in operations
        ) == 1


def test_font_endpoints_are_owned_by_the_font_router() -> None:
    operations = _operations(fonts_router.routes)

    assert {(method, path) for method, path, _ in operations} == FONT_OPERATIONS
    assert {module for _, _, module in operations} == {"app.api.routers.fonts"}


def test_font_router_is_registered_once_in_the_http_app() -> None:
    operations = _operations(app.routes)

    for method, path in FONT_OPERATIONS:
        assert sum(
            registered_method == method and registered_path == path
            for registered_method, registered_path, _ in operations
        ) == 1


def test_skill_endpoints_are_owned_by_the_skill_router() -> None:
    operations = _operations(skills_router.routes)

    assert {(method, path) for method, path, _ in operations} == SKILL_OPERATIONS
    assert {module for _, _, module in operations} == {"app.api.routers.skills"}


def test_skill_router_is_registered_once_in_the_http_app() -> None:
    operations = _operations(app.routes)

    for method, path in SKILL_OPERATIONS:
        assert sum(
            registered_method == method and registered_path == path
            for registered_method, registered_path, _ in operations
        ) == 1


def test_system_endpoints_are_owned_by_the_system_router() -> None:
    operations = _operations(system_router.routes)

    assert {(method, path) for method, path, _ in operations} == SYSTEM_OPERATIONS
    assert {module for _, _, module in operations} == {"app.api.routers.system"}


def test_system_router_is_registered_once_in_the_http_app() -> None:
    operations = _operations(app.routes)

    for method, path in SYSTEM_OPERATIONS:
        assert sum(
            registered_method == method and registered_path == path
            for registered_method, registered_path, _ in operations
        ) == 1
