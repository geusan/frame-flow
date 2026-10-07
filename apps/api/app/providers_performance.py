from __future__ import annotations

from .provider_credentials import provider_value

import hashlib
import json
import os
import time
from dataclasses import dataclass
from typing import Callable

import httpx
from .billing import ProviderCall, submit_with_cost, record_fal_result

FAL_PERFORMANCE_MODEL = "fal-ai/kling-video/v3/pro/motion-control"
ELEVENLABS_VOICE_MODEL = "eleven_multilingual_sts_v2"


class MediaProviderError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool = False, rejected: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.rejected = rejected


@dataclass(frozen=True)
class ProviderMedia:
    content: bytes
    content_type: str
    request_id: str
    usage: dict


class FalPerformanceService:
    def __init__(self, *, api_key: str | None = None, client: httpx.Client | None = None, poll_interval: float = 3) -> None:
        self.key = api_key if api_key is not None else provider_value("FAL_KEY", "")
        if not self.key:
            raise MediaProviderError("FAL_KEY is required for performance transfer")
        self.client = client or httpx.Client(timeout=httpx.Timeout(120, connect=30))
        self.poll_interval = poll_interval

    def close(self) -> None:
        self.client.close()

    def _upload(self, content: bytes, content_type: str, filename: str) -> str:
        response = self.client.post("https://rest.alpha.fal.ai/storage/upload/initiate",
            params={"storage_type": "fal-cdn-v3"},
            headers={"Authorization": f"Key {self.key}", "X-Fal-Object-Lifecycle": json.dumps({"expiration_duration_seconds": 86400})},
            json={"content_type": content_type, "file_name": filename})
        response.raise_for_status()
        payload = response.json()
        upload_url, file_url = str(payload["upload_url"]), str(payload["file_url"])
        for url in (upload_url, file_url):
            parsed = httpx.URL(url)
            if parsed.scheme != "https" or not (parsed.host == "fal.media" or parsed.host.endswith(".fal.media") or parsed.host.endswith(".fal.ai")):
                raise MediaProviderError("fal returned an unsupported upload URL")
        uploaded = self.client.put(upload_url, content=content, headers={"Content-Type": content_type})
        uploaded.raise_for_status()
        return file_url

    def transfer(self, *, image: bytes, image_content_type: str, video: bytes, prompt: str,
                 orientation: str, timeout_seconds: int, resume_id: str | None,
                 remember: Callable[[str], None], progress: Callable[[int, str], None]) -> ProviderMedia:
        headers = {"Authorization": f"Key {self.key}"}
        request_id = resume_id
        if not request_id:
            try:
                progress(10, "Uploading the character and driving video")
                image_url = self._upload(image, image_content_type, "character." + image_content_type.split("/")[-1])
                video_url = self._upload(video, "video/mp4", "driving.mp4")
            except (httpx.HTTPError, MediaProviderError) as exc:
                # No inference was submitted; an upload failure is safe to retry.
                remember("rejected")
                raise MediaProviderError("fal media upload failed before generation was submitted", retryable=True, rejected=True) from exc
            try:
                response = submit_with_cost("fal", "performance", FAL_PERFORMANCE_MODEL, self.client.post, f"https://queue.fal.run/{FAL_PERFORMANCE_MODEL}", headers=headers, json={
                    "image_url": image_url, "video_url": video_url,
                    "prompt": prompt, "character_orientation": orientation, "keep_original_sound": False,
                })
                response.raise_for_status()
                request_id = str(response.json().get("request_id") or "")
                if not request_id:
                    raise MediaProviderError("fal returned no request ID; inspect the pending submission before retrying")
                remember(request_id)
            except httpx.HTTPError as exc:
                code = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else "network"
                if code in {400, 401, 402, 403, 404, 422}:
                    remember("rejected")
                if code == 403 and "exhausted balance" in exc.response.text.lower():
                    raise MediaProviderError("fal balance is exhausted. Top up at https://fal.ai/dashboard/billing, then rerun this node.", rejected=True) from exc
                raise MediaProviderError(f"fal submission failed ({code}); automatic resubmission is disabled") from exc
        # Queue status/result endpoints use the provider's root model namespace.
        request_url = f"https://queue.fal.run/fal-ai/kling-video/requests/{request_id}"
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            try:
                response = self.client.get(request_url + "/status", headers=headers)
                response.raise_for_status()
                status = str(response.json().get("status") or "")
                if status == "COMPLETED":
                    break
                if status in {"FAILED", "CANCELED", "CANCELLED"}:
                    raise MediaProviderError(f"fal performance task {status.lower()}: {request_id}")
                progress(25 if status == "IN_QUEUE" else 55, "Waiting for motion/face transfer" if status == "IN_QUEUE" else "Transferring the reference performance")
                time.sleep(self.poll_interval)
            except httpx.HTTPError as exc:
                raise MediaProviderError(f"fal task polling interrupted; retry resumes request {request_id}", retryable=True) from exc
        else:
            raise MediaProviderError(f"fal task is still pending; retry resumes request {request_id}", retryable=True)
        try:
            response = self.client.get(request_url, headers=headers)
            if response.status_code == 422:
                details = response.json().get("detail", [])
                # Do not include the provider's echoed input media in errors/logs.
                messages = [str(item.get("msg", "Invalid input"))[:200] for item in details if isinstance(item, dict)] if isinstance(details, list) else [str(details)[:200]]
                remember("rejected")
                raise MediaProviderError("fal rejected generation input: " + "; ".join(messages), rejected=True)
            response.raise_for_status()
            payload = response.json()
            record_fal_result(response, FAL_PERFORMANCE_MODEL, request_id, self.client, headers)
            payload = payload.get("data", payload)
            url = str((payload.get("video") or {}).get("url") or "")
            parsed = httpx.URL(url)
            if parsed.scheme != "https" or not (parsed.host == "fal.media" or parsed.host.endswith(".fal.media")):
                raise MediaProviderError("fal returned an unsupported result URL")
            progress(80, "Downloading the transferred video")
            content = bytearray()
            with self.client.stream("GET", url) as media:
                media.raise_for_status()
                for chunk in media.iter_bytes(1024 * 1024):
                    content.extend(chunk)
                    if len(content) > 512 * 1024 * 1024:
                        raise MediaProviderError("Performance result exceeds 512 MB")
            if not content:
                raise MediaProviderError("fal returned an empty video")
            return ProviderMedia(bytes(content), "video/mp4", request_id, {"cost_status": "provider_billed_unreported", "metrics": payload.get("metrics", {})})
        except httpx.HTTPError as exc:
            raise MediaProviderError(f"fal result download interrupted; retry resumes request {request_id}", retryable=True) from exc


