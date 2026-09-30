from __future__ import annotations

from dataclasses import dataclass
import mimetypes
import re
from urllib.parse import unquote, urljoin, urlparse

import httpx

from .contexts.artifacts.domain import (
    ArtifactPayloadTooLargeError,
    ArtifactUnsupportedMediaError,
    ArtifactValidationError,
)
from .video_downloaders import VideoDownloaderError, validate_public_url


@dataclass(frozen=True)
class DownloadedImage:
    content: bytes
    content_type: str
    filename: str
    source_url: str


def download_image_url(
    url: str, *, max_bytes: int, client: httpx.Client | None = None,
) -> DownloadedImage | None:
    """Probe direct media without reading video/page bodies; None uses the video adapter."""
    if client is None:
        with httpx.Client(timeout=httpx.Timeout(30, connect=10), follow_redirects=False) as session:
            return download_image_url(url, max_bytes=max_bytes, client=session)

    current_url = url
    expects_image = False
    for _ in range(6):
        try:
            validate_public_url(current_url)
        except (VideoDownloaderError, ValueError) as exc:
            raise ArtifactValidationError(str(exc)) from exc
        path_type = mimetypes.guess_type(unquote(urlparse(current_url).path))[0] or ""
        expects_image = expects_image or path_type.startswith("image/")
        try:
            with client.stream("GET", current_url, follow_redirects=False) as response:
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        raise ArtifactValidationError("image URL redirect is missing its destination")
                    current_url = urljoin(current_url, location)
                    continue
                content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                expects_image = expects_image or content_type.startswith("image/")
                response.raise_for_status()
                if content_type in {"", "application/octet-stream"} and path_type.startswith("image/"):
                    content_type = path_type
                if not content_type.startswith("image/"):
                    if expects_image:
                        raise ArtifactUnsupportedMediaError("the URL did not return an image file")
                    return None
                length = response.headers.get("content-length", "")
                if length.isdigit() and int(length) > max_bytes:
                    raise ArtifactPayloadTooLargeError("downloaded image exceeds the 250 MB Canvas limit")
                content = bytearray()
                for chunk in response.iter_bytes(chunk_size=64 * 1024):
                    if len(content) + len(chunk) > max_bytes:
                        raise ArtifactPayloadTooLargeError("downloaded image exceeds the 250 MB Canvas limit")
                    content.extend(chunk)
                if not content:
                    raise ArtifactValidationError("downloaded image is empty")
                filename = unquote(urlparse(current_url).path.rsplit("/", 1)[-1])
                filename = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "-", filename).strip(" .")[:180] or "image"
                if not (mimetypes.guess_type(filename)[0] or "").startswith("image/"):
                    filename += mimetypes.guess_extension(content_type) or ".image"
                return DownloadedImage(bytes(content), content_type, filename, current_url)
        except httpx.HTTPError as exc:
            if not expects_image:
                # Video sites may reject plain HTTP clients but accept their dedicated adapter.
                return None
            if isinstance(exc, httpx.HTTPStatusError):
                message = f"image download failed (HTTP {exc.response.status_code})"
            elif isinstance(exc, httpx.TimeoutException):
                message = "image download timed out; try again"
            else:
                message = "image download failed; check the URL and try again"
            raise ArtifactValidationError(message) from exc
    raise ArtifactValidationError("image URL has too many redirects")
