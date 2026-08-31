from __future__ import annotations

import io
import os
import re
import wave
from dataclasses import dataclass, field
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
class CharacterImageAsset:
    data: bytes
    content_type: str
    filename: str
    role: str
    prompt: str


@dataclass(frozen=True)
class CharacterGenerationResult:
    output: dict[str, object]
    provider_request_id: str
    input_artifact_ids: list[str]
    name: str
    synopsis: str
    images: tuple[CharacterImageAsset, ...]


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
    metadata: dict[str, Any] = field(default_factory=dict)
    cost_usd: float | None = None


@dataclass(frozen=True)
class InputMedia:
    artifact_id: str
    artifact_type: str
    data: bytes
    content_type: str


CHARACTER_SHOTS: tuple[tuple[str, str], ...] = (
    ("baseline", "clean full-body establishing portrait, relaxed neutral standing pose, eye-level camera, softly lit studio environment"),
    ("closeup", "head-and-shoulders three-quarter portrait in warm window light, calm natural expression, facial details in sharp focus"),
    ("daily_life", "candid daily-life scene at a quiet cafe table, seated naturally with hands visible, soft morning daylight"),
    ("work_scene", "focused work scene at a desk appropriate to the character, medium shot, practical indoor lighting"),
    ("action_scene", "single full-body action moment outdoors with readable limbs and balanced anatomy, dynamic side lighting"),
    ("night_scene", "walking alone on a city street at night, three-quarter full-body view, controlled neon rim light and soft facial fill"),
    ("emotional_scene", "emotionally vulnerable quiet moment near a rain-streaked window, medium close shot, subtle expression"),
    ("hero_scene", "decisive full-body hero moment in an environment appropriate to the character, low camera angle, dramatic but coherent lighting"),
)


