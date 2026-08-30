from __future__ import annotations

import io
import zipfile

import pytest

from app.r2_training_storage import (
    R2TrainingDatasetStore,
    R2TrainingSettings,
    R2TrainingStorageError,
    build_captioned_lora_archive,
)


class FakeR2Client:
    def __init__(self):
        self.put = None
        self.presign = None

    def put_object(self, **kwargs):
        self.put = kwargs
        return {"ETag": '"test"'}

    def generate_presigned_url(self, operation, *, Params, ExpiresIn):
        self.presign = {"operation": operation, "params": Params, "expires_in": ExpiresIn}
        return f"https://account.r2.cloudflarestorage.com/{Params['Bucket']}/{Params['Key']}?X-Amz-Signature=test"


def test_captioned_archive_contains_images_and_matching_captions():
    archive = build_captioned_lora_archive(
        [(f"view_{index}", f"image-{index}".encode(), "png") for index in range(4)],
        trigger_word="mori_catgirl_v1",
    )
    with zipfile.ZipFile(io.BytesIO(archive)) as dataset:
        images = [name for name in dataset.namelist() if name.endswith(".png")]
        captions = [dataset.read(name).decode() for name in dataset.namelist() if name.endswith(".txt")]
    assert len(images) == 4
    assert len(captions) == 4
    assert all(caption.startswith("mori_catgirl_v1") for caption in captions)


def test_r2_training_store_uploads_private_zip_and_returns_presigned_get_url():
    client = FakeR2Client()
    settings = R2TrainingSettings(
        account_id="account",
        bucket="frameflow-lora-training",
        access_key_id="access",
        secret_access_key="secret",
        endpoint_url="https://account.r2.cloudflarestorage.com",
        key_prefix="lora-training",
        signed_url_ttl_seconds=3600,
    )
    stored = R2TrainingDatasetStore(settings, client=client).put_archive(character_id="character_1", archive=b"zip-bytes")

    assert client.put["Bucket"] == "frameflow-lora-training"
    assert client.put["ContentType"] == "application/zip"
    assert client.put["ContentLength"] == len(b"zip-bytes")
    assert stored.key.startswith("lora-training/character_1/")
    assert stored.key.endswith(".zip")
    assert stored.uri.startswith("r2://frameflow-lora-training/")
    assert stored.download_url.startswith("https://account.r2.cloudflarestorage.com/")
    assert client.presign == {
        "operation": "get_object",
        "params": {"Bucket": "frameflow-lora-training", "Key": stored.key},
        "expires_in": 3600,
    }


def test_r2_training_settings_require_bucket_scoped_credentials(monkeypatch):
    for key in ("R2_ACCOUNT_ID", "R2_TRAINING_BUCKET", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_ENDPOINT_URL"):
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(R2TrainingStorageError, match="Settings → Cloudflare R2"):
        R2TrainingSettings.from_env()
