from __future__ import annotations

import hashlib
import mimetypes
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import PurePath
from typing import Any, Protocol
from urllib.parse import urlparse

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError


class StorageError(RuntimeError):
    pass


@dataclass(frozen=True)
class StorageBuckets:
    reference: str
    formats: str
    generation: str
    renders: str

    def all(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys((self.reference, self.formats, self.generation, self.renders)))


@dataclass(frozen=True)
class StorageSettings:
    provider: str
    endpoint_url: str | None
    public_endpoint_url: str | None
    access_key: str | None
    secret_key: str | None
    region: str
    auto_create_buckets: bool
    signed_url_ttl_seconds: int
    buckets: StorageBuckets

    @classmethod
    def from_env(cls) -> "StorageSettings":
        provider = os.getenv("STORAGE_PROVIDER", "minio").strip().lower()
        if provider not in {"memory", "minio", "r2", "s3"}:
            raise StorageError("STORAGE_PROVIDER must be one of: memory, minio, r2, s3")

        endpoint = os.getenv("STORAGE_ENDPOINT")
        public_endpoint = os.getenv("STORAGE_PUBLIC_ENDPOINT")
        access_key = os.getenv("STORAGE_ACCESS_KEY")
        secret_key = os.getenv("STORAGE_SECRET_KEY")
        region = os.getenv("STORAGE_REGION", "auto" if provider == "r2" else "us-east-1")

        if provider == "minio":
            endpoint = endpoint or "http://localhost:9000"
            public_endpoint = public_endpoint or endpoint
            access_key = access_key or "frameflow"
            secret_key = secret_key or "frameflow-local-secret"
        elif provider == "r2":
            account_id = os.getenv("R2_ACCOUNT_ID")
            endpoint = endpoint or (f"https://{account_id}.r2.cloudflarestorage.com" if account_id else None)
            public_endpoint = public_endpoint or endpoint

        if provider != "memory" and (not endpoint or not access_key or not secret_key):
            raise StorageError(
                f"{provider} storage requires STORAGE_ENDPOINT (or R2_ACCOUNT_ID), "
                "STORAGE_ACCESS_KEY, and STORAGE_SECRET_KEY"
            )

        auto_create_default = provider == "minio"
        auto_create = os.getenv("STORAGE_AUTO_CREATE_BUCKETS", str(auto_create_default)).lower() in {"1", "true", "yes"}
        ttl = int(os.getenv("STORAGE_SIGNED_URL_TTL_SECONDS", "900"))
        if not 1 <= ttl <= 604_800:
            raise StorageError("STORAGE_SIGNED_URL_TTL_SECONDS must be between 1 and 604800")

        return cls(
            provider=provider,
            endpoint_url=endpoint,
            public_endpoint_url=public_endpoint,
            access_key=access_key,
            secret_key=secret_key,
            region=region,
            auto_create_buckets=auto_create,
            signed_url_ttl_seconds=ttl,
            buckets=StorageBuckets(
                reference=os.getenv("STORAGE_BUCKET_REFERENCE", "project-reference-private"),
                formats=os.getenv("STORAGE_BUCKET_FORMATS", "project-derived-formats"),
                generation=os.getenv("STORAGE_BUCKET_GENERATION", "project-generation-assets"),
                renders=os.getenv("STORAGE_BUCKET_RENDERS", "project-final-renders"),
            ),
        )


@dataclass(frozen=True)
class StoredObject:
    provider: str
    bucket: str
    key: str
    uri: str
    size_bytes: int
    sha256: str
    content_type: str
    etag: str | None = None


@dataclass(frozen=True)
class UploadTarget:
    provider: str
    bucket: str
    key: str
    uri: str
    url: str
    expires_in_seconds: int
    headers: dict[str, str]


class ObjectStorage(Protocol):
    settings: StorageSettings

    def initialize(self) -> None: ...

    def put_bytes(
        self,
        *,
        bucket: str,
        key: str,
        data: bytes,
        content_type: str,
        metadata: dict[str, str] | None = None,
    ) -> StoredObject: ...

    def get_bytes(self, *, bucket: str, key: str) -> bytes: ...

    def create_download_url(self, *, bucket: str, key: str) -> str: ...

    def create_upload_url(self, *, bucket: str, key: str, content_type: str) -> UploadTarget: ...


