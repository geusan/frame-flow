from __future__ import annotations

import io
import os
import re
import wave
from dataclasses import dataclass
from typing import Any

from .domain import ExperimentRunRequest
from .providers_google import (
    GeneratedBinary,
    GoogleImageProvider,
    GoogleProviderConfig,
    GoogleTextProvider,
    GoogleTtsProvider,
    GoogleVideoProvider,
)
from .project_skills import project_skill_system_prompt


LIVE_GENERATION_REVISION = "google-live.v1"


@dataclass(frozen=True)
class GeneratedAsset:
    data: bytes
    content_type: str
    filename: str


@dataclass(frozen=True)
class LiveGenerationResult:
    output: dict[str, object]
    artifact_type: str
    schema_id: str | None
    provider_request_id: str
    content: bytes
    content_type: str
    filename: str
    input_artifact_ids: list[str]
    additional_assets: tuple[GeneratedAsset, ...] = ()


@dataclass(frozen=True)
class InputMedia:
    artifact_id: str
    artifact_type: str
    data: bytes
    content_type: str


class GoogleGenerationServices:
    def __init__(
        self,
        *,
        text: GoogleTextProvider,
        image: GoogleImageProvider,
        video: GoogleVideoProvider,
        tts: GoogleTtsProvider,
    ) -> None:
        self.text = text
        self.image = image
        self.video = video
        self.tts = tts

    def execute(self, payload: ExperimentRunRequest, inputs: list[InputMedia]) -> LiveGenerationResult:
        logical_model = payload.model_alias if payload.model_alias.startswith("google.") else f"google.{payload.model_alias}"
        input_ids = [item.artifact_id for item in inputs]
        seed = payload.parameters.get("seed")
        seed_value = int(seed) if seed is not None else None

        if payload.node_key in {"image.generate", "image.edit"}:
            candidate_count = max(1, min(4, int(payload.parameters.get("output_count") or 1)))
            image_inputs = [item for item in inputs if item.artifact_type == "Image"][:4]
            generated_images = self.image.generate(
                prompt=payload.prompt,
                logical_model=logical_model,
                candidate_count=candidate_count,
                aspect_ratio=str(payload.parameters.get("aspect_ratio") or "9:16"),
                seed=seed_value,
                reference_images=[(item.data, item.content_type) for item in image_inputs],
            )
            generated = generated_images[0]
            extension = ".png" if "png" in generated.mime_type else ".jpg"
            editing = payload.node_key == "image.edit"
            return LiveGenerationResult(
                {"kind": "image", "title": "AI edited image" if editing else "Generated image", "mimeType": generated.mime_type},
                "Image", "google.image.edit.v1" if editing else "google.image.v1", generated.provider_request_id, generated.data,
                generated.mime_type, f"{'edited' if editing else 'generated'}{extension}", input_ids,
                tuple(GeneratedAsset(item.data, item.mime_type, f"{'edited' if editing else 'generated'}-{index}{'.png' if 'png' in item.mime_type else '.jpg'}") for index, item in enumerate(generated_images[1:], start=2)),
            )

        if payload.node_key == "video.generate":
            image_inputs = [item for item in inputs if item.artifact_type == "Image"][:3]
            duration = int(payload.parameters.get("duration_seconds") or 6)
            resolution = str(payload.parameters.get("resolution") or "720p").lower()
            if resolution not in {"720p", "1080p"}:
                resolution = "1080p"
            candidate_count = max(1, min(4, int(payload.parameters.get("output_count") or 1)))
            submission = self.video.submit(
                prompt=payload.prompt,
                logical_model=logical_model,
                duration_seconds=duration,
                candidate_count=candidate_count,
                aspect_ratio=str(payload.parameters.get("aspect_ratio") or "9:16"),
                seed=seed_value,
                output_gcs_uri=os.getenv("GOOGLE_VIDEO_OUTPUT_GCS_URI") or None,
                reference_images=[(item.data, item.content_type) for item in image_inputs],
                resolution=resolution,
            )
            generated_videos = self.video.wait_for_generated(
                submission,
                logical_model=logical_model,
                timeout_seconds=int(os.getenv("GOOGLE_VIDEO_TIMEOUT_SECONDS", "900")),
                poll_interval_seconds=float(os.getenv("GOOGLE_VIDEO_POLL_SECONDS", "10")),
            )
            generated = generated_videos[0]
            return LiveGenerationResult(
                {"kind": "video", "title": "Generated video", "mimeType": generated.mime_type},
                "Video", "google.video.v1", generated.provider_request_id, generated.data,
                generated.mime_type, "generated.mp4", input_ids,
                tuple(GeneratedAsset(item.data, item.mime_type, f"generated-{index}.mp4") for index, item in enumerate(generated_videos[1:], start=2)),
            )

        if payload.node_key == "tts.generate":
            generated = self.tts.synthesize(
                text=payload.prompt,
                style_prompt=str(payload.parameters.get("style_prompt") or "Read naturally and clearly for a short-form video."),
                voice_name=str(payload.parameters.get("voice_name") or "Kore"),
                locale=str(payload.parameters.get("language") or "ko-KR"),
                logical_model=logical_model,
            )
            wav = _audio_to_wav(generated)
            return LiveGenerationResult(
                {"kind": "audio", "title": "Generated voiceover", "mimeType": "audio/wav"},
                "Audio", "google.tts.v1", generated.provider_request_id, wav,
                "audio/wav", "voiceover.wav", input_ids,
            )

        if payload.node_key in {"llm.assistant", "script.generate", "skill.execute"}:
            if payload.node_key == "skill.execute":
                system_prompt = project_skill_system_prompt(
                    str(payload.parameters.get("skill_id") or ""),
                    str(payload.parameters.get("skill_version") or "") or None,
                )
            else:
                system_prompt = (
                    "Write only the final narration script for a short-form video. Preserve factual meaning, use natural spoken language, and do not add commentary."
                    if payload.node_key == "script.generate"
                    else "Transform the user's prompt as requested. Return only the useful final text without meta commentary."
                )
            text, request_id = self.text.generate_text(
                logical_model=logical_model,
                system_prompt=system_prompt,
                rendered_prompt=payload.prompt,
                temperature=float(payload.parameters.get("temperature") or 0.4),
                seed=seed_value,
            )
            artifact_type = "Script" if payload.node_key == "script.generate" else "Text"
            schema_id = "script.v1" if payload.node_key == "script.generate" else "prompt.master.v1" if payload.node_key == "skill.execute" else "google.text.v1"
            title = "Generated script" if payload.node_key == "script.generate" else "Generated master prompt" if payload.node_key == "skill.execute" else "Generated text"
            return LiveGenerationResult(
                {"kind": "text", "title": title, "text": text}, artifact_type, schema_id,
                request_id, text.encode(), "text/plain", "master-prompt.txt" if payload.node_key == "skill.execute" else "result.txt", input_ids,
            )

        raise ValueError(f"unsupported live Google generation node: {payload.node_key}")


def _audio_to_wav(generated: GeneratedBinary) -> bytes:
    mime_type = generated.mime_type.lower()
    if mime_type.startswith("audio/wav") or mime_type.startswith("audio/x-wav"):
        return generated.data
    if mime_type.startswith("audio/pcm") or mime_type.startswith("audio/l16"):
        rate_match = re.search(r"rate=(\d+)", mime_type)
        sample_rate = int(rate_match.group(1)) if rate_match else 24_000
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(sample_rate)
            output.writeframes(generated.data)
        return buffer.getvalue()
    raise RuntimeError(f"unsupported Gemini-TTS output type: {generated.mime_type}")


def get_google_generation_services() -> GoogleGenerationServices:
    config = GoogleProviderConfig.from_env()
    return GoogleGenerationServices(
        text=GoogleTextProvider(config),
        image=GoogleImageProvider(config),
        video=GoogleVideoProvider(config),
        tts=GoogleTtsProvider(config),
    )
