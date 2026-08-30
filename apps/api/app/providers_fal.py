from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any

import httpx

from .domain import ExperimentRunRequest
from .providers_generation import InputMedia, LiveGenerationResult


FAL_LIVE_REVISION = "fal-live.v1"
FAL_FLUX2_LORA_MODEL = "fal-ai/flux-2/lora"
FAL_FLUX2_TRAINER_MODEL = "fal-ai/flux-2-trainer-v2"


@dataclass(frozen=True)
class FalProviderConfig:
    api_key: str
    queue_base_url: str = "https://queue.fal.run"

    @classmethod
    def from_env(cls) -> "FalProviderConfig":
        api_key = os.getenv("FAL_KEY", "").strip()
        if not api_key:
            raise RuntimeError("FAL_KEY is required for fal LoRA generation")
        return cls(api_key=api_key, queue_base_url=os.getenv("FAL_QUEUE_BASE_URL", "https://queue.fal.run").rstrip("/"))


class FalGenerationServices:
    def __init__(self, config: FalProviderConfig | None = None, client: Any | None = None) -> None:
        self.config = config or FalProviderConfig.from_env()
        self.client = client or httpx.Client(timeout=httpx.Timeout(300.0, connect=30.0))

    def execute(self, payload: ExperimentRunRequest, inputs: list[InputMedia]) -> LiveGenerationResult:
        if payload.node_key != "lora.image.generate":
            raise ValueError(f"fal provider does not support Canvas node: {payload.node_key}")
        lora_path = str(payload.parameters.get("lora_url") or "").strip()
        if not lora_path:
            raise ValueError("LoRA weights URL or Hugging Face repository ID is required")
        scale = float(payload.parameters.get("lora_scale") or 0.9)
        if not 0 <= scale <= 2:
            raise ValueError("LoRA scale must be between 0 and 2")
        trigger_word = str(payload.parameters.get("trigger_word") or "").strip()
        rendered_prompt = f"{trigger_word}, {payload.prompt.strip()}" if trigger_word else payload.prompt.strip()
        request_body = {
            "prompt": rendered_prompt,
            "guidance_scale": float(payload.parameters.get("guidance_scale") or 2.5),
            "num_inference_steps": int(payload.parameters.get("inference_steps") or 28),
            "image_size": _image_size(
                str(payload.parameters.get("aspect_ratio") or "9:16"),
                str(payload.parameters.get("resolution") or "2K"),
            ),
            "num_images": 1,
            "acceleration": "regular",
            "enable_prompt_expansion": False,
            "enable_safety_checker": True,
            "output_format": "png",
            "loras": [{"path": lora_path, "scale": scale}],
        }
        headers = {"Authorization": f"Key {self.config.api_key}", "Content-Type": "application/json"}
        submitted = self.client.post(
            f"{self.config.queue_base_url}/{FAL_FLUX2_LORA_MODEL}",
            headers=headers,
            json=request_body,
        )
        submitted.raise_for_status()
        submission = submitted.json()
        request_id = str(submission.get("request_id") or "")
        if not request_id:
            raise RuntimeError("fal queue did not return a request_id")
        status_url = str(submission.get("status_url") or f"{self.config.queue_base_url}/{FAL_FLUX2_LORA_MODEL}/requests/{request_id}/status")
        response_url = str(submission.get("response_url") or f"{self.config.queue_base_url}/{FAL_FLUX2_LORA_MODEL}/requests/{request_id}")
        deadline = time.monotonic() + float(payload.parameters.get("timeout_seconds") or 300)
        while time.monotonic() < deadline:
            status_response = self.client.get(status_url, headers=headers)
            status_response.raise_for_status()
            status_payload = status_response.json()
            status = str(status_payload.get("status") or "").upper()
            if status == "COMPLETED":
                break
            if status in {"FAILED", "CANCELLED"}:
                raise RuntimeError(str(status_payload.get("error") or f"fal request {status.lower()}"))
            time.sleep(1)
        else:
            raise RuntimeError(f"fal LoRA generation timed out: {request_id}")
        result_response = self.client.get(response_url, headers=headers)
        result_response.raise_for_status()
        result_payload = result_response.json()
        result = result_payload.get("data") if isinstance(result_payload.get("data"), dict) else result_payload
        images = result.get("images") or []
        image_url = str((images[0] if images else {}).get("url") or "")
        if not image_url:
            raise RuntimeError("fal LoRA generation returned no image URL")
        image_response = self.client.get(image_url)
        image_response.raise_for_status()
        content_type = str(image_response.headers.get("content-type") or (images[0] if images else {}).get("content_type") or "image/png").split(";", 1)[0]
        input_ids = [item.artifact_id for item in inputs]
        return LiveGenerationResult(
            {"kind": "image", "title": "LoRA generated image", "mimeType": content_type},
            "Image",
            "fal.flux2.lora.v1",
            request_id,
            bytes(image_response.content),
            content_type,
            "lora-generated.png",
            input_ids,
        )

    def submit_lora_training(
        self,
        *,
        image_data_url: str,
        trigger_word: str,
        steps: int = 1000,
        learning_rate: float = 0.00005,
    ) -> dict[str, Any]:
        if not image_data_url.startswith(("http://", "https://")):
            raise ValueError("fal LoRA training requires a downloadable HTTP(S) dataset URL")
        headers = self._headers()
        submitted = self.client.post(
            f"{self.config.queue_base_url}/{FAL_FLUX2_TRAINER_MODEL}",
            headers=headers,
            json={
                "image_data_url": image_data_url,
                "steps": steps,
                "learning_rate": learning_rate,
                "default_caption": f"{trigger_word}, same character identity",
                "output_lora_format": "fal",
            },
        )
        submitted.raise_for_status()
        payload = submitted.json()
        request_id = str(payload.get("request_id") or "")
        if not request_id:
            raise RuntimeError("fal trainer queue did not return a request_id")
        return {
            "request_id": request_id,
            "status_url": str(payload.get("status_url") or f"{self.config.queue_base_url}/{FAL_FLUX2_TRAINER_MODEL}/requests/{request_id}/status"),
            "response_url": str(payload.get("response_url") or f"{self.config.queue_base_url}/{FAL_FLUX2_TRAINER_MODEL}/requests/{request_id}"),
            "status": "IN_QUEUE",
        }

    def get_queue_status(self, status_url: str) -> dict[str, Any]:
        response = self.client.get(status_url, headers=self._headers())
        response.raise_for_status()
        return dict(response.json())

    def get_queue_result(self, response_url: str) -> dict[str, Any]:
        response = self.client.get(response_url, headers=self._headers())
        response.raise_for_status()
        payload = response.json()
        return dict(payload.get("data") if isinstance(payload.get("data"), dict) else payload)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Key {self.config.api_key}", "Content-Type": "application/json"}


def _image_size(aspect_ratio: str, resolution: str) -> dict[str, int] | str:
    long_edge = 2048 if resolution.lower() in {"2k", "4k"} else 1280
    if aspect_ratio == "1:1":
        return {"width": long_edge, "height": long_edge}
    if aspect_ratio == "16:9":
        return {"width": long_edge, "height": round(long_edge * 9 / 16)}
    if aspect_ratio == "4:5":
        return {"width": round(long_edge * 4 / 5), "height": long_edge}
    return {"width": round(long_edge * 9 / 16), "height": long_edge}


def get_fal_generation_services() -> FalGenerationServices:
    return FalGenerationServices()