class MemoryObjectStorage:
    def __init__(self, settings: StorageSettings) -> None:
        self.settings = settings
        self.objects: dict[tuple[str, str], tuple[bytes, str, dict[str, str]]] = {}

    def initialize(self) -> None:
        return None

    def put_bytes(
        self,
        *,
        bucket: str,
        key: str,
        data: bytes,
        content_type: str,
        metadata: dict[str, str] | None = None,
    ) -> StoredObject:
        digest = hashlib.sha256(data).hexdigest()
        self.objects[(bucket, key)] = (data, content_type, metadata or {})
        return StoredObject("memory", bucket, key, f"memory://{bucket}/{key}", len(data), digest, content_type, digest)

    def get_bytes(self, *, bucket: str, key: str) -> bytes:
        try:
            return self.objects[(bucket, key)][0]
        except KeyError as exc:
            raise StorageError(f"object does not exist: {bucket}/{key}") from exc

    def create_download_url(self, *, bucket: str, key: str) -> str:
        if (bucket, key) not in self.objects:
            raise StorageError(f"object does not exist: {bucket}/{key}")
        return f"memory://{bucket}/{key}"

    def create_upload_url(self, *, bucket: str, key: str, content_type: str) -> UploadTarget:
        return UploadTarget(
            "memory", bucket, key, f"memory://{bucket}/{key}", f"memory://{bucket}/{key}",
            self.settings.signed_url_ttl_seconds, {"content-type": content_type},
        )


class S3CompatibleObjectStorage:
    def __init__(self, settings: StorageSettings, *, client: Any | None = None, public_client: Any | None = None) -> None:
        self.settings = settings
        self.client = client or self._client(settings.endpoint_url)
        self.public_client = public_client or self._client(settings.public_endpoint_url or settings.endpoint_url)

    def _client(self, endpoint_url: str | None) -> Any:
        return boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=self.settings.access_key,
            aws_secret_access_key=self.settings.secret_key,
            region_name=self.settings.region,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

    def initialize(self) -> None:
        if not self.settings.auto_create_buckets:
            return
        for bucket in self.settings.buckets.all():
            try:
                self.client.head_bucket(Bucket=bucket)
            except ClientError as exc:
                status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
                code = str(exc.response.get("Error", {}).get("Code", ""))
                if status != 404 and code not in {"404", "NoSuchBucket", "NotFound"}:
                    raise StorageError(f"could not inspect storage bucket {bucket}: {code or status}") from exc
                try:
                    self.client.create_bucket(Bucket=bucket)
                except ClientError as create_exc:
                    create_code = create_exc.response.get("Error", {}).get("Code", "unknown")
                    raise StorageError(f"could not create storage bucket {bucket}: {create_code}") from create_exc

    def put_bytes(
        self,
        *,
        bucket: str,
        key: str,
        data: bytes,
        content_type: str,
        metadata: dict[str, str] | None = None,
    ) -> StoredObject:
        digest = hashlib.sha256(data).hexdigest()
        try:
            response = self.client.put_object(
                Bucket=bucket,
                Key=key,
                Body=data,
                ContentLength=len(data),
                ContentType=content_type,
                Metadata={"sha256": digest, **(metadata or {})},
            )
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "unknown")
            raise StorageError(f"failed to store object {bucket}/{key}: {code}") from exc
        return StoredObject(
            self.settings.provider,
            bucket,
            key,
            f"s3://{bucket}/{key}",
            len(data),
            digest,
            content_type,
            response.get("ETag", "").strip('"') or None,
        )

    def get_bytes(self, *, bucket: str, key: str) -> bytes:
        try:
            response = self.client.get_object(Bucket=bucket, Key=key)
            return response["Body"].read()
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "unknown")
            raise StorageError(f"failed to read object {bucket}/{key}: {code}") from exc

    def create_download_url(self, *, bucket: str, key: str) -> str:
        try:
            return self.public_client.generate_presigned_url(
                "get_object",
                Params={"Bucket": bucket, "Key": key},
                ExpiresIn=self.settings.signed_url_ttl_seconds,
            )
        except ClientError as exc:
            raise StorageError(f"failed to sign download URL for {bucket}/{key}") from exc

    def create_upload_url(self, *, bucket: str, key: str, content_type: str) -> UploadTarget:
        try:
            url = self.public_client.generate_presigned_url(
                "put_object",
                Params={"Bucket": bucket, "Key": key, "ContentType": content_type},
                ExpiresIn=self.settings.signed_url_ttl_seconds,
            )
        except ClientError as exc:
            raise StorageError(f"failed to sign upload URL for {bucket}/{key}") from exc
        return UploadTarget(
            self.settings.provider,
            bucket,
            key,
            f"s3://{bucket}/{key}",
            url,
            self.settings.signed_url_ttl_seconds,
            {"content-type": content_type},
        )


