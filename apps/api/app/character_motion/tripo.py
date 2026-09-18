from __future__ import annotations

from dataclasses import dataclass
import os
import re
import time
from typing import Any, Callable
from urllib.parse import urljoin, urlparse

import httpx


TRIPO_API_REVISION = "tripo-api-v3.2026-09"
TRIPO_DEFAULT_BASE_URL = "https://openapi.tripo3d.ai/v3"
TRIPO_IMAGE_MAX_BYTES = 20 * 1024 * 1024
TRIPO_MODEL_MAX_BYTES = 150 * 1024 * 1024
# Tripo v3 currently returns opaque IDs. Production responses include both the
# documented task_* form and UUIDs; only URL path-safe characters are accepted.
TRIPO_TASK_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{2,254}$")
TRIPO_VIEW_ORDER = ("front", "left", "back", "right")
TRIPO_DOWNLOAD_DOMAIN_SUFFIXES = (".tripo3d.ai", ".tripo3d.com")


class TripoProviderError(RuntimeError):
    """An actionable Tripo API failure with retry classification."""

    def __init__(self, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.retryable = retryable


@dataclass(frozen=True)
class TripoUpload:
    role: str
    data: bytes
    content_type: str
    filename: str


@dataclass(frozen=True)
class TripoTaskResult:
    task_id: str
    task_type: str
    output: dict[str, Any]
    credits_consumed: float
    raw: dict[str, Any]


@dataclass(frozen=True)
class TripoBinaryResult:
    data: bytes
    task: TripoTaskResult
    metadata: dict[str, Any]


@dataclass(frozen=True)
class TripoMultiviewResult:
    views: tuple[TripoUpload, ...]
    task: TripoTaskResult


class TripoClient:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        poll_interval_seconds: float | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.api_key = (api_key if api_key is not None else os.getenv("TRIPO_API_KEY", "")).strip()
        if not self.api_key:
            raise TripoProviderError(
                "Tripo API key is not configured. Enable Tripo in Settings or set TRIPO_API_KEY on the worker.",
                retryable=False,
            )
        self.base_url = (base_url or os.getenv("TRIPO_BASE_URL", TRIPO_DEFAULT_BASE_URL)).rstrip("/")
        parsed_base = urlparse(self.base_url)
        if parsed_base.scheme != "https" and os.getenv("APP_ENV") != "test":
            raise TripoProviderError("TRIPO_BASE_URL must use HTTPS", retryable=False)
        if not parsed_base.hostname:
            raise TripoProviderError("TRIPO_BASE_URL is invalid", retryable=False)
        self.base_hostname = parsed_base.hostname.lower()
        configured_hosts = {
            value.strip().lower()
            for value in os.getenv("TRIPO_ALLOWED_DOWNLOAD_HOSTS", "").split(",")
            if value.strip()
        }
        self.allowed_download_hosts = {self.base_hostname, *configured_hosts}
        self.auth_headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
            self.poll_interval_seconds = (
                float(poll_interval_seconds)
                if poll_interval_seconds is not None
                else float(os.getenv("TRIPO_POLL_INTERVAL_SECONDS", "2"))
            )
        except ValueError as exc:
            raise TripoProviderError("TRIPO_POLL_INTERVAL_SECONDS must be numeric", retryable=False) from exc
        if not 0.1 <= self.poll_interval_seconds <= 30:
            raise TripoProviderError(
                "TRIPO_POLL_INTERVAL_SECONDS must be between 0.1 and 30", retryable=False,
            )
        self._owns_http = http_client is None
        self.http = http_client or httpx.Client(timeout=httpx.Timeout(90, connect=15))

    def close(self) -> None:
        if self._owns_http:
            self.http.close()

    @staticmethod
    def _error_for_status(response: httpx.Response, action: str) -> TripoProviderError:
        status = response.status_code
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        code = payload.get("code")
        suggestion = str(payload.get("suggestion") or "").strip()
        request_id = str(payload.get("request_id") or "").strip()
        detail = str(
            data.get("error_message")
            or payload.get("message")
            or payload.get("error")
            or response.text
            or f"HTTP {status}"
        )[-1200:]
        diagnostic = "".join([
            f" [code {code}]" if code is not None else "",
            f" [request {request_id}]" if request_id else "",
        ])
        if status == 401:
            return TripoProviderError(
                "Tripo authentication failed. Create or copy a key from Tripo Console → API Keys, "
                "paste only the API key (currently documented as tsk_…), without 'Bearer', and save Settings → Tripo."
                + diagnostic,
                retryable=False,
            )
        if status == 403 and (code == 2010 or "credit" in detail.lower()):
            return TripoProviderError(
                f"Tripo credits are insufficient while {action}: {detail}. "
                f"{suggestion or 'Top up the Tripo API account before retrying.'}{diagnostic}",
                retryable=False,
            )
        if status == 403:
            return TripoProviderError(
                f"Tripo permission denied while {action}: {detail}. "
                f"{suggestion or 'Check API key permissions and IP restrictions.'}{diagnostic}",
                retryable=False,
            )
        if status == 429:
            return TripoProviderError(f"Tripo rate limit exceeded while {action}: {detail}", retryable=True)
        return TripoProviderError(
            f"Tripo API failed while {action} (HTTP {status}): {detail}",
            retryable=status >= 500 or status in {408, 409, 425},
        )

    def _payload(self, response: httpx.Response, action: str) -> dict[str, Any]:
        if response.status_code >= 400:
            raise self._error_for_status(response, action)
        try:
            payload = response.json()
        except ValueError as exc:
            raise TripoProviderError(
                f"Tripo returned invalid JSON while {action}", retryable=True,
            ) from exc
        if not isinstance(payload, dict):
            raise TripoProviderError(f"Tripo returned an invalid result while {action}", retryable=True)
        if payload.get("code") not in {None, 0}:
            data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
            detail = str(data.get("error_message") or payload.get("message") or f"code {payload.get('code')}")
            raise TripoProviderError(f"Tripo rejected the request while {action}: {detail}", retryable=False)
        data = payload.get("data")
        if not isinstance(data, dict):
            raise TripoProviderError(f"Tripo response is missing data while {action}", retryable=True)
        return data

    def upload_file(self, upload: TripoUpload, *, model: bool = False) -> str:
        maximum = TRIPO_MODEL_MAX_BYTES if model else TRIPO_IMAGE_MAX_BYTES
        if not upload.data or len(upload.data) > maximum:
            label = "model" if model else "image"
            raise TripoProviderError(
                f"Tripo {label} upload must be between 1 byte and {maximum // (1024 * 1024)} MB",
                retryable=False,
            )
        content_type = upload.content_type.split(";", 1)[0].strip().lower()
        allowed = {"model/gltf-binary"} if model else {"image/png", "image/jpeg", "image/jpg"}
        if content_type not in allowed:
            formats = "GLB" if model else "PNG or JPEG"
            raise TripoProviderError(f"Tripo upload requires {formats}; received {content_type}", retryable=False)
        try:
            response = self.http.post(
                f"{self.base_url}/files",
                headers=self.auth_headers,
                files={"file": (upload.filename, upload.data, content_type)},
            )
        except httpx.HTTPError as exc:
            raise TripoProviderError(f"Tripo file upload is unavailable: {exc}", retryable=True) from exc
        data = self._payload(response, f"uploading {upload.role}")
        token = str(data.get("file_token") or "")
        if not token:
            raise TripoProviderError("Tripo file upload did not return a file_token", retryable=True)
        return token

    def account_balance(self) -> dict[str, float]:
        try:
            response = self.http.get(f"{self.base_url}/account/balance", headers=self.auth_headers)
        except httpx.HTTPError as exc:
            raise TripoProviderError(f"Tripo account validation is unavailable: {exc}", retryable=True) from exc
        data = self._payload(response, "validating account credentials")
        try:
            balance = float(data["balance"])
            frozen = float(data.get("frozen") or 0)
        except (KeyError, TypeError, ValueError) as exc:
            raise TripoProviderError("Tripo balance response is missing numeric credits", retryable=True) from exc
        return {"balance": balance, "frozen": frozen}

    def submit_task(self, path: str, payload: dict[str, Any], *, action: str) -> str:
        try:
            response = self.http.post(f"{self.base_url}{path}", headers=self.auth_headers, json=payload)
        except httpx.HTTPError as exc:
            raise TripoProviderError(f"Tripo is unavailable while {action}: {exc}", retryable=True) from exc
        data = self._payload(response, action)
        task_id = str(data.get("task_id") or "")
        if not TRIPO_TASK_ID_PATTERN.fullmatch(task_id):
            # The task may already have been created and billed. Never submit a
            # duplicate merely because a new provider ID format was received.
            raise TripoProviderError(f"Tripo did not return a safe task ID while {action}", retryable=False)
        return task_id

    def wait_task(
        self,
        task_id: str,
        *,
        action: str,
        timeout_seconds: int,
        progress: Callable[[int, str], None] | None = None,
    ) -> TripoTaskResult:
        if not TRIPO_TASK_ID_PATTERN.fullmatch(task_id):
            raise TripoProviderError(f"Invalid Tripo task ID for {action}", retryable=False)
        deadline = time.monotonic() + timeout_seconds
        while True:
            try:
                response = self.http.get(
                    f"{self.base_url}/tasks/{task_id}",
                    headers={**self.auth_headers, "Cache-Control": "no-cache"},
                )
            except httpx.HTTPError as exc:
                raise TripoProviderError(f"Tripo task status is unavailable: {exc}", retryable=True) from exc
            data = self._payload(response, f"polling {action}")
            status = str(data.get("status") or "").lower()
            provider_progress = max(0, min(100, int(data.get("progress") or 0)))
            if progress:
                progress(provider_progress, f"Tripo {action}: {status or 'unknown'} {provider_progress}%")
            if status == "success":
                output = data.get("output") if isinstance(data.get("output"), dict) else {}
                return TripoTaskResult(
                    task_id=task_id,
                    task_type=str(data.get("type") or action),
                    output=output,
                    credits_consumed=float(data.get("credits_consumed") or 0),
                    raw=data,
                )
            if status in {"failed", "cancelled"}:
                detail = str(data.get("error_message") or data.get("error_code") or "provider task failed")
                raise TripoProviderError(f"Tripo {action} task {status}: {detail}", retryable=False)
            if status not in {"queued", "running"}:
                raise TripoProviderError(f"Tripo {action} returned unknown task status: {status}", retryable=True)
            if time.monotonic() >= deadline:
                raise TripoProviderError(
                    f"Tripo {action} task exceeded its {timeout_seconds} second timeout: {task_id}",
                    retryable=True,
                )
            time.sleep(max(0.0, min(self.poll_interval_seconds, deadline - time.monotonic())))

    def _validate_download_url(self, url: str) -> None:
        parsed = urlparse(url)
        hostname = (parsed.hostname or "").lower()
        allowed = (
            hostname in self.allowed_download_hosts
            or hostname in {"tripo3d.ai", "tripo3d.com"}
            or hostname.endswith(TRIPO_DOWNLOAD_DOMAIN_SUFFIXES)
        )
        if parsed.scheme != "https" or not hostname or not allowed or parsed.username or parsed.password:
            raise TripoProviderError("Tripo returned an unsafe model download URL", retryable=False)

    def download_model(self, url: str) -> bytes:
        return self._download_file(url, maximum=TRIPO_MODEL_MAX_BYTES, label="model")

    def _download_file(self, url: str, *, maximum: int, label: str) -> bytes:
        current = url
        for _ in range(4):
            self._validate_download_url(current)
            try:
                response = self.http.get(current, follow_redirects=False)
            except httpx.HTTPError as exc:
                raise TripoProviderError(f"Tripo {label} download is unavailable: {exc}", retryable=True) from exc
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("location", "")
                if not location:
                    raise TripoProviderError(f"Tripo {label} download redirect is missing a location", retryable=True)
                current = urljoin(current, location)
                continue
            if response.status_code >= 400:
                raise self._error_for_status(response, f"downloading the generated {label}")
            content = response.content
            if not content or len(content) > maximum:
                raise TripoProviderError(f"Tripo returned an empty or oversized {label}", retryable=True)
            return content
        raise TripoProviderError(f"Tripo {label} download exceeded the redirect limit", retryable=True)

    def generate_multiview_images(
        self,
        source: TripoUpload,
        *,
        timeout_seconds: int,
        resume_task_id: str | None = None,
        on_task: Callable[[str, str], None] | None = None,
        progress: Callable[[int, str], None] | None = None,
    ) -> TripoMultiviewResult:
        """One source image -> a coherent four-view set; pose is source-controlled.

        This endpoint does not expose a model, seed, or pose selector. Do not
        send invented parameters or treat the service as a trainable model.
        """
        task_id = resume_task_id
        if not task_id:
            token = self.upload_file(source)
            if on_task:
                on_task("multiview", "pending")
            task_id = self.submit_task(
                "/generation/image-to-multiview", {"input": token},
                action="generating four-view images",
            )
            if on_task:
                on_task("multiview", task_id)
        task = self.wait_task(
            task_id, action="four-view image generation", timeout_seconds=timeout_seconds,
            progress=progress,
        )
        # Public v3 docs show flattened URLs; live tasks also return the
        # versioned output under generate_multiview_image.
        nested = task.output.get("generate_multiview_image")
        output = nested if isinstance(nested, dict) else task.output
        urls = [output.get(f"{role}_view_url") for role in TRIPO_VIEW_ORDER]
        if any(not isinstance(url, str) or not url for url in urls):
            raise TripoProviderError("Tripo multiview result must contain all four view URLs", retryable=False)
        if len(set(urls)) != 4:
            raise TripoProviderError("Tripo multiview result contains duplicate view URLs", retryable=False)
        views = []
        for role, url in zip(TRIPO_VIEW_ORDER, urls, strict=True):
            data = self._download_file(str(url), maximum=TRIPO_IMAGE_MAX_BYTES, label=f"{role} image")
            # The executor decodes and normalizes PNG/JPEG/WebP before storing
            # images for the existing PNG/JPEG-only 3D upload capability.
            views.append(TripoUpload(role, data, "application/octet-stream", f"{role}.png"))
        return TripoMultiviewResult(tuple(views), task)

    def generate_multiview(
        self,
        views: tuple[TripoUpload, ...],
        *,
        model: str,
        face_limit: int,
        texture: bool,
        pbr: bool,
        texture_quality: str,
        export_uv: bool,
        smart_low_poly: bool,
        seed: int,
        timeout_seconds: int,
        resume_task_id: str | None = None,
        on_task: Callable[[str, str], None] | None = None,
        progress: Callable[[int, str], None] | None = None,
    ) -> TripoBinaryResult:
        by_role = {view.role: view for view in views}
        if "front" not in by_role or len(by_role) < 2 or len(by_role) > 4:
            raise TripoProviderError("Tripo multiview generation requires front plus 1–3 distinct views", retryable=False)
        if any(role not in TRIPO_VIEW_ORDER for role in by_role):
            raise TripoProviderError("Tripo multiview roles must be front, left, back, or right", retryable=False)
        if not 48 <= face_limit <= 20_000:
            raise TripoProviderError("Tripo animation-ready face_limit must be between 48 and 20000", retryable=False)
        if resume_task_id:
            task_id = resume_task_id
        else:
            generation_credits = (
                40 if not texture else 60 if texture_quality == "detailed" else 50
            ) if model.startswith("P1-") else (
                20 if not texture else 40 if texture_quality == "detailed" else 30
            )
            account = self.account_balance()
            if account["balance"] < generation_credits:
                raise TripoProviderError(
                    f"Tripo balance is {account['balance']:g} credits, but this {model} multiview preset "
                    f"requires about {generation_credits} credits. Top up the Tripo API account before retrying.",
                    retryable=False,
                )
            if progress:
                progress(6, f"Tripo balance preflight passed · {account['balance']:g} credits")
            inputs: list[dict[str, str]] = []
            for index, role in enumerate(TRIPO_VIEW_ORDER):
                view = by_role.get(role)
                if not view:
                    continue
                if progress:
                    progress(8 + round(index / 4 * 20), f"Uploading {role} character view")
                inputs.append({role: self.upload_file(view)})
            payload: dict[str, Any] = {
                "inputs": inputs,
                "model": model,
                "face_limit": face_limit,
                "texture": texture,
                "pbr": pbr if texture else False,
                "export_uv": export_uv,
                "model_seed": seed,
            }
            if texture:
                payload["texture_quality"] = texture_quality
            if model.startswith("v3."):
                payload["smart_low_poly"] = smart_low_poly
            if on_task:
                on_task("generate", "pending")
            task_id = self.submit_task(
                "/generation/multiview-to-model", payload, action="submitting multiview generation",
            )
            if on_task:
                on_task("generate", task_id)
        task = self.wait_task(
            task_id,
            action="multiview generation",
            timeout_seconds=timeout_seconds,
            progress=(lambda value, message: progress(32 + round(value * 0.55), message)) if progress else None,
        )
        model_url = str(task.output.get("model_url") or "")
        if not model_url:
            raise TripoProviderError("Tripo generation completed without a model_url", retryable=True)
        if progress:
            progress(90, "Downloading generated GLB")
        return TripoBinaryResult(
            data=self.download_model(model_url),
            task=task,
            metadata={
                "model": model,
                "face_limit": face_limit,
                "view_roles": [role for role in TRIPO_VIEW_ORDER if role in by_role],
                "credits_consumed": task.credits_consumed,
                "rendered_preview_available": bool(task.output.get("rendered_image_url")),
            },
        )

    def auto_rig(
        self,
        glb: bytes,
        *,
        model: str,
        rig_type: str,
        spec: str,
        timeout_seconds: int,
        run_rig_check: bool,
        resume_stage: str | None = None,
        resume_task_id: str | None = None,
        on_task: Callable[[str, str], None] | None = None,
        progress: Callable[[int, str], None] | None = None,
    ) -> TripoBinaryResult:
        file_token: str | None = None
        rig_check: TripoTaskResult | None = None
        rig_task: TripoTaskResult
        if resume_stage == "rig" and resume_task_id:
            rig_task = self.wait_task(
                resume_task_id,
                action="auto rig",
                timeout_seconds=timeout_seconds,
                progress=(lambda value, message: progress(45 + round(value * 0.4), message)) if progress else None,
            )
        else:
            if progress:
                progress(10, "Uploading GLB for Tripo rigging")
            file_token = self.upload_file(
                TripoUpload("character", glb, "model/gltf-binary", "character.glb"), model=True,
            )
            if run_rig_check:
                if resume_stage == "rig_check" and resume_task_id:
                    check_task_id = resume_task_id
                else:
                    if on_task:
                        on_task("rig_check", "pending")
                    check_task_id = self.submit_task(
                        "/animations/rig-check", {"input": file_token}, action="submitting riggability check",
                    )
                if on_task and not (resume_stage == "rig_check" and resume_task_id):
                    on_task("rig_check", check_task_id)
                rig_check = self.wait_task(
                    check_task_id,
                    action="riggability check",
                    timeout_seconds=timeout_seconds,
                    progress=(lambda value, message: progress(20 + round(value * 0.2), message)) if progress else None,
                )
                if not bool(rig_check.output.get("riggable")):
                    recommended = str(rig_check.output.get("rig_type") or "unknown")
                    raise TripoProviderError(
                        f"Tripo reports that this GLB is not riggable as {rig_type}; recommended type: {recommended}",
                        retryable=False,
                    )
            if not file_token:
                file_token = self.upload_file(
                    TripoUpload("character", glb, "model/gltf-binary", "character.glb"), model=True,
                )
            if on_task:
                on_task("rig", "pending")
            rig_task_id = self.submit_task(
                "/animations/rig",
                {"input": file_token, "model": model, "rig_type": rig_type, "spec": spec, "out_format": "glb"},
                action="submitting auto rig",
            )
            if on_task:
                on_task("rig", rig_task_id)
            rig_task = self.wait_task(
                rig_task_id,
                action="auto rig",
                timeout_seconds=timeout_seconds,
                progress=(lambda value, message: progress(45 + round(value * 0.4), message)) if progress else None,
            )
        model_url = str(rig_task.output.get("model_url") or "")
        if not model_url:
            raise TripoProviderError("Tripo auto rig completed without a model_url", retryable=True)
        if progress:
            progress(90, "Downloading rigged GLB")
        return TripoBinaryResult(
            data=self.download_model(model_url),
            task=rig_task,
            metadata={
                "model": model,
                "rig_type": rig_type,
                "spec": spec,
                "credits_consumed": rig_task.credits_consumed,
                "rig_check_task_id": rig_check.task_id if rig_check else None,
                "rig_check": rig_check.output if rig_check else None,
            },
        )
