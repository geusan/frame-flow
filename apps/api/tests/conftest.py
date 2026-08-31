import os
from pathlib import Path

TEST_DB = Path(__file__).parent / f"test_video_canvas_{os.getpid()}.db"
if TEST_DB.exists():
    TEST_DB.unlink()
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB}"
os.environ["STORAGE_PROVIDER"] = "memory"
os.environ["APP_ENV"] = "test"
os.environ["GENERATION_PROVIDER_MODE"] = "fixture"
os.environ["REFERENCE_PROVIDER_MODE"] = "fixture"
os.environ["VIDEO_DOWNLOADER_PROVIDER"] = "fixture"
os.environ["SCENE_SEARCH_PROVIDER_MODE"] = "fixture"
os.environ["FORMAT_PROVIDER_MODE"] = "fixture"
os.environ["SUBTITLE_ALIGNMENT_MODE"] = "heuristic"
os.environ["REFERENCE_ANALYSIS_MODE"] = "fixture"
os.environ["REFERENCE_AUDIO_SEPARATOR"] = "fixture"

import pytest
from fastapi.testclient import TestClient

from app.database import Base, engine
from app.main import app


@pytest.fixture()
def client():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as test_client:
        yield test_client


def pytest_sessionfinish(session, exitstatus):
    del session, exitstatus
    engine.dispose()
    if TEST_DB.exists():
        TEST_DB.unlink()
