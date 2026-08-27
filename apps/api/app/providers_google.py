from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from typing import Any

from google import genai
from google.genai import types

from .providers import MODEL_REGISTRY, ProviderSubmission


class GoogleProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class GoogleProviderConfig:
    project: str
    location: str = "global"
    api_version: str = "v1"

    @classmethod
    def from_env(cls) -> "GoogleProviderConfig":
        project = os.getenv("GOOGLE_CLOUD_PROJECT", "")
        if not project:
            raise GoogleProviderError("GOOGLE_CLOUD_PROJECT is required for live Google providers")
        return cls(project=project, location=os.getenv("GOOGLE_CLOUD_LOCATION", "global"))


@dataclass(frozen=True)
class GeneratedBinary:
    data: bytes
    mime_type: str
    exact_model_id: str
    provider_request_id: str


def request_hash(logical_model: str, payload: dict[str, Any]) -> str:
    normalized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(f"google:{logical_model}:{normalized}".encode()).hexdigest()


def _request_id(value: str) -> str:
    return f"google_{value[:20]}"


class GoogleProviderBase:
    def __init__(self, config: GoogleProviderConfig | None = None, client: Any | None = None) -> None:
        self.config = config or GoogleProviderConfig.from_env()
        self.client = client or genai.Client(
            vertexai=True,
            project=self.config.project,
            location=self.config.location,
            http_options=types.HttpOptions(api_version=self.config.api_version),
        )

    @staticmethod
    def exact_model(logical_model: str) -> str:
        try:
            return MODEL_REGISTRY[logical_model]
        except KeyError as exc:
            raise GoogleProviderError(f"logical model is not registered: {logical_model}") from exc


class GoogleTextProvider(GoogleProviderBase):
    def generate_text(
        self,
        *,
        logical_model: str,
        system_prompt: str,
        rendered_prompt: str,
        temperature: float = 0.4,
        seed: int | None = None,
    ) -> tuple[str, str]:
        exact_model = self.exact_model(logical_model)
        payload = {
            "model": exact_model,
            "system_prompt": system_prompt,
            "rendered_prompt": rendered_prompt,
            "temperature": temperature,
            "seed": seed,
        }
        digest = request_hash(logical_model, payload)
        response = self.client.models.generate_content(
            model=exact_model,
            contents=rendered_prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                response_modalities=[types.Modality.TEXT],
                temperature=temperature,
                seed=seed,
            ),
        )
        if not response.text:
            raise GoogleProviderError("Google text provider returned no content")
        return response.text, _request_id(digest)

    def generate_structured(
        self,
        *,
        logical_model: str,
        system_prompt: str,
        rendered_prompt: str,
        output_json_schema: dict[str, Any],
        temperature: float = 0.2,
        seed: int | None = None,
    ) -> tuple[dict[str, Any], str]:
        exact_model = self.exact_model(logical_model)
        payload = {
            "model": exact_model,
            "system_prompt": system_prompt,
            "rendered_prompt": rendered_prompt,
            "output_json_schema": output_json_schema,
            "temperature": temperature,
            "seed": seed,
        }
        digest = request_hash(logical_model, payload)
        response = self.client.models.generate_content(
            model=exact_model,
            contents=rendered_prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                response_mime_type="application/json",
                response_json_schema=output_json_schema,
                temperature=temperature,
                seed=seed,
            ),
        )
        if not response.text:
            raise GoogleProviderError("Google text provider returned no structured content")
        try:
            return json.loads(response.text), _request_id(digest)
        except json.JSONDecodeError as exc:
            raise GoogleProviderError("Google text response did not contain valid JSON") from exc


class GoogleImageProvider(GoogleProviderBase):
    def generate(
        self,
        *,
        prompt: str,
        logical_model: str = "google.image.fast",
        candidate_count: int = 1,
        aspect_ratio: str = "9:16",
        seed: int | None = None,
    ) -> list[GeneratedBinary]:
        if not 1 <= candidate_count <= 4:
            raise GoogleProviderError("candidate_count must be between 1 and 4")
        exact_model = self.exact_model(logical_model)
        payload = {"model": exact_model, "prompt": prompt, "candidate_count": candidate_count, "aspect_ratio": aspect_ratio, "seed": seed}
        digest = request_hash(logical_model, payload)
        response = self.client.models.generate_content(
            model=exact_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                candidate_count=candidate_count,
                response_modalities=[types.Modality.TEXT, types.Modality.IMAGE],
                image_config=types.ImageConfig(aspect_ratio=aspect_ratio),
                seed=seed,
            ),
        )
        generated: list[GeneratedBinary] = []
        for candidate in response.candidates or []:
            for part in candidate.content.parts or []:
                if part.inline_data and part.inline_data.data:
                    generated.append(GeneratedBinary(part.inline_data.data, part.inline_data.mime_type or "image/png", exact_model, _request_id(digest)))
        if not generated:
            raise GoogleProviderError("Google image provider returned no image parts")
        return generated


