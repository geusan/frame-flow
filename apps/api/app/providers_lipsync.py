from __future__ import annotations

import time

import httpx
from decimal import Decimal
from .billing import submit_with_cost, record_provider_result

from .providers_performance import FalPerformanceService, MediaProviderError, ProviderMedia

FAL_LIPSYNC_MODEL = "fal-ai/sync-lipsync/v2/pro"


class FalLipSyncService(FalPerformanceService):
    def synchronize(self, *, video: bytes, audio: bytes, audio_content_type: str,
                    timeout_seconds: int, resume_id: str | None, remember, progress) -> ProviderMedia:
        headers = {"Authorization": f"Key {self.key}"}
        request_id = resume_id
        if not request_id:
            try:
                progress(10, "Uploading the matched video and speech segment")
                video_url = self._upload(video, "video/mp4", "speech-segment.mp4")
                audio_url = self._upload(audio, audio_content_type, "speech.wav")
            except (httpx.HTTPError, MediaProviderError) as exc:
                remember("rejected")
                raise MediaProviderError("Lip-sync upload failed before submission", retryable=True, rejected=True) from exc
            try:
                response = submit_with_cost("fal", "lip_sync", FAL_LIPSYNC_MODEL, self.client.post, "https://queue.fal.run/" + FAL_LIPSYNC_MODEL,
                    headers=headers, json={"video_url": video_url, "audio_url": audio_url, "sync_mode": "cut_off"})
                response.raise_for_status()
                request_id = str(response.json().get("request_id") or "")
                if not request_id:
                    raise MediaProviderError("Lip-sync submission returned no request ID; inspect provider history")
                remember(request_id)
            except httpx.HTTPError as exc:
                status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else "network"
                if status in {400, 401, 402, 403, 404, 422}:
                    remember("rejected")
                raise MediaProviderError(f"Lip-sync submission failed ({status}); automatic resubmission is disabled") from exc
        request_url = "https://queue.fal.run/fal-ai/sync-lipsync/requests/" + request_id
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            try:
                response = self.client.get(request_url + "/status", headers=headers)
                response.raise_for_status()
                status = response.json().get("status")
            except httpx.HTTPError as exc:
                raise MediaProviderError(f"Lip-sync polling interrupted; retry resumes {request_id}", retryable=True) from exc
            if status == "COMPLETED":
                break
            if status in {"FAILED", "CANCELED", "CANCELLED"}:
                raise MediaProviderError(f"Lip-sync task {status}: {request_id}")
            progress(25 if status == "IN_QUEUE" else 55, "Synchronizing mouth movements to the supplied speech")
            time.sleep(self.poll_interval)
        else:
            raise MediaProviderError(f"Lip-sync task is pending; retry resumes {request_id}", retryable=True)
        try:
            response = self.client.get(request_url, headers=headers)
            if response.status_code == 422:
                remember("rejected")
                raise MediaProviderError(f"Lip-sync input was rejected for request {request_id}; inspect provider details", rejected=True)
            response.raise_for_status()
            payload = response.json()
            url = str((payload.get("video") or {}).get("url") or "")
            parsed = httpx.URL(url)
            if parsed.scheme != "https" or not (parsed.host == "fal.media" or parsed.host.endswith(".fal.media") or parsed.host == "storage.googleapis.com"):
                raise MediaProviderError("Lip-sync provider returned an unsupported media URL")
            usage = {"billable_units": response.headers.get("x-fal-billable-units"), "cost_status": "provider_billed_unreported"}
            # Pricing lookup failure must not discard a completed paid result.
            try:
                pricing = self.client.get("https://api.fal.ai/v1/models/pricing", headers=headers, params={"endpoint_id": FAL_LIPSYNC_MODEL})
                pricing.raise_for_status()
                price = next(p for p in pricing.json()["prices"] if p["endpoint_id"] == FAL_LIPSYNC_MODEL)
                quantity = float(usage["billable_units"])
                if price["currency"] == "USD" and quantity >= 0:
                    usage.update(unit=price["unit"], unit_price=price["unit_price"], currency="USD",
                                 calculated_cost_usd=quantity * float(price["unit_price"]), cost_status="provider_usage_calculated")
            except (httpx.HTTPError, ValueError, TypeError, KeyError, StopIteration):
                pass
            amount = Decimal(str(usage["billable_units"])) * Decimal(str(usage["unit_price"])) if usage.get("cost_status") == "provider_usage_calculated" else None
            pricing = {"source": "https://api.fal.ai/v1/models/pricing", "basis": "provider_usage_and_price", "unit": usage.get("unit"), "unit_price_usd": str(usage.get("unit_price")), "currency": "USD"} if amount is not None else None
            record_provider_result("fal", FAL_LIPSYNC_MODEL, request_id, usage, amount=amount, pricing=pricing, status="calculated")
            progress(80, "Downloading the lip-synced segment")
            content = bytearray()
            with self.client.stream("GET", url) as result:
                result.raise_for_status()
                for chunk in result.iter_bytes(1024 * 1024):
                    content.extend(chunk)
                    if len(content) > 512 * 1024 * 1024:
                        raise MediaProviderError("Lip-sync output exceeds 512 MB")
            if not content:
                raise MediaProviderError("Lip-sync provider returned empty video")
            return ProviderMedia(bytes(content), "video/mp4", request_id, usage)
        except httpx.HTTPError as exc:
            raise MediaProviderError(f"Lip-sync result retrieval interrupted; retry resumes {request_id}", retryable=True) from exc
