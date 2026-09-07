from pathlib import Path


def test_image_executor_uses_artifact_port_instead_of_database_session() -> None:
    source = (
        Path(__file__).parents[1]
        / "app"
        / "nodes"
        / "executors"
        / "image_generation.py"
    ).read_text()

    assert "context.db" not in source
    assert "create_artifact" not in source
    assert "get_storage" not in source
    assert "from .media_support import load_input_media" not in source
    assert "require_artifact_store" in source


def test_node_contract_does_not_expose_sqlalchemy_through_artifact_port() -> None:
    source = (
        Path(__file__).parents[1] / "app" / "nodes" / "contracts.py"
    ).read_text()
    artifact_boundary = source.split("class NodeArtifactStore", 1)[1].split(
        "class NodeExecutionContext",
        1,
    )[0]

    assert "Session" not in artifact_boundary
    assert "ArtifactRecord" not in artifact_boundary
