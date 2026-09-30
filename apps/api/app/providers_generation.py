from __future__ import annotations

import io
import os
import re
import wave
from dataclasses import dataclass

from .nodes.contracts import NodeInputMedia
from .providers_google import (
    GeneratedBinary,
    GoogleImageProvider,
    GoogleProviderConfig,
    GoogleTextProvider,
    GoogleTtsProvider,
    GoogleVideoProvider,
)


LIVE_GENERATION_REVISION = "google-live.v1"


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


InputMedia = NodeInputMedia


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


STUDIO_CHARACTER_SHOTS: tuple[tuple[str, str], ...] = (
    ("baseline", "full-body front view, relaxed neutral standing pose, both hands and both feet visible"),
    ("front", "front-facing head-and-shoulders portrait, calm neutral expression"),
    ("three_quarter_left", "head-and-shoulders portrait with the subject turned 45 degrees toward camera-left"),
    ("three_quarter_right", "head-and-shoulders portrait with the subject turned 45 degrees toward camera-right"),
    ("profile_left", "clean left-side profile head-and-shoulders portrait, nose pointing camera-left"),
    ("profile_right", "clean right-side profile head-and-shoulders portrait, nose pointing camera-right"),
    ("back", "full-body rear view, back to the camera, arms relaxed, hair silhouette and outfit visible"),
    ("smile", "front-facing waist-up portrait, small natural smile, relaxed shoulders"),
)


def character_shot_prompts(synopsis: str, count: int, *, shot_style: str = "story") -> list[tuple[str, str]]:
    count = max(4, min(len(CHARACTER_SHOTS), count))
    identity_lock = (
        "Use the first supplied image as the canonical character identity and design source, never as a layout reference. "
        "Create exactly one depiction of the same character in the entire image: one head, one torso, one pair of arms, and one pair of legs. "
        "Preserve the same face, proportions, hair, eyes, distinctive anatomy, accessories, outfit, palette, and rendering medium in every view. "
        "Use one coherent scene background appropriate to the requested shot while keeping the character as the only depicted subject. "
        "No duplicate character, alternate pose, collage, contact sheet, split panel, inset, extra face, "
        "body-part study, icon, label, arrow, typography, logo, or watermark."
    )
    shots = CHARACTER_SHOTS
    if shot_style == "studio":
        shots = STUDIO_CHARACTER_SHOTS
        identity_lock = (
            "The first supplied photograph defines the character's face and hair; the remaining photographs guide only styling and posing. "
            "Photograph exactly one person in the same seamless neutral-gray studio in every view. "
            "Keep facial structure, age, skin tone, body proportions, haircut, wardrobe and natural photographic medium consistent. "
            "Change only the requested view and expression. Keep the camera level, perspective natural, and studio lighting consistent. "
            "No cafe, desk, street, outdoor scene, dramatic narrative, collage, duplicate person, labels, logo or watermark."
        )
    return [
        (role, f"Character identity specification:\n{synopsis.strip()}\n\nShot: {shot}.\n\n{identity_lock}")
        for role, shot in shots[:count]
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

    def generate_speech(
        self,
        *,
        logical_model: str,
        text: str,
        style_prompt: str,
        voice_name: str,
        locale: str,
    ) -> GeneratedBinary:
        generated = self.tts.synthesize(
            text=text,
            style_prompt=style_prompt,
            voice_name=voice_name,
            locale=locale,
            logical_model=logical_model,
        )
        return GeneratedBinary(_audio_to_wav(generated), "audio/wav", generated.exact_model_id, generated.provider_request_id)


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
