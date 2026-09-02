from __future__ import annotations

import base64
import hashlib
import json
import os
import time
from dataclasses import dataclass
from typing import Any

from google import genai
from google.genai import types

from .google_service_account import google_credentials_from_env, google_project_from_env
from .providers import MODEL_REGISTRY, ProviderSubmission, model_id_for_alias


class GoogleProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class GoogleProviderConfig:
    project: str | None = None
    location: str = "global"
    api_version: str = "v1"
    api_key: str | None = None
    credentials: Any | None = None

    @classmethod
    def from_env(cls) -> "GoogleProviderConfig":
        project = google_project_from_env()
        credentials = google_credentials_from_env()
        if not project or credentials is None:
            raise GoogleProviderError("Google Service Account JSON is required for live Google providers")
        return cls(project=project, credentials=credentials, location=os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1"), api_version="v1")


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
        self.client = client or (
            genai.Client(api_key=self.config.api_key)
            if self.config.api_key
            else genai.Client(
                vertexai=True,
                project=self.config.project,
                location=self.config.location,
                credentials=self.config.credentials,
                http_options=types.HttpOptions(api_version=self.config.api_version),
            )
        )

    def exact_model(self, logical_model: str) -> str:
        exact_model = model_id_for_alias(logical_model, gemini_api=bool(self.config.api_key))
        if not exact_model or logical_model not in MODEL_REGISTRY:
            raise GoogleProviderError(f"logical model is not registered: {logical_model}")
        return exact_model


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
        reference_images: list[tuple[bytes, str]] | None = None,
    ) -> list[GeneratedBinary]:
        if not 1 <= candidate_count <= 4:
            raise GoogleProviderError("candidate_count must be between 1 and 4")
        exact_model = self.exact_model(logical_model)
        references = reference_images or []
        payload = {"model": exact_model, "prompt": prompt, "candidate_count": candidate_count, "aspect_ratio": aspect_ratio, "seed": seed, "reference_hashes": [hashlib.sha256(data).hexdigest() for data, _ in references]}
        digest = request_hash(logical_model, payload)
        response = self.client.models.generate_content(
            model=exact_model,
            contents=[prompt, *(types.Part.from_bytes(data=data, mime_type=mime_type) for data, mime_type in references)] if references else prompt,
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
    def generate_omni(
        self,
        *,
        prompt: str,
        logical_model: str = "google.video.omni",
        aspect_ratio: str = "9:16",
        resolution: str = "720p",
        reference_images: list[tuple[bytes, str]] | None = None,
        reference_videos: list[tuple[bytes, str]] | None = None,
    ) -> list[GeneratedBinary]:
        if not self.config.api_key:
            raise GoogleProviderError("Gemini Omni video generation requires a Gemini API key")
        images = (reference_images or [])[:4]
        videos = (reference_videos or [])[:1]
        exact_model = self.exact_model(logical_model)
        inputs: list[dict[str, str]] = []
        for data, mime_type in images:
            inputs.append({"type": "image", "data": base64.b64encode(data).decode("ascii"), "mime_type": mime_type})
        for data, mime_type in videos:
            inputs.append({"type": "video", "data": base64.b64encode(data).decode("ascii"), "mime_type": mime_type})
        reference_tags = " ".join(
            [*(f"<IMAGE_REF_{index}>" for index in range(len(images))), *(f"<VIDEO_REF_{index}>" for index in range(len(videos)))]
        )
        role_instruction = (
            f"[# References {reference_tags}] " if reference_tags else ""
        ) + (
            "Use the image references as the character identity and appearance source. " if images else ""
        ) + (
            "Use the video reference as motion, timing, expression, and performance guidance; do not copy its person's identity. " if videos else ""
        )
        rendered_prompt = (
            f"{role_instruction}{prompt.strip()}\n\n"
            "Preserve the referenced character's face, body proportions, hair, distinctive anatomy, accessories, outfit, palette, and rendering style in every frame. "
            "Exactly one depiction of the character. Single continuous shot, no scene cuts, no identity drift, morphing, duplicate body, extra limbs, text, labels, or contact-sheet layout."
        )
        inputs.append({"type": "text", "text": rendered_prompt})
        response = self.client.interactions.create(
            model=exact_model,
            input=inputs,
            response_format={"type": "video", "aspect_ratio": aspect_ratio, "resolution": resolution},
            generation_config={"video_config": {"task": "reference_to_video" if images or videos else "text_to_video"}},
            store=False,
            timeout=900,
        )
        generated: list[GeneratedBinary] = []
        provider_request_id = str(
            getattr(response, "id", "")
            or _request_id(request_hash(logical_model, {"prompt": rendered_prompt}))
        )

        def append_video_output(output: Any) -> None:
            data = getattr(output, "data", None)
            if not data:
                return
            generated.append(GeneratedBinary(
                base64.b64decode(data),
                getattr(output, "mime_type", None) or "video/mp4",
                exact_model,
                provider_request_id,
            ))

        top_level_video = getattr(response, "output_video", None)
        if top_level_video is not None:
            append_video_output(top_level_video)
        for output in getattr(response, "outputs", None) or []:
            if getattr(output, "type", None) == "video":
                append_video_output(output)
        if not generated:
            for step in getattr(response, "steps", None) or []:
                for content in getattr(step, "content", None) or []:
                    if getattr(content, "type", None) == "video":
                        append_video_output(content)
        if not generated:
            raw_response = response.model_dump(exclude_none=True) if hasattr(response, "model_dump") else {
                "response_type": type(response).__name__,
                "output_types": [type(item).__name__ for item in (getattr(response, "outputs", None) or [])],
            }

            def redact_large_values(value: Any, key: str = "") -> Any:
                if key.lower() in {"data", "input", "inline_data"}:
                    return "<redacted>"
                if isinstance(value, dict):
                    return {item_key: redact_large_values(item_value, str(item_key)) for item_key, item_value in value.items()}
                if isinstance(value, list):
                    return [redact_large_values(item) for item in value]
                if isinstance(value, str) and len(value) > 500:
                    return f"<string:{len(value)} chars>"
                return value

            response_summary = json.dumps(redact_large_values(raw_response), ensure_ascii=False, default=str)[:6000]
            raise GoogleProviderError(f"Gemini Omni provider returned no inline video output: {response_summary}")
        return generated

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
        reference_images: list[tuple[bytes, str]] | None = None,
        resolution: str = "720p",
    ) -> ProviderSubmission:
        references = (reference_images or [])[:3]
        if self.config.api_key and (image_data is not None or references or resolution in {"1080p", "4k"}):
            duration_seconds = 8
        if duration_seconds not in {4, 6, 8}:
            raise GoogleProviderError("Veo shot duration must be 4, 6, or 8 seconds")
        if not 1 <= candidate_count <= 4:
            raise GoogleProviderError("Veo candidate_count must be between 1 and 4")
        exact_model = self.exact_model(logical_model)
        payload = {"model": exact_model, "prompt": prompt, "duration_seconds": duration_seconds, "candidate_count": candidate_count, "aspect_ratio": aspect_ratio, "seed": seed, "output_gcs_uri": output_gcs_uri, "has_image": image_data is not None, "reference_hashes": [hashlib.sha256(data).hexdigest() for data, _ in references], "resolution": resolution}
        digest = request_hash(logical_model, payload)
        config_values: dict[str, Any] = {
            "duration_seconds": duration_seconds,
            "number_of_videos": candidate_count,
            "aspect_ratio": aspect_ratio,
            "seed": seed,
            "resolution": resolution,
        }
        if not self.config.api_key:
            config_values.update(generate_audio=True, enhance_prompt=True, output_gcs_uri=output_gcs_uri)
        if references:
            config_values["reference_images"] = [
                types.VideoGenerationReferenceImage(
                    image=types.Image(image_bytes=data, mime_type=mime_type),
                    reference_type=types.VideoGenerationReferenceType.ASSET,
                )
                for data, mime_type in references
            ]
        operation = self.client.models.generate_videos(
            model=exact_model,
            source=types.GenerateVideosSource(
                prompt=prompt,
                image=types.Image(image_bytes=image_data, mime_type=image_mime_type) if image_data and not references else None,
            ),
            config=types.GenerateVideosConfig(**config_values),
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
                data = self._download_gcs(video.uri) if video.uri.startswith("gs://") else self.client.files.download(file=video)
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
        return storage.Client(
            project=google_project_from_env() or None,
            credentials=google_credentials_from_env(),
        ).bucket(bucket_name).blob(blob_name).download_as_bytes()


class GoogleTtsProvider(GoogleProviderBase):
    def __init__(self, config: GoogleProviderConfig | None = None, client: Any | None = None) -> None:
        super().__init__(config, client)
        self._preview_client = self.client
        if client is None and self.config.project and self.config.api_version != "v1beta1":
            self._preview_client = genai.Client(
                vertexai=True,
                project=self.config.project,
                location="global",
                credentials=self.config.credentials,
                http_options=types.HttpOptions(api_version="v1beta1"),
            )

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
        client = self._preview_client if exact_model == "gemini-3.1-flash-tts-preview" else self.client
        response = client.models.generate_content(
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
