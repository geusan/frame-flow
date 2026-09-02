from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Protocol

from .google_service_account import google_credentials_from_env, google_project_from_env
from .providers_google import GoogleProviderConfig, GoogleTextProvider, GoogleTtsProvider


@dataclass(frozen=True)
class SpeechSegment:
    index: int
    start_ms: int
    end_ms: int
    text: str


@dataclass(frozen=True)
class TranscriptResult:
    language_code: str
    segments: list[SpeechSegment]

    @property
    def text(self) -> str:
        return " ".join(segment.text for segment in self.segments).strip()


@dataclass(frozen=True)
class TranslationResult:
    segments: list[SpeechSegment]
    provider_request_id: str

    @property
    def text(self) -> str:
        return " ".join(segment.text for segment in self.segments).strip()


@dataclass(frozen=True)
class SynthesizedSpeech:
    data: bytes
    mime_type: str
    provider_request_id: str


class SpeechRecognizer(Protocol):
    def transcribe(self, audio: bytes, *, language_code: str, duration_ms: int) -> TranscriptResult: ...


class SegmentTranslator(Protocol):
    def translate(self, transcript: TranscriptResult, *, target_language: str) -> TranslationResult: ...


class SpeechSynthesizer(Protocol):
    def synthesize(self, text: str, *, language_code: str, voice_name: str) -> SynthesizedSpeech: ...


@dataclass(frozen=True)
class LocalizationServices:
    recognizer: SpeechRecognizer
    translator: SegmentTranslator
    synthesizer: SpeechSynthesizer


def _duration_ms(value: Any) -> int:
    if value is None:
        return 0
    if hasattr(value, "total_seconds"):
        return round(value.total_seconds() * 1000)
    seconds = int(getattr(value, "seconds", 0) or 0)
    nanos = int(getattr(value, "nanos", 0) or 0)
    return seconds * 1000 + round(nanos / 1_000_000)