class GoogleVideoProvider(GoogleProviderBase):
    def submit(
        self,
        *,
        prompt: str,
        logical_model: str = "google.video.fast",
        duration_seconds: int = 4,
        candidate_count: int = 1,
        aspect_ratio: str = "9:16",
        seed: int | None = None,
        output_gcs_uri: str | None = None,
        image_data: bytes | None = None,
        image_mime_type: str = "image/png",
        resolution: str = "720p",
    ) -> ProviderSubmission:
        if duration_seconds not in {4, 6, 8}:
            raise GoogleProviderError("Veo shot duration must be 4, 6, or 8 seconds")
        if not 1 <= candidate_count <= 4:
            raise GoogleProviderError("Veo candidate_count must be between 1 and 4")
        exact_model = self.exact_model(logical_model)
        payload = {"model": exact_model, "prompt": prompt, "duration_seconds": duration_seconds, "candidate_count": candidate_count, "aspect_ratio": aspect_ratio, "seed": seed, "output_gcs_uri": output_gcs_uri, "has_image": image_data is not None, "resolution": resolution}
        digest = request_hash(logical_model, payload)
        operation = self.client.models.generate_videos(
            model=exact_model,
            source=types.GenerateVideosSource(
                prompt=prompt,
                image=types.Image(image_bytes=image_data, mime_type=image_mime_type) if image_data else None,
            ),
            config=types.GenerateVideosConfig(
                duration_seconds=duration_seconds,
                number_of_videos=candidate_count,
                aspect_ratio=aspect_ratio,
                generate_audio=True,
                enhance_prompt=True,
                seed=seed,
                output_gcs_uri=output_gcs_uri,
                resolution=resolution,
            ),
        )
        if not operation.name:
            raise GoogleProviderError("Google video provider did not return an operation ID")
        return ProviderSubmission(_request_id(digest), operation.name, digest)

    def poll(self, operation_id: str) -> tuple[bool, list[str]]:
        operation = self.client.operations.get(types.GenerateVideosOperation(name=operation_id))
        if not operation.done:
            return False, []
        if operation.error:
            raise GoogleProviderError(f"Google video operation failed: {operation.error}")
        response = operation.response or operation.result
        videos = getattr(response, "generated_videos", None) or []
        uris = [generated.video.uri for generated in videos if generated.video and generated.video.uri]
        return True, uris

    def wait_for_generated(
        self,
        submission: ProviderSubmission,
        *,
        logical_model: str = "google.video.fast",
        timeout_seconds: int = 900,
        poll_interval_seconds: float = 10,
    ) -> list[GeneratedBinary]:
        if not submission.provider_operation_id:
            raise GoogleProviderError("Google video submission has no operation ID")
        deadline = time.monotonic() + timeout_seconds
        operation = types.GenerateVideosOperation(name=submission.provider_operation_id)
        while time.monotonic() < deadline:
            operation = self.client.operations.get(operation)
            if operation.done:
                break
            time.sleep(poll_interval_seconds)
        if not operation.done:
            raise GoogleProviderError(f"Google video operation timed out: {submission.provider_operation_id}")
        if operation.error:
            raise GoogleProviderError(f"Google video operation failed: {operation.error}")
        response = operation.response or operation.result
        videos = getattr(response, "generated_videos", None) or []
        generated_results: list[GeneratedBinary] = []
        for generated in videos:
            video = getattr(generated, "video", None)
            if not video:
                continue
            data = getattr(video, "video_bytes", None)
            mime_type = getattr(video, "mime_type", None) or "video/mp4"
            if not data and getattr(video, "uri", None):
                data = self._download_gcs(video.uri)
            if data:
                generated_results.append(GeneratedBinary(data, mime_type, self.exact_model(logical_model), submission.provider_request_id))
        if not generated_results:
            raise GoogleProviderError("Google video operation returned no downloadable video")
        return generated_results

    @staticmethod
    def _download_gcs(uri: str) -> bytes:
        if not uri.startswith("gs://"):
            raise GoogleProviderError(f"unsupported generated video URI: {uri}")
        try:
            from google.cloud import storage
        except ImportError as exc:
            raise GoogleProviderError("google-cloud-storage is required to download Veo GCS output") from exc
        bucket_name, _, blob_name = uri[5:].partition("/")
        if not bucket_name or not blob_name:
            raise GoogleProviderError(f"invalid generated video GCS URI: {uri}")
        return storage.Client().bucket(bucket_name).blob(blob_name).download_as_bytes()


class GoogleTtsProvider(GoogleProviderBase):
    def synthesize(
        self,
        *,
        text: str,
        style_prompt: str,
        voice_name: str,
        locale: str = "ko-KR",
        logical_model: str = "google.tts.fast",
    ) -> GeneratedBinary:
        exact_model = self.exact_model(logical_model)
        rendered = f"{style_prompt.strip()}\n\nRead the following text exactly:\n{text.strip()}"
        digest = request_hash(logical_model, {"model": exact_model, "text": text, "style_prompt": style_prompt, "voice_name": voice_name, "locale": locale})
        response = self.client.models.generate_content(
            model=exact_model,
            contents=rendered,
            config=types.GenerateContentConfig(
                response_modalities=[types.Modality.AUDIO],
                speech_config=types.SpeechConfig(
                    language_code=locale,
                    voice_config=types.VoiceConfig(prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice_name)),
                ),
            ),
        )
        for candidate in response.candidates or []:
            for part in candidate.content.parts or []:
                if part.inline_data and part.inline_data.data:
                    return GeneratedBinary(part.inline_data.data, part.inline_data.mime_type or "audio/pcm;rate=24000", exact_model, _request_id(digest))
        raise GoogleProviderError("Gemini-TTS returned no audio data")
