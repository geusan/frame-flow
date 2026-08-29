from __future__ import annotations

import base64
import hashlib
import os
from dataclasses import dataclass
from typing import Any

from openai import OpenAI

from .domain import ExperimentRunRequest
from .providers import OPENAI_MODEL_REGISTRY
from .providers_generation import GeneratedAsset, InputMedia, LiveGenerationResult
from .project_skills import project_skill_system_prompt


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

    def execute(self, payload: ExperimentRunRequest, inputs: list[InputMedia]) -> LiveGenerationResult:
        logical_model = payload.model_alias
        try:
            exact_model = OPENAI_MODEL_REGISTRY[logical_model]
        except KeyError as exc:
            raise ValueError(f"OpenAI model alias is not registered: {logical_model}") from exc
        input_ids = [item.artifact_id for item in inputs]

        if payload.node_key in {"llm.assistant", "script.generate", "skill.execute"}:
            if payload.node_key == "skill.execute":
                instructions = project_skill_system_prompt(
                    str(payload.parameters.get("skill_id") or ""),
                    str(payload.parameters.get("skill_version") or "") or None,
                )
            else:
                instructions = (
                    "Write only the final narration script for a short-form video. Preserve factual meaning, use natural spoken language, and do not add meta commentary."
                    if payload.node_key == "script.generate"
                    else "Transform the user's prompt as requested. Return only the useful final text without meta commentary."
                )
            response = self.client.responses.create(
                model=exact_model,
                instructions=instructions,
                input=payload.prompt,
                store=False,
            )
            text = str(response.output_text or "").strip()
            if not text:
                raise RuntimeError("OpenAI Responses API returned no text")
            artifact_type = "Script" if payload.node_key == "script.generate" else "Text"
            skill_execution = payload.node_key == "skill.execute"
            return LiveGenerationResult(
                {"kind": "text", "title": "Generated script" if artifact_type == "Script" else "Generated master prompt" if skill_execution else "Generated text", "text": text},
                artifact_type, "script.v1" if artifact_type == "Script" else "prompt.master.v1" if skill_execution else "openai.text.v1",
                response.id, text.encode(), "text/plain", "master-prompt.txt" if skill_execution else "result.txt", input_ids,
            )

        if payload.node_key in {"image.generate", "image.edit"}:
            count = max(1, min(4, int(payload.parameters.get("output_count") or 1)))
            size = _image_size(str(payload.parameters.get("aspect_ratio") or "9:16"))
            image_inputs = [item for item in inputs if item.artifact_type == "Image"][:4]
            common = {
                "model": exact_model,
                "prompt": payload.prompt,
                "n": count,
                "size": size,
                "quality": str(payload.parameters.get("quality") or "medium"),
                "output_format": "png",
            }
            response = self.client.images.edit(
                image=[(f"input-{index}.png", item.data, item.content_type) for index, item in enumerate(image_inputs, start=1)],
                **common,
            ) if image_inputs else self.client.images.generate(**common)
            images = [base64.b64decode(item.b64_json) for item in response.data if item.b64_json]
            if not images:
                raise RuntimeError("OpenAI Images API returned no image")
            request_id = f"openai_{hashlib.sha256((payload.prompt + str(response.created)).encode()).hexdigest()[:20]}"
            editing = payload.node_key == "image.edit"
            return LiveGenerationResult(
                {"kind": "image", "title": "AI edited image" if editing else "Generated image", "mimeType": "image/png"},
                "Image", "openai.image.edit.v1" if editing else "openai.image.v1", request_id, images[0], "image/png", "edited.png" if editing else "generated.png", input_ids,
                tuple(GeneratedAsset(data, "image/png", f"{'edited' if editing else 'generated'}-{index}.png") for index, data in enumerate(images[1:], start=2)),
            )

        if payload.node_key == "tts.generate":
            speech_request = {
                "model": exact_model,
                "voice": str(payload.parameters.get("voice_name") or "coral"),
                "input": payload.prompt,
                "response_format": "wav",
            }
            if exact_model.startswith("gpt-4o-mini-tts"):
                speech_request["instructions"] = str(
                    payload.parameters.get("style_prompt")
                    or "Speak naturally and clearly for a short-form video."
                )
            response = self.client.audio.speech.create(**speech_request)
            audio = bytes(response.content)
            if not audio:
                raise RuntimeError("OpenAI Speech API returned no audio")
            request_id = f"openai_{hashlib.sha256((payload.prompt + exact_model).encode()).hexdigest()[:20]}"
            return LiveGenerationResult(
                {"kind": "audio", "title": "Generated voiceover", "mimeType": "audio/wav"},
                "Audio", "openai.tts.v1", request_id, audio, "audio/wav", "voiceover.wav", input_ids,
            )

        raise ValueError(f"OpenAI provider does not support Canvas node: {payload.node_key}")


def _image_size(aspect_ratio: str) -> str:
    if aspect_ratio == "16:9":
        return "1536x1024"
    if aspect_ratio == "1:1":
        return "1024x1024"
    return "1024x1536"


def get_openai_generation_services() -> OpenAIGenerationServices:
    return OpenAIGenerationServices()
