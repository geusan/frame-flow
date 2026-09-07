from __future__ import annotations

import base64
import hashlib
import os
from dataclasses import dataclass
from typing import Any

from openai import OpenAI

from .providers import OPENAI_MODEL_REGISTRY
from .providers_generation import (
    CharacterGenerationResult,
    CharacterImageAsset,
    InputMedia,
    character_shot_prompts,
)


OPENAI_LIVE_REVISION = "openai-live.v1"


@dataclass(frozen=True)
class OpenAIProviderConfig:
    api_key: str
    base_url: str | None = None
    organization: str | None = None
    project: str | None = None

    @classmethod
    def from_env(cls) -> "OpenAIProviderConfig":
        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is required for OpenAI provider models")
        return cls(
            api_key=api_key,
            base_url=os.getenv("OPENAI_BASE_URL") or None,
            organization=os.getenv("OPENAI_ORG_ID") or None,
            project=os.getenv("OPENAI_PROJECT_ID") or None,
        )


class OpenAIGenerationServices:
    def __init__(self, config: OpenAIProviderConfig | None = None, client: Any | None = None) -> None:
        self.config = config or OpenAIProviderConfig.from_env()
        self.client = client or OpenAI(
            api_key=self.config.api_key,
            base_url=self.config.base_url,
            organization=self.config.organization,
            project=self.config.project,
        )

    def generate_text(self, *, logical_model: str, prompt: str, instructions: str) -> tuple[str, str]:
        try:
            exact_model = OPENAI_MODEL_REGISTRY[logical_model]
        except KeyError as exc:
            raise ValueError(f"OpenAI model alias is not registered: {logical_model}") from exc
        response = self.client.responses.create(
            model=exact_model,
            instructions=instructions,
            input=prompt,
            store=False,
        )
        text = str(response.output_text or "").strip()
        if not text:
            raise RuntimeError("OpenAI Responses API returned no text")
        return text, str(response.id)

    def generate_images(
        self,
        *,
        logical_model: str,
        prompt: str,
        count: int,
        aspect_ratio: str,
        quality: str,
        reference_images: list[InputMedia],
    ) -> tuple[list[bytes], str]:
        try:
            exact_model = OPENAI_MODEL_REGISTRY[logical_model]
        except KeyError as exc:
            raise ValueError(f"OpenAI model alias is not registered: {logical_model}") from exc
        common = {
            "model": exact_model,
            "prompt": prompt,
            "n": max(1, min(4, count)),
            "size": _image_size(aspect_ratio),
            "quality": quality,
            "output_format": "png",
        }
        response = self.client.images.edit(
            image=[(f"input-{index}.png", item.data, item.content_type) for index, item in enumerate(reference_images[:4], start=1)],
            **common,
        ) if reference_images else self.client.images.generate(**common)
        images = [base64.b64decode(item.b64_json) for item in response.data if item.b64_json]
        if not images:
            raise RuntimeError("OpenAI Images API returned no image")
        request_id = f"openai_{hashlib.sha256((prompt + str(response.created)).encode()).hexdigest()[:20]}"
        return images, request_id

    def generate_character(
        self,
        *,
        logical_model: str,
        synopsis: str,
        name: str,
        shot_count: int,
        aspect_ratio: str,
        quality: str,
        reference_images: list[InputMedia],
    ) -> CharacterGenerationResult:
        shots = character_shot_prompts(synopsis, shot_count)
        generated_assets: list[CharacterImageAsset] = []
        canonical = reference_images[0] if reference_images else None
        supporting_references = reference_images[1:3] if reference_images else []
        request_id = ""
        for index, (role, shot_prompt) in enumerate(shots):
            image_inputs = [*([canonical] if canonical else []), *supporting_references][:4]
            images, current_request_id = self.generate_images(
                logical_model=logical_model,
                prompt=shot_prompt,
                count=1,
                aspect_ratio=aspect_ratio,
                quality=quality,
                reference_images=image_inputs,
            )
            data = images[0]
            request_id = request_id or current_request_id
            canonical = canonical or InputMedia("generated-canonical", "Image", data, "image/png")
            generated_assets.append(CharacterImageAsset(data, "image/png", f"character-{index + 1:02d}-{role}.png", role, shot_prompt))
        return CharacterGenerationResult(
            {"kind": "image", "title": f"{name} · {len(generated_assets)} views", "mimeType": "image/png"},
            request_id,
            [item.artifact_id for item in reference_images],
            name,
            synopsis,
            tuple(generated_assets),
        )

    def generate_speech(
        self,
        *,
        logical_model: str,
        text: str,
        voice_name: str,
        style_prompt: str,
    ) -> tuple[bytes, str, str]:
        try:
            exact_model = OPENAI_MODEL_REGISTRY[logical_model]
        except KeyError as exc:
            raise ValueError(f"OpenAI model alias is not registered: {logical_model}") from exc
        speech_request = {
            "model": exact_model,
            "voice": voice_name,
            "input": text,
            "response_format": "wav",
        }
        if exact_model.startswith("gpt-4o-mini-tts"):
            speech_request["instructions"] = style_prompt
        response = self.client.audio.speech.create(**speech_request)
        audio = bytes(response.content)
        if not audio:
            raise RuntimeError("OpenAI Speech API returned no audio")
        request_id = f"openai_{hashlib.sha256((text + exact_model).encode()).hexdigest()[:20]}"
        return audio, request_id, exact_model


def _image_size(aspect_ratio: str) -> str:
    if aspect_ratio == "16:9":
        return "1536x1024"
    if aspect_ratio == "1:1":
        return "1024x1024"
    return "1024x1536"


def get_openai_generation_services() -> OpenAIGenerationServices:
    return OpenAIGenerationServices()