class GoogleChirp3Recognizer:
    def __init__(self, project: str, location: str = "us", client: Any | None = None) -> None:
        if not project:
            raise RuntimeError("GOOGLE_CLOUD_PROJECT is required for Chirp 3 speech recognition")
        if location == "global":
            raise RuntimeError("Chirp 3 is not available in global; set GOOGLE_SPEECH_LOCATION to a supported region such as us")
        self.project = project
        self.location = location
        if client is not None:
            self.client = client
            return
        try:
            from google.api_core.client_options import ClientOptions
            from google.cloud.speech_v2 import SpeechClient
        except ImportError as exc:
            raise RuntimeError("google-cloud-speech is required for Chirp 3 speech recognition") from exc
        credentials = google_credentials_from_env()
        if credentials is None:
            raise RuntimeError("Google Service Account JSON is required for Chirp 3 speech recognition")
        options = None if location == "global" else ClientOptions(api_endpoint=f"{location}-speech.googleapis.com")
        self.client = SpeechClient(
            client_options=options,
            credentials=credentials,
        )

    def transcribe(self, audio: bytes, *, language_code: str, duration_ms: int) -> TranscriptResult:
        try:
            from google.cloud.speech_v2.types import cloud_speech
        except ImportError as exc:
            raise RuntimeError("google-cloud-speech is required for Chirp 3 speech recognition") from exc
        config = cloud_speech.RecognitionConfig(
            auto_decoding_config=cloud_speech.AutoDetectDecodingConfig(),
            language_codes=[language_code or "auto"],
            model="chirp_3",
            features=cloud_speech.RecognitionFeatures(enable_word_time_offsets=True),
        )
        request = cloud_speech.RecognizeRequest(
            recognizer=f"projects/{self.project}/locations/{self.location}/recognizers/_",
            config=config,
            content=audio,
        )
        response = self.client.recognize(request=request)
        raw_results = [result for result in response.results if result.alternatives]
        if not raw_results:
            raise RuntimeError("Chirp 3 returned no transcript")
        segments: list[SpeechSegment] = []
        cursor = 0
        fallback_duration = max(1, duration_ms // len(raw_results))
        detected_language = language_code if language_code != "auto" else "und"
        for index, result in enumerate(raw_results):
            alternative = result.alternatives[0]
            text = alternative.transcript.strip()
            if not text:
                continue
            words = list(alternative.words or [])
            start_ms = _duration_ms(words[0].start_offset) if words else cursor
            end_ms = _duration_ms(words[-1].end_offset) if words else min(duration_ms, start_ms + fallback_duration)
            if end_ms <= start_ms:
                end_ms = min(duration_ms, start_ms + fallback_duration)
            segments.append(SpeechSegment(index=len(segments), start_ms=start_ms, end_ms=end_ms, text=text))
            cursor = end_ms
            result_language = str(getattr(result, "language_code", "") or "")
            if result_language:
                detected_language = result_language
        if not segments:
            raise RuntimeError("Chirp 3 returned an empty transcript")
        return TranscriptResult(detected_language, segments)


class GeminiSegmentTranslator:
    def __init__(self, provider: GoogleTextProvider | None = None, logical_model: str = "google.text.quality") -> None:
        self.provider = provider or GoogleTextProvider()
        self.logical_model = logical_model

    def translate(self, transcript: TranscriptResult, *, target_language: str) -> TranslationResult:
        schema = {
            "type": "object",
            "properties": {
                "segments": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "index": {"type": "integer"},
                            "text": {"type": "string"},
                        },
                        "required": ["index", "text"],
                    },
                },
            },
            "required": ["segments"],
        }
        source = [{"index": segment.index, "text": segment.text} for segment in transcript.segments]
        translated, request_id = self.provider.generate_structured(
            logical_model=self.logical_model,
            system_prompt=(
                "You are a professional audiovisual translator. Translate every segment naturally for dubbing. "
                "Preserve the exact segment count and index values, do not omit information, and keep each segment concise enough for its original speaking window."
            ),
            rendered_prompt=json.dumps({
                "source_language": transcript.language_code,
                "target_language": target_language,
                "segments": source,
            }, ensure_ascii=False),
            output_json_schema=schema,
            temperature=0.1,
        )
        rows = translated.get("segments")
        if not isinstance(rows, list):
            raise RuntimeError("Gemini translation response did not contain segments")
        by_index = {int(row["index"]): str(row["text"]).strip() for row in rows if isinstance(row, dict) and "index" in row and "text" in row}
        expected = {segment.index for segment in transcript.segments}
        if set(by_index) != expected or any(not by_index[index] for index in expected):
            raise RuntimeError("Gemini translation did not preserve every transcript segment")
        segments = [
            SpeechSegment(segment.index, segment.start_ms, segment.end_ms, by_index[segment.index])
            for segment in transcript.segments
        ]
        return TranslationResult(segments, request_id)


class GeminiSpeechSynthesizer:
    def __init__(self, provider: GoogleTtsProvider | None = None) -> None:
        self.provider = provider or GoogleTtsProvider()

    def synthesize(self, text: str, *, language_code: str, voice_name: str) -> SynthesizedSpeech:
        generated = self.provider.synthesize(
            text=text,
            style_prompt="Read the translated narration naturally, clearly, and at a concise documentary pace.",
            voice_name=voice_name,
            locale=language_code,
        )
        return SynthesizedSpeech(generated.data, generated.mime_type, generated.provider_request_id)


def get_speech_recognizer() -> SpeechRecognizer:
    project = google_project_from_env()
    if not project:
        raise RuntimeError("GOOGLE_CLOUD_PROJECT is required for Chirp 3 Speech-to-Text")
    speech_location = os.getenv("GOOGLE_SPEECH_LOCATION", "us").strip() or "us"
    return GoogleChirp3Recognizer(project, speech_location)


def get_localization_services() -> LocalizationServices:
    generation_config = GoogleProviderConfig.from_env()
    return LocalizationServices(
        recognizer=get_speech_recognizer(),
        translator=GeminiSegmentTranslator(GoogleTextProvider(generation_config)),
        synthesizer=GeminiSpeechSynthesizer(GoogleTtsProvider(generation_config)),
    )
