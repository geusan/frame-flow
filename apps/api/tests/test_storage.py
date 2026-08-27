from __future__ import annotations

from app.storage import (
    MemoryObjectStorage,
    StorageSettings,
    artifact_object_key,
    bucket_for_artifact,
    safe_upload_key,
)


def test_memory_storage_persists_bytes_and_signs_the_same_object():
    settings = StorageSettings.from_env()
    storage = MemoryObjectStorage(settings)
    stored = storage.put_bytes(
        bucket=settings.buckets.generation,
        key="artifacts/image/art_test.svg",
        data=b"<svg/>",
        content_type="image/svg+xml",
    )
    assert stored.sha256 == "d4dc56669143034f31aa309635d4113d9ad76a02b1739da22c965ed2049be9e6"
    assert stored.size_bytes == 6
    assert storage.get_bytes(bucket=stored.bucket, key=stored.key) == b"<svg/>"
    assert storage.create_download_url(bucket=stored.bucket, key=stored.key) == stored.uri


def test_storage_settings_switch_from_minio_to_r2(monkeypatch):
    monkeypatch.setenv("STORAGE_PROVIDER", "r2")
    monkeypatch.setenv("R2_ACCOUNT_ID", "abc123")
    monkeypatch.setenv("STORAGE_ACCESS_KEY", "access")
    monkeypatch.setenv("STORAGE_SECRET_KEY", "secret")
    monkeypatch.delenv("STORAGE_ENDPOINT", raising=False)
    monkeypatch.delenv("STORAGE_PUBLIC_ENDPOINT", raising=False)
    monkeypatch.delenv("STORAGE_AUTO_CREATE_BUCKETS", raising=False)
    settings = StorageSettings.from_env()
    assert settings.provider == "r2"
    assert settings.endpoint_url == "https://abc123.r2.cloudflarestorage.com"
    assert settings.region == "auto"
    assert settings.auto_create_buckets is False


def test_artifact_bucket_and_keys_are_deterministic_and_path_safe():
    settings = StorageSettings.from_env()
    assert bucket_for_artifact(settings, "ReferenceOriginal") == settings.buckets.reference
    assert bucket_for_artifact(settings, "Image") == settings.buckets.generation
    assert artifact_object_key("Video", "art_123", "video/mp4") == "artifacts/video/art_123.mp4"
    assert safe_upload_key("upload_123", "../../my clip.mp4") == "uploads/upload_123/my-clip.mp4"
