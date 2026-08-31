import os
from pathlib import Path


# Tests must not inherit a developer's live provider or object-storage setup.
# Individual tests opt into the settings they exercise with monkeypatch.
ISOLATED_ENV_KEYS = (
    "STORAGE_PROVIDER",
    "STORAGE_ENDPOINT",
    "STORAGE_PUBLIC_ENDPOINT",
    "STORAGE_REGION",
    "STORAGE_AUTO_CREATE_BUCKETS",
    "STORAGE_ACCESS_KEY",
    "STORAGE_SECRET_KEY",
    "R2_ACCOUNT_ID",
    "R2_ACCESS_KEY_ID",
    "R2_SECRET_ACCESS_KEY",
    "R2_ENDPOINT_URL",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "GOOGLE_CLOUD_PROJECT",
    "GOOGLE_CLOUD_LOCATION",
    "GOOGLE_SPEECH_LOCATION",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "GOOGLE_SERVICE_ACCOUNT_JSON",
    "GOOGLE_VIDEO_OUTPUT_GCS_URI",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "OPENAI_ORG_ID",
    "OPENAI_PROJECT_ID",
    "FAL_KEY",
)
for env_key in ISOLATED_ENV_KEYS:
    os.environ.pop(env_key, None)

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
