from __future__ import annotations

import json
import math
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
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


SPEECH_SYNC_CHUNK_MS = 50_000
SUBTITLE_MAX_CHARS = 28
SUBTITLE_MAX_DURATION_MS = 6_000


@dataclass(frozen=True)
class AudioRecognitionChunk:
    data: bytes
    offset_ms: int
    duration_ms: int


def _split_audio_for_sync_recognition(audio: bytes, duration_ms: int) -> list[AudioRecognitionChunk]:
    if duration_ms <= SPEECH_SYNC_CHUNK_MS:
        return [AudioRecognitionChunk(audio, 0, duration_ms)]
    with tempfile.TemporaryDirectory(prefix="frameflow-speech-chunks-") as temp_dir:
        directory = Path(temp_dir)
        source = directory / "source.audio"
        source.write_bytes(audio)
        chunks: list[AudioRecognitionChunk] = []
        for index in range(math.ceil(duration_ms / SPEECH_SYNC_CHUNK_MS)):
            offset_ms = index * SPEECH_SYNC_CHUNK_MS
            chunk_duration_ms = min(SPEECH_SYNC_CHUNK_MS, duration_ms - offset_ms)
            output = directory / f"chunk-{index:03d}.flac"
            command = [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-i", str(source), "-ss", f"{offset_ms / 1000:.3f}",
                "-t", f"{chunk_duration_ms / 1000:.3f}", "-vn", "-ac", "1", "-ar", "16000",
                "-c:a", "flac", str(output),
            ]
            try:
                subprocess.run(command, check=True, capture_output=True, text=True, timeout=180)
            except FileNotFoundError as exc:
                raise RuntimeError("ffmpeg is required to chunk long Speech-to-Text audio") from exc
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
                detail = (getattr(exc, "stderr", "") or str(exc))[-1600:]
                raise RuntimeError(f"Speech-to-Text audio chunking failed: {detail}") from exc
            chunks.append(AudioRecognitionChunk(output.read_bytes(), offset_ms, chunk_duration_ms))
        return chunks


def _duration_ms(value: Any) -> int:
    if value is None:
        return 0
    if hasattr(value, "total_seconds"):
        return round(value.total_seconds() * 1000)
    seconds = int(getattr(value, "seconds", 0) or 0)
    nanos = int(getattr(value, "nanos", 0) or 0)
    return seconds * 1000 + round(nanos / 1_000_000)


def _caption_segments_from_words(
    words: list[Any],
    fallback_text: str,
    duration_ms: int,
    *,
    fallback_start_ms: int = 0,
) -> list[tuple[int, int, str]]:
    timed_words = [
        (
            _duration_ms(getattr(word, "start_offset", None)),
            _duration_ms(getattr(word, "end_offset", None)),
            str(getattr(word, "word", "") or "").strip(),
        )
        for word in words
        if str(getattr(word, "word", "") or "").strip()
    ]
    if not timed_words:
        tokens = [token for token in fallback_text.split() if token]
        if not tokens:
            return []
        token_duration = max(1, duration_ms // len(tokens))
        timed_words = [
            (
                fallback_start_ms + index * token_duration,
                fallback_start_ms + (duration_ms if index == len(tokens) - 1 else (index + 1) * token_duration),
                token,
            )
            for index, token in enumerate(tokens)
        ]

    segments: list[tuple[int, int, str]] = []
    current: list[str] = []
    start_ms = timed_words[0][0]
    end_ms = start_ms
    for index, (word_start, word_end, word_text) in enumerate(timed_words):
        if not current:
            start_ms = word_start
        current.append(word_text)
        end_ms = max(word_end, word_start + 1)
        text = " ".join(current)
        compact_length = len(re.sub(r"\s+", "", text))
        terminal = bool(re.search(r"[.!?。！？][\"'’”)]?$", word_text))
        should_break = (
            compact_length >= SUBTITLE_MAX_CHARS
            or end_ms - start_ms >= SUBTITLE_MAX_DURATION_MS
            or terminal
        )
        if should_break or index == len(timed_words) - 1:
            segments.append((start_ms, end_ms, text))
            current = []
    return segments


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
        segments: list[SpeechSegment] = []
        detected_language = language_code if language_code != "auto" else "und"
        for chunk in _split_audio_for_sync_recognition(audio, duration_ms):
            config = cloud_speech.RecognitionConfig(
                auto_decoding_config=cloud_speech.AutoDetectDecodingConfig(),
                language_codes=[language_code or "auto"],
                model="chirp_3",
                features=cloud_speech.RecognitionFeatures(enable_word_time_offsets=True),
            )
            request = cloud_speech.RecognizeRequest(
                recognizer=f"projects/{self.project}/locations/{self.location}/recognizers/_",
                config=config,
                content=chunk.data,
            )
            response = self.client.recognize(request=request)
            raw_results = [result for result in response.results if result.alternatives]
            cursor = 0
            fallback_duration = max(1, chunk.duration_ms // max(1, len(raw_results)))
            for result in raw_results:
                alternative = result.alternatives[0]
                text = alternative.transcript.strip()
                if not text:
                    continue
                words = list(alternative.words or [])
                caption_segments = _caption_segments_from_words(
                    words,
                    text,
                    fallback_duration,
                    fallback_start_ms=cursor,
                )
                for start_in_chunk, end_in_chunk, caption_text in caption_segments:
                    if end_in_chunk <= start_in_chunk:
                        end_in_chunk = min(chunk.duration_ms, start_in_chunk + fallback_duration)
                    segments.append(SpeechSegment(
                        index=len(segments),
                        start_ms=chunk.offset_ms + start_in_chunk,
                        end_ms=chunk.offset_ms + end_in_chunk,
                        text=caption_text,
                    ))
                    cursor = end_in_chunk
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
