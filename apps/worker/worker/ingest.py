from __future__ import annotations

import ipaddress
import json
import socket
import subprocess
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse


class IngestError(RuntimeError):
    pass


@dataclass(frozen=True)
class ReferenceMetadata:
    canonical_url: str
    source_id: str
    title: str
    creator: str
    duration_ms: int
    width: int | None
    height: int | None
    has_subtitles: bool
    thumbnail_url: str | None
    estimated_bytes: int | None


@dataclass(frozen=True)
class DownloadPolicy:
    allow_media_download: bool
    max_duration_seconds: int = 600
    timeout_seconds: int = 900
    format_selector: str = "bv*[height<=1080]+ba/b[height<=1080]"


@dataclass(frozen=True)
class DownloadResult:
    job_id: str
    files: list[Path]
    info_json: dict


class ReferenceIngestProvider(Protocol):
    def inspect(self, url: str) -> ReferenceMetadata: ...
    def download(self, url: str, policy: DownloadPolicy, output_dir: Path) -> DownloadResult: ...
    def cancel(self, job_id: str) -> None: ...


def validate_public_http_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise IngestError("only absolute HTTP(S) URLs are accepted")
    if parsed.username or parsed.password:
        raise IngestError("URLs containing credentials are not accepted")
    try:
        addresses = {result[4][0] for result in socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)}
    except socket.gaierror as exc:
        raise IngestError("source hostname could not be resolved") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise IngestError("private, loopback, link-local, and reserved destinations are blocked")
    return url


class YtDlpIngestProvider:
    """yt-dlp is isolated behind this adapter and never receives shell text."""

    def __init__(self, executable: str = "yt-dlp") -> None:
        self.executable = executable
        self._jobs: dict[str, subprocess.Popen[str]] = {}
        self._lock = threading.Lock()

    def _base_args(self) -> list[str]:
        return [
            self.executable,
            "--ignore-config",
            "--no-playlist",
            "--restrict-filenames",
            "--socket-timeout", "15",
            "--retries", "2",
            "--no-warnings",
        ]

    def inspect(self, url: str) -> ReferenceMetadata:
        safe_url = validate_public_http_url(url)
        args = [*self._base_args(), "--skip-download", "--dump-single-json", "--", safe_url]
        try:
            result = subprocess.run(args, check=True, capture_output=True, text=True, timeout=45)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
            stderr = getattr(exc, "stderr", "") or ""
            raise IngestError(f"metadata inspection failed: {stderr[-800:]}") from exc
        info = json.loads(result.stdout)
        subtitles = info.get("subtitles") or info.get("automatic_captions") or {}
        formats = info.get("formats") or []
        estimated = max((item.get("filesize") or item.get("filesize_approx") or 0 for item in formats), default=0) or None
        return ReferenceMetadata(
            canonical_url=info.get("webpage_url") or safe_url,
            source_id=str(info.get("id") or ""),
            title=str(info.get("title") or "Untitled reference")[:512],
            creator=str(info.get("channel") or info.get("uploader") or "Unknown")[:255],
            duration_ms=round(float(info.get("duration") or 0) * 1000),
            width=info.get("width"),
            height=info.get("height"),
            has_subtitles=bool(subtitles),
            thumbnail_url=info.get("thumbnail"),
            estimated_bytes=estimated,
        )

    def download(self, url: str, policy: DownloadPolicy, output_dir: Path) -> DownloadResult:
        if not policy.allow_media_download:
            raise IngestError("media download requires an explicit rights-approved policy")
        safe_url = validate_public_http_url(url)
        if output_dir.is_symlink():
            raise IngestError("symlink output directories are not accepted")
        target = output_dir.resolve()
        target.mkdir(parents=True, exist_ok=True)
        job_id = f"ingest_{uuid.uuid4().hex[:16]}"
        output_template = str(target / "%(id).80s.%(ext)s")
        args = [
            *self._base_args(),
            "--max-downloads", "1",
            "--match-filter", f"duration <= {policy.max_duration_seconds}",
            "--format", policy.format_selector,
            "--merge-output-format", "mp4",
            "--write-info-json",
            "--write-thumbnail",
            "--write-subs",
            "--write-auto-subs",
            "--sub-langs", "ko.*,en.*",
            "--output", output_template,
            "--print", "after_move:filepath",
            "--", safe_url,
        ]
        process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=target)
        with self._lock:
            self._jobs[job_id] = process
        try:
            stdout, stderr = process.communicate(timeout=policy.timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            process.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
            raise IngestError("reference download exceeded its time limit") from exc
        finally:
            with self._lock:
                self._jobs.pop(job_id, None)
        if process.returncode != 0:
            raise IngestError(f"reference download failed: {stderr[-1000:]}")
        produced = [path.resolve() for path in target.iterdir() if path.is_file()]
        if any(target not in path.parents for path in produced):
            raise IngestError("ingest attempted to write outside its job directory")
        info_files = [path for path in produced if path.name.endswith(".info.json")]
        info = json.loads(info_files[0].read_text()) if info_files else {}
        return DownloadResult(job_id=job_id, files=sorted(produced), info_json=info)

    def cancel(self, job_id: str) -> None:
        with self._lock:
            process = self._jobs.get(job_id)
        if process and process.poll() is None:
            process.terminate()
