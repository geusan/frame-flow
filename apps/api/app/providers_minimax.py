from __future__ import annotations

import base64
import json
import os
import re
import time
from urllib.parse import urljoin

import httpx
from .billing import submit_with_cost, record_provider_result

from .providers_performance import MediaProviderError, ProviderMedia
from .video_downloaders import VideoDownloaderError, validate_public_url


MINIMAX_H3_MODEL = "MiniMax-H3"
MAX_REQUEST_BYTES = 64 * 1024 * 1024


def reference_request(*, prompt, resolution, duration, ratio, media):
    """MiniMax V2 reference capability; media order is significant within each modality."""
    if not prompt.strip() or len(prompt) > 7000:
        raise MediaProviderError("MiniMax reference prompt must contain 1–7000 characters")
    if resolution not in {"768P", "2K"} or type(duration) is not int or not 4 <= duration <= 15:
        raise MediaProviderError("MiniMax H3 requires 768P/2K and an integer duration of 4–15 seconds")
    content = [{"type": "text", "text": prompt}]
    counts = {kind: 0 for kind in ("image", "video", "audio")}
    for kind, mime, data in media:
        if kind not in counts:
            raise MediaProviderError("Unsupported MiniMax reference modality")
        counts[kind] += 1
        key = kind + "_url"
        content.append({"type": key, key: {"url": f"data:{mime};base64," + base64.b64encode(data).decode()}, "role": "reference_" + kind})
    if not 1 <= counts["image"] <= 9 or counts["video"] > 3 or counts["audio"] > 3 or sum(counts.values()) > 12:
        raise MediaProviderError("Reference limits: 1–9 images, up to 3 videos and 3 audios, at most 12 files total")
    payload = {"model": MINIMAX_H3_MODEL, "content": content, "resolution": resolution, "duration": duration, "ratio": ratio}
    if len(json.dumps(payload).encode()) > MAX_REQUEST_BYTES:
        raise MediaProviderError("MiniMax request exceeds 64 MB; use smaller reference artifacts")
    return payload


class MiniMaxVideoService:
    def __init__(self, *, api_key=None, base_url=None, client=None, poll_interval=5):
        self.key = api_key if api_key is not None else os.getenv("MINIMAX_API_KEY", "")
        if not self.key:
            raise MediaProviderError("MINIMAX_API_KEY is required")
        self.base = (base_url or os.getenv("MINIMAX_API_HOST") or "https://api.minimax.io").rstrip("/")
        parsed = httpx.URL(self.base)
        if parsed.scheme != "https" or parsed.userinfo or parsed.path not in {"", "/"}:
            raise MediaProviderError("MiniMax API host must be an HTTPS origin without embedded credentials")
        self.client = client or httpx.Client(timeout=httpx.Timeout(180, connect=30), follow_redirects=False)
        self.poll_interval = poll_interval

    def close(self):
        self.client.close()

    def _download(self, url):
        for _ in range(5):
            if httpx.URL(url).scheme != "https":
                raise MediaProviderError("MiniMax returned a non-HTTPS video URL")
            try:
                validate_public_url(url)
            except (VideoDownloaderError, ValueError) as exc:
                raise MediaProviderError("MiniMax returned an invalid public video URL") from exc
            # Credentials are only sent to the API, never to the result CDN.
            with self.client.stream("GET", url, follow_redirects=False) as response:
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        raise MediaProviderError("MiniMax video redirect has no destination")
                    url = urljoin(url, location)
                    continue
                response.raise_for_status()
                data = bytearray()
                for chunk in response.iter_bytes(1024 * 1024):
                    data.extend(chunk)
                    if len(data) > 512 * 1024 * 1024:
                        raise MediaProviderError("MiniMax output exceeds 512 MB")
                if not data:
                    raise MediaProviderError("MiniMax returned an empty video")
                return bytes(data)
        raise MediaProviderError("MiniMax video has too many redirects")

    def generate(self, payload, *, timeout_seconds, resume_id, remember, progress):
        headers = {"Authorization": "Bearer " + self.key}
        ident = resume_id
        if not ident:
            try:
                progress(15, "Submitting multimodal references to MiniMax H3")
                response = submit_with_cost("minimax", "video_generation", MINIMAX_H3_MODEL, self.client.post, self.base + "/v2/video_generation", request_id_field="task_id", headers=headers, json=payload)
                response.raise_for_status()
                ident = str(response.json().get("task_id") or "")
                if not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", ident):
                    raise MediaProviderError("MiniMax returned no valid task ID; inspect provider history before retrying")
                remember(ident)
            except httpx.HTTPError as exc:
                code = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else "network"
                rejected = code in {400, 401, 402, 403, 404, 422, 429}
                if rejected:
                    remember("rejected")
                raise MediaProviderError(f"MiniMax submission failed ({code}); automatic resubmission is disabled", rejected=rejected) from exc
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", ident):
            raise MediaProviderError("Invalid saved MiniMax task ID")
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            try:
                response = self.client.get(self.base + "/v2/query/video_generation/" + ident, headers=headers)
                response.raise_for_status()
                task = response.json().get("task") or {}
                status = task.get("status")
                if status == "succeeded":
                    record_provider_result("minimax", str(task.get("model") or "unspecified"), ident,
                        {"provider_usage": task.get("usage") or {}, "duration": task.get("duration"),
                         "resolution": task.get("resolution"), "task_type": task.get("task_type")},
                        context={"api_origin": self.base})
                    if task.get("model") != MINIMAX_H3_MODEL:
                        raise MediaProviderError("MiniMax result model does not match MiniMax-H3")
                    progress(85, "Downloading the MiniMax H3 result")
                    content = self._download(str((task.get("content") or {}).get("url") or ""))
                    return ProviderMedia(content, "video/mp4", ident, {"cost_status": "provider_billed_unreported", "provider_usage": task.get("usage") or {}, "model": task.get("model"), "resolution": task.get("resolution"), "duration": task.get("duration"), "ratio": task.get("ratio")})
                if status in {"failed", "cancelled"}:
                    raise MediaProviderError(f"MiniMax task {status}: {ident}; check the provider task details")
                if status not in {"queued", "running"}:
                    raise MediaProviderError("MiniMax returned an unknown task status")
                progress(25 if status == "queued" else 55, "MiniMax H3 queued" if status == "queued" else "MiniMax H3 generating reference video")
                time.sleep(self.poll_interval)
            except httpx.HTTPError as exc:
                retryable = not isinstance(exc, httpx.HTTPStatusError) or exc.response.status_code in {408, 429} or exc.response.status_code >= 500
                raise MediaProviderError(f"MiniMax query/download interrupted; resume task {ident}", retryable=retryable) from exc
        raise MediaProviderError(f"MiniMax task pending; resume task {ident}", retryable=True)
