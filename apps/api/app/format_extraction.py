from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from typing import Any

from google.genai import types

from .domain import FormatProfilePayload
from .providers import MODEL_REGISTRY
from .providers_google import GoogleProviderConfig, GoogleProviderError, GoogleTextProvider


@dataclass(frozen=True)
class FormatSource:
    reference_id: str
    title: str
    creator: str
    duration_ms: int
    proxy_video: bytes
    content_type: str = "video/mp4"


@dataclass(frozen=True)
class ExtractedFormat:
    profile: FormatProfilePayload
    provider_request_id: str
    exact_model_id: str


FORMAT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "duration": {"type": "object", "properties": {"target_ms": {"type": "integer"}}, "required": ["target_ms"]},
        "narrative": {"type": "object", "properties": {"beats": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "role": {"type": "string", "enum": ["hook", "context", "escalation", "payoff"]},
                "start_ratio": {"type": "number"}, "end_ratio": {"type": "number"}, "pattern": {"type": "string"},
            },
            "required": ["role", "start_ratio", "end_ratio"],
        }}}, "required": ["beats"]},
        "editing": {"type": "object", "properties": {
            "median_shot_duration_ms": {"type": "integer"}, "cuts_per_10_seconds": {"type": "number"}, "transition_policy": {"type": "string"},
        }, "required": ["median_shot_duration_ms", "cuts_per_10_seconds", "transition_policy"]},
        "captions": {"type": "object", "properties": {
            "position": {"type": "string"}, "max_lines": {"type": "integer"}, "max_chars_per_line": {"type": "integer"}, "words_per_chunk": {"type": "integer"},
        }, "required": ["position", "max_lines", "max_chars_per_line", "words_per_chunk"]},
        "voice": {"type": "object", "properties": {"tone": {"type": "string"}, "pace_syllables_per_second": {"type": "number"}}, "required": ["tone", "pace_syllables_per_second"]},
        "music": {"type": "object", "properties": {"bpm_range": {"type": "array", "items": {"type": "integer"}}, "ducking_under_voice_db": {"type": "number"}}, "required": ["bpm_range", "ducking_under_voice_db"]},
        "visual": {"type": "object", "properties": {"motion_intensity": {"type": "number"}, "preferred_shot_types": {"type": "array", "items": {"type": "string"}}}, "required": ["motion_intensity", "preferred_shot_types"]},
        "constraints": {"type": "object"},
        "extensions": {"type": "object"},
    },
    "required": ["duration", "narrative", "editing", "captions", "voice", "music", "visual", "extensions"],
}


class GeminiFormatExtractor:
    def __init__(self, provider: GoogleTextProvider | None = None) -> None:
        self.provider = provider or GoogleTextProvider(GoogleProviderConfig.from_env())

    def extract(self, sources: list[FormatSource]) -> ExtractedFormat:
        if not sources:
            raise ValueError("at least one Reference is required for format extraction")
        logical_model = "google.text.quality"
        exact_model = MODEL_REGISTRY[logical_model]
        source_metadata = [
            {"reference_id": item.reference_id, "title": item.title, "creator": item.creator, "duration_ms": item.duration_ms}
            for item in sources
        ]
        prompt = (
            "Analyze the attached short-form reference videos as abstract production formats, not as reusable source content. "
            "Return a consensus format profile describing timing, narrative beats, edit rhythm, captions, voice, music, and visual style. "
            "Ratios must be ordered, non-overlapping, and between 0 and 1. motion_intensity must be between 0 and 1. "
            f"Reference metadata: {json.dumps(source_metadata, ensure_ascii=False)}"
        )
        contents: list[Any] = [prompt]
        for source in sources:
            contents.append(types.Part.from_bytes(data=source.proxy_video, mime_type=source.content_type))
        response = self.provider.client.models.generate_content(
            model=exact_model,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction="You are a video format analyst. Output only the requested structured data and never copy dialogue or distinctive creative content from references.",
                response_mime_type="application/json",
                response_json_schema=FORMAT_SCHEMA,
                temperature=0.2,
            ),
        )
        if not response.text:
            raise GoogleProviderError("Gemini format extraction returned no structured content")
        try:
            extracted = json.loads(response.text)
            extracted["duration"]["target_ms"] = max(1, int(extracted["duration"]["target_ms"]))
            extracted["visual"]["motion_intensity"] = min(1, max(0, float(extracted["visual"]["motion_intensity"])))
            profile = FormatProfilePayload.model_validate({
                "schema_version": "format.profile.v1",
                "core": {"schema_version": "format.core.v1", **{key: value for key, value in extracted.items() if key != "extensions"}},
                "extensions": extracted.get("extensions") or {},
                "evidence": {},
            })
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise GoogleProviderError(f"Gemini format extraction returned an invalid profile: {exc}") from exc
        digest = hashlib.sha256(response.text.encode()).hexdigest()
        return ExtractedFormat(profile, f"google_{digest[:20]}", exact_model)


class FixtureFormatExtractor:
    def extract(self, sources: list[FormatSource]) -> ExtractedFormat:
        reference_ids = [source.reference_id for source in sources]
        evidence = {"editing.median_shot_duration_ms": {"value": 2200, "confidence": 0.91, "evidence": [{"reference_id": reference_ids[0], "start_ms": 0, "end_ms": 1000, "artifact_id": "fixture"}]}}
        profile = FormatProfilePayload.model_validate({"core": {"duration": {"target_ms": 38_000}, "narrative": {"beats": [{"role": "hook", "start_ratio": 0, "end_ratio": 0.08, "pattern": "contradiction"}, {"role": "context", "start_ratio": 0.08, "end_ratio": 0.30}, {"role": "escalation", "start_ratio": 0.30, "end_ratio": 0.76}, {"role": "payoff", "start_ratio": 0.76, "end_ratio": 0.95}]}, "editing": {"median_shot_duration_ms": 2200, "cuts_per_10_seconds": 4.4, "transition_policy": "mostly_hard_cut"}, "captions": {"position": "center_lower", "max_lines": 2, "max_chars_per_line": 12, "words_per_chunk": 4}, "voice": {"tone": "confident_explanatory", "pace_syllables_per_second": 4.7}, "music": {"bpm_range": [110, 120], "ducking_under_voice_db": -8}, "visual": {"motion_intensity": 0.65, "preferred_shot_types": ["close_up", "medium", "detail"]}}, "extensions": {}, "evidence": evidence})
        return ExtractedFormat(profile, "fixture_format", "fixture")


def get_format_extractor():
    mode = os.getenv("FORMAT_PROVIDER_MODE", "live").strip().lower()
    if mode == "live":
        return GeminiFormatExtractor()
    if mode == "fixture":
        if os.getenv("APP_ENV") != "test":
            raise ValueError("FORMAT_PROVIDER_MODE=fixture is only allowed when APP_ENV=test")
        return FixtureFormatExtractor()
    raise ValueError("FORMAT_PROVIDER_MODE must be live or fixture")
