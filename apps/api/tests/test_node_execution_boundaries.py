from pathlib import Path


def test_provider_executors_use_artifact_port_instead_of_database_session() -> None:
    executor_root = Path(__file__).parents[1] / "app" / "nodes" / "executors"

    for filename in (
        "image_generation.py",
        "video_generation.py",
        "speech_generation.py",
        "text_support.py",
    ):
        source = (executor_root / filename).read_text()
        assert "context.db" not in source, filename
        assert "create_artifact" not in source, filename
        assert "get_storage" not in source, filename
        assert "from .media_support import load_input_media" not in source, filename
        assert "require_artifact_store" in source, filename


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
