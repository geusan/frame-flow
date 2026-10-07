"""Private disk object storage for local and single-installation deployments."""
from pathlib import Path, PurePosixPath
from uuid import uuid4
import hashlib
import os

from .storage import StoredObject, StorageError


class FileObjectStorage:
    def __init__(self, root, settings):
        self.root = Path(root).resolve()
        self.settings = settings
    def initialize(self):
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
    def path(self, bucket, key):
        if not bucket or "/" in bucket or bucket in {".", ".."} or "\\" in key or any(part in {".", ".."} for part in key.split("/")) or key.startswith("/"):
            raise StorageError("Invalid object location")
        target = (self.root / bucket / key).resolve()
        if self.root not in target.parents:
            raise StorageError("Object path escapes storage root")
        return target
    def put_bytes(self, *, bucket, key, data, content_type, metadata=None):
        target = self.path(bucket, key)
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = target.with_name(f".{uuid4().hex}.tmp")
        try:
            with temporary.open("xb") as stream:
                stream.write(data); stream.flush(); os.fsync(stream.fileno())
            temporary.chmod(0o600)
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
        checksum = hashlib.sha256(data).hexdigest()
        return StoredObject("filesystem", bucket, key, f"filesystem://{bucket}/{key}", len(data), checksum, content_type)
    def get_bytes(self, *, bucket, key):
        try:
            return self.path(bucket, key).read_bytes()
        except OSError:
            raise StorageError("Object not found") from None
    def create_download_url(self, *, bucket, key):
        raise StorageError("Private filesystem downloads require an authenticated API request")
    def create_upload_url(self, *, bucket, key, content_type):
        raise StorageError("Private filesystem uploads use the authenticated multipart API")
