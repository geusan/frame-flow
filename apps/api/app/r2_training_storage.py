from __future__ import annotations

import hashlib
import io
import os
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import boto3
from botocore.client import Config
from botocore.exceptions import BotoCoreError, ClientError


class R2TrainingStorageError(RuntimeError):
    pass


@dataclass(frozen=True)
class R2TrainingSettings:
    account_id: str
    bucket: str
    access_key_id: str
    secret_access_key: str
    endpoint_url: str
    key_prefix: str
    signed_url_ttl_seconds: int

    @classmethod
    def from_env(cls) -> "R2TrainingSettings":
        account_id = os.getenv("R2_ACCOUNT_ID", "").strip()
        bucket = os.getenv("R2_TRAINING_BUCKET", "").strip()
        access_key_id = os.getenv("R2_ACCESS_KEY_ID", "").strip()
        secret_access_key = os.getenv("R2_SECRET_ACCESS_KEY", "").strip()
        endpoint_url = os.getenv("R2_ENDPOINT_URL", "").strip()
        if not endpoint_url and account_id:
            endpoint_url = f"https://{account_id}.r2.cloudflarestorage.com"
        missing = [
            name for name, value in {
                "R2_ACCOUNT_ID": account_id,
                "R2_TRAINING_BUCKET": bucket,
                "R2_ACCESS_KEY_ID": access_key_id,
                "R2_SECRET_ACCESS_KEY": secret_access_key,
            }.items() if not value
        ]
        if missing:
            raise R2TrainingStorageError(
                "Cloudflare R2 training storage is not configured. "
                f"Configure Settings → Cloudflare R2 ({', '.join(missing)})."
            )
        prefix = os.getenv("R2_TRAINING_PREFIX", "lora-training").strip().strip("/") or "lora-training"
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,255}", prefix) or ".." in prefix:
            raise R2TrainingStorageError("R2_TRAINING_PREFIX contains an invalid object-key segment")
        ttl = int(os.getenv("R2_PRESIGNED_URL_TTL_SECONDS", "3600"))
        if not 60 <= ttl <= 604_800:
            raise R2TrainingStorageError("R2_PRESIGNED_URL_TTL_SECONDS must be between 60 and 604800")
        return cls(account_id, bucket, access_key_id, secret_access_key, endpoint_url, prefix, ttl)


@dataclass(frozen=True)
class R2TrainingDataset:
    bucket: str
    key: str
    uri: str
    sha256: str
    size_bytes: int
    download_url: str
    expires_at: str


def build_captioned_lora_archive(
    images: list[tuple[str, bytes, str]],
    *,
    trigger_word: str,
) -> bytes:
    if len(images) < 4:
        raise ValueError("At least 4 character images are required for LoRA training")
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as dataset:
        for index, (role, content, extension) in enumerate(images, start=1):
            safe_role = re.sub(r"[^A-Za-z0-9_-]+", "_", role).strip("_") or f"view_{index}"
            safe_extension = extension.lower().lstrip(".")
            if safe_extension not in {"png", "jpg", "jpeg", "webp"}:
                raise ValueError(f"Unsupported LoRA training image format: {extension}")
            stem = f"{index:02d}_{safe_role}"
            dataset.writestr(f"{stem}.{safe_extension}", content)
            dataset.writestr(f"{stem}.txt", f"{trigger_word}, same character identity, {safe_role.replace('_', ' ')}")
    return archive.getvalue()


class R2TrainingDatasetStore:
    def __init__(self, settings: R2TrainingSettings | None = None, *, client: Any | None = None) -> None:
        self.settings = settings or R2TrainingSettings.from_env()
        self.client = client or boto3.client(
            "s3",
            endpoint_url=self.settings.endpoint_url,
            aws_access_key_id=self.settings.access_key_id,
            aws_secret_access_key=self.settings.secret_access_key,
            region_name="auto",
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

    def put_archive(self, *, character_id: str, archive: bytes) -> R2TrainingDataset:
        digest = hashlib.sha256(archive).hexdigest()
        safe_character_id = re.sub(r"[^A-Za-z0-9_-]+", "-", character_id).strip("-") or "character"
        key = f"{self.settings.key_prefix}/{safe_character_id}/{digest}.zip"
        try:
            self.client.put_object(
                Bucket=self.settings.bucket,
                Key=key,
                Body=archive,
                ContentLength=len(archive),
                ContentType="application/zip",
                Metadata={"sha256": digest, "character-id": safe_character_id},
            )
            download_url = self.client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.settings.bucket, "Key": key},
                ExpiresIn=self.settings.signed_url_ttl_seconds,
            )
        except (BotoCoreError, ClientError) as exc:
            raise R2TrainingStorageError(f"Failed to upload LoRA training dataset to R2: {exc}") from exc
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=self.settings.signed_url_ttl_seconds)
        return R2TrainingDataset(
            bucket=self.settings.bucket,
            key=key,
            uri=f"r2://{self.settings.bucket}/{key}",
            sha256=digest,
            size_bytes=len(archive),
            download_url=download_url,
            expires_at=expires_at.isoformat(),
        )


def get_r2_training_dataset_store() -> R2TrainingDatasetStore:
    return R2TrainingDatasetStore()