def character_shot_prompts(synopsis: str, count: int) -> list[tuple[str, str]]:
    count = max(4, min(len(CHARACTER_SHOTS), count))
    identity_lock = (
        "Use the first supplied image as the canonical character identity and design source, never as a layout reference. "
        "Create exactly one depiction of the same character in the entire image: one head, one torso, one pair of arms, and one pair of legs. "
        "Preserve the same face, proportions, hair, eyes, distinctive anatomy, accessories, outfit, palette, and rendering medium in every view. "
        "Use one coherent scene background appropriate to the requested shot while keeping the character as the only depicted subject. "
        "No duplicate character, alternate pose, collage, contact sheet, split panel, inset, extra face, "
        "body-part study, icon, label, arrow, typography, logo, or watermark."
    )
    return [
        (role, f"Character identity specification:\n{synopsis.strip()}\n\nShot: {shot}.\n\n{identity_lock}")
        for role, shot in CHARACTER_SHOTS[:count]
    ]


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

    def generate_images(
        self,
        *,
        logical_model: str,
        prompt: str,
        candidate_count: int,
        aspect_ratio: str,
        seed: int | None,
        reference_images: list[InputMedia],
    ) -> list[GeneratedBinary]:
        return self.image.generate(
            prompt=prompt,
            logical_model=logical_model,
            candidate_count=candidate_count,
            aspect_ratio=aspect_ratio,
            seed=seed,
            reference_images=[(item.data, item.content_type) for item in reference_images[:4]],
        )

    def generate_character(
        self,
        *,
        logical_model: str,
        synopsis: str,
        name: str,
        shot_count: int,
        aspect_ratio: str,
        seed: int | None,
        reference_images: list[InputMedia],
    ) -> CharacterGenerationResult:
        references = reference_images[:3]
        shots = character_shot_prompts(synopsis, shot_count)
        generated_assets: list[CharacterImageAsset] = []
        canonical_reference: tuple[bytes, str] | None = ((references[0].data, references[0].content_type) if references else None)
        supporting_references = references[1:] if references else []
        request_id = ""
        for index, (role, shot_prompt) in enumerate(shots):
            current_references = [*([canonical_reference] if canonical_reference else []), *((item.data, item.content_type) for item in supporting_references)][:4]
            generated = self.image.generate(
                prompt=shot_prompt,
                logical_model=logical_model,
                candidate_count=1,
                aspect_ratio=aspect_ratio,
                seed=(seed + index) if seed is not None else None,
                reference_images=current_references,
            )[0]
            request_id = request_id or generated.provider_request_id
            canonical_reference = canonical_reference or (generated.data, generated.mime_type)
            extension = ".png" if "png" in generated.mime_type else ".jpg"
            generated_assets.append(CharacterImageAsset(generated.data, generated.mime_type, f"character-{index + 1:02d}-{role}{extension}", role, shot_prompt))
        return CharacterGenerationResult(
            {"kind": "image", "title": f"{name} · {len(generated_assets)} views", "mimeType": generated_assets[0].content_type},
            request_id,
            [item.artifact_id for item in reference_images],
            name,
            synopsis,
            tuple(generated_assets),
        )

    def generate_videos(
        self,
        *,
        logical_model: str,
        prompt: str,
        duration_seconds: int,
        candidate_count: int,
        aspect_ratio: str,
        resolution: str,
        seed: int | None,
        image_inputs: list[InputMedia],
        video_inputs: list[InputMedia],
    ) -> list[GeneratedBinary]:
        normalized_resolution = resolution.lower()
        if normalized_resolution not in {"720p", "1080p"}:
            normalized_resolution = "1080p"
        if logical_model == "google.video.omni":
            return self.video.generate_omni(
                prompt=prompt,
                logical_model=logical_model,
                aspect_ratio=aspect_ratio,
                resolution=normalized_resolution,
                reference_images=[(item.data, item.content_type) for item in image_inputs[:3]],
                reference_videos=[(item.data, item.content_type) for item in video_inputs[:1]],
            )
        if video_inputs:
            raise ValueError("Reference Video input requires the Gemini Omni 1.1 Flash model")
        submission = self.video.submit(
            prompt=prompt,
            logical_model=logical_model,
            duration_seconds=duration_seconds,
            candidate_count=max(1, min(4, candidate_count)),
            aspect_ratio=aspect_ratio,
            seed=seed,
            output_gcs_uri=os.getenv("GOOGLE_VIDEO_OUTPUT_GCS_URI") or None,
            reference_images=[(item.data, item.content_type) for item in image_inputs[:3]],
            resolution=normalized_resolution,
        )
        return self.video.wait_for_generated(
            submission,
            logical_model=logical_model,
            timeout_seconds=int(os.getenv("GOOGLE_VIDEO_TIMEOUT_SECONDS", "900")),
            poll_interval_seconds=float(os.getenv("GOOGLE_VIDEO_POLL_SECONDS", "10")),
        )

    def execute(self, payload: ExperimentRunRequest, inputs: list[InputMedia]) -> LiveGenerationResult | CharacterGenerationResult:
        logical_model = payload.model_alias if payload.model_alias.startswith("google.") else f"google.{payload.model_alias}"
        input_ids = [item.artifact_id for item in inputs]
        seed = payload.parameters.get("seed")
        seed_value = int(seed) if seed is not None else None

        if payload.node_key == "character.generate":
            reference_inputs = [item for item in inputs if item.artifact_type == "Image"][:3]
            name = str(payload.parameters.get("character_name") or "Generated character").strip() or "Generated character"
            return self.generate_character(
                logical_model=logical_model,
                synopsis=payload.prompt,
                name=name,
                shot_count=int(payload.parameters.get("shot_count") or 6),
                aspect_ratio=str(payload.parameters.get("aspect_ratio") or "9:16"),
                seed=seed_value,
                reference_images=reference_inputs,
            )

        if payload.node_key in {"image.generate", "image.edit"}:
            candidate_count = max(1, min(4, int(payload.parameters.get("output_count") or 1)))
            image_inputs = [item for item in inputs if item.artifact_type == "Image"][:4]
            generated_images = self.generate_images(
                logical_model=logical_model,
                prompt=payload.prompt,
                candidate_count=candidate_count,
                aspect_ratio=str(payload.parameters.get("aspect_ratio") or "9:16"),
                seed=seed_value,
                reference_images=image_inputs,
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
            video_inputs = [item for item in inputs if item.artifact_type in {"Video", "FinalVideo"}][:1]
            generated_videos = self.generate_videos(
                logical_model=logical_model,
                prompt=payload.prompt,
                duration_seconds=int(payload.parameters.get("duration_seconds") or 6),
                candidate_count=int(payload.parameters.get("output_count") or 1),
                aspect_ratio=str(payload.parameters.get("aspect_ratio") or "9:16"),
                resolution=str(payload.parameters.get("resolution") or "720p"),
                seed=seed_value,
                image_inputs=image_inputs,
                video_inputs=video_inputs,
            )
            generated = generated_videos[0]
            omni = logical_model == "google.video.omni"
            return LiveGenerationResult(
                {"kind": "video", "title": "Generated character video" if omni else "Generated video", "mimeType": generated.mime_type},
                "Video", "google.video.omni.v1" if omni else "google.video.v1", generated.provider_request_id, generated.data,
                generated.mime_type, "generated-character.mp4" if omni else "generated.mp4", input_ids,
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