class ElevenLabsVoiceService:
    def __init__(self, *, api_key: str | None = None, client: httpx.Client | None = None) -> None:
        self.key = api_key if api_key is not None else provider_value("ELEVENLABS_API_KEY", "")
        if not self.key:
            raise MediaProviderError("ELEVENLABS_API_KEY is required for voice conversion")
        self.base = provider_value("ELEVENLABS_BASE_URL", "https://api.elevenlabs.io").rstrip("/")
        self.client = client or httpx.Client(timeout=httpx.Timeout(300, connect=30))

    def close(self) -> None:
        self.client.close()

    def validate_voice(self, voice_id: str) -> None:
        response = self.client.get(f"{self.base}/v1/voices/{voice_id}", headers={"xi-api-key": self.key})
        if response.status_code != 200:
            raise MediaProviderError(f"ElevenLabs voice {voice_id} is not available to this API account (HTTP {response.status_code})")

    def convert(self, *, audio: bytes, voice_id: str, stability: float, similarity: float,
                seed: int, remove_noise: bool) -> ProviderMedia:
        charge = ProviderCall("elevenlabs", "speech_to_speech", ELEVENLABS_VOICE_MODEL)
        try:
            response = self.client.post(f"{self.base}/v1/speech-to-speech/{voice_id}",
                headers={"xi-api-key": self.key}, params={"output_format": "mp3_44100_128"},
                files={"audio": ("source.wav", audio, "audio/wav")}, data={
                    "model_id": ELEVENLABS_VOICE_MODEL,
                    "voice_settings": json.dumps({"stability": stability, "similarity_boost": similarity, "style": 0, "use_speaker_boost": True}),
                    "seed": str(seed), "remove_background_noise": str(remove_noise).lower(),
                })
            response.raise_for_status()
        except httpx.HTTPError as exc:
            charge.failed(exc)
            code = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else "network"
            raise MediaProviderError(f"ElevenLabs voice conversion failed ({code}); inspect provider history before retrying", rejected=code in {400, 401, 402, 403, 404, 422}) from exc
        charge.submitted(response.headers.get("request-id") or response.headers.get("x-request-id"))
        charge.complete(usage={"character_cost": response.headers.get("character-cost"), "history_item_id": response.headers.get("history-item-id")})
        if not response.content:
            raise MediaProviderError("ElevenLabs returned empty audio")
        request_id = response.headers.get("request-id") or response.headers.get("x-request-id") or "response_" + hashlib.sha256(response.content).hexdigest()[:24]
        return ProviderMedia(bytes(response.content), "audio/mpeg", request_id, {
            "cost_status": "provider_billed_unreported", "character_cost": response.headers.get("character-cost"),
            "history_item_id": response.headers.get("history-item-id"),
        })