REFERENCE_TYPES = {
    "ReferenceOriginal",
    "ProxyVideo",
    "Thumbnail",
    "Subtitle",
    "ReferenceAnalysis",
    "ReferenceAudioMix",
    "ReferenceTranscript",
    "ReferenceSubtitle",
    "ReferenceVocals",
    "ReferenceAccompaniment",
}
FORMAT_TYPES = {"FormatProfile", "GenerationSpec", "Script", "TimedScript", "ShotPlan", "Timeline"}
RENDER_TYPES = {"QCReport", "FinalVideo"}


def bucket_for_artifact(settings: StorageSettings, artifact_type: str, metadata: dict[str, Any] | None = None) -> str:
    scope = str((metadata or {}).get("storage_scope", ""))
    if scope in {"reference", "formats", "generation", "renders"}:
        return getattr(settings.buckets, scope)
    if artifact_type in REFERENCE_TYPES:
        return settings.buckets.reference
    if artifact_type in FORMAT_TYPES:
        return settings.buckets.formats
    if artifact_type in RENDER_TYPES:
        return settings.buckets.renders
    return settings.buckets.generation


def extension_for(content_type: str, filename: str | None = None) -> str:
    if filename:
        suffix = PurePath(filename).suffix.lower()
        if re.fullmatch(r"\.[a-z0-9]{1,10}", suffix):
            return suffix
    overrides = {
        "image/svg+xml": ".svg",
        "video/mp4": ".mp4",
        "audio/wav": ".wav",
        "audio/pcm": ".pcm",
        "application/json": ".json",
        "text/plain": ".txt",
    }
    normalized = content_type.split(";", 1)[0].lower()
    return overrides.get(normalized) or mimetypes.guess_extension(normalized) or ".bin"


def artifact_object_key(artifact_type: str, artifact_id: str, content_type: str, filename: str | None = None) -> str:
    kind = re.sub(r"[^a-z0-9]+", "-", artifact_type.lower()).strip("-") or "artifact"
    return f"artifacts/{kind}/{artifact_id}{extension_for(content_type, filename)}"


def safe_upload_key(upload_id: str, filename: str) -> str:
    basename = PurePath(filename).name
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", basename).strip(".-") or "upload.bin"
    return f"uploads/{upload_id}/{safe_name[:180]}"


def storage_location(uri: str, metadata: dict[str, Any] | None = None) -> tuple[str, str]:
    storage = (metadata or {}).get("storage") or {}
    bucket = storage.get("bucket")
    key = storage.get("key")
    if bucket and key:
        return str(bucket), str(key)
    parsed = urlparse(uri)
    if parsed.scheme in {"s3", "memory"} and parsed.netloc and parsed.path.lstrip("/"):
        return parsed.netloc, parsed.path.lstrip("/")
    raise StorageError("artifact is not backed by the configured object storage")


def artifact_content_url(artifact_id: str) -> str:
    api_base = os.getenv("API_PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")
    return f"{api_base}/artifacts/{artifact_id}/content"


@lru_cache(maxsize=1)
def get_storage() -> ObjectStorage:
    settings = StorageSettings.from_env()
    if settings.provider == "memory":
        return MemoryObjectStorage(settings)
    return S3CompatibleObjectStorage(settings)


def reset_storage_cache() -> None:
    get_storage.cache_clear()
