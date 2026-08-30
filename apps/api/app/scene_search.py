from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from google.genai import types

from .providers import ALL_MODEL_REGISTRY
from .providers_google import GoogleProviderConfig, GoogleProviderError, GoogleTextProvider
from .providers_openai import OpenAIGenerationServices, OpenAIProviderConfig


class SceneSearchError(RuntimeError):
    pass


@dataclass(frozen=True)
class SampledFrame:
    index: int
    timestamp_ms: int
    content: bytes
    content_type: str = "image/jpeg"


@dataclass(frozen=True)
class RankedScene:
    frame: SampledFrame
    score: float
    reason: str


@dataclass(frozen=True)
class SceneSearchResult:
    scenes: tuple[RankedScene, ...]
    provider: str
    model_alias: str
    exact_model_id: str
    provider_request_id: str
    source_duration_ms: int


class SceneRanker(Protocol):
    provider_name: str

    def rank(self, prompt: str, frames: list[SampledFrame], candidate_count: int, model_alias: str) -> SceneSearchResult: ...


SCENE_SEARCH_MODELS: dict[str, tuple[str, ...]] = {
    "google": tuple(alias for alias in ALL_MODEL_REGISTRY if alias.startswith("google.text.")),
    "openai": ("openai.text.fast", "openai.text.quality", "openai.chat.latest"),
}

SCENE_SEARCH_DEFAULT_MODELS = {
    "google": "google.text.fast",
    "openai": "openai.chat.latest",
}


def resolve_scene_search_model(provider: str, model_alias: str | None) -> tuple[str, str]:
    normalized_provider = provider.strip().lower()
    if normalized_provider not in SCENE_SEARCH_MODELS:
        raise SceneSearchError(f"unsupported scene search provider: {provider}")
    normalized_alias = (model_alias or SCENE_SEARCH_DEFAULT_MODELS[normalized_provider]).strip().lower()
    if normalized_alias not in SCENE_SEARCH_MODELS[normalized_provider]:
        allowed = ", ".join(SCENE_SEARCH_MODELS[normalized_provider])
        raise SceneSearchError(
            f"scene search model {normalized_alias} is not available for {normalized_provider} (allowed: {allowed})"
        )
    return normalized_alias, ALL_MODEL_REGISTRY[normalized_alias]


class GoogleSceneRanker:
    provider_name = "google"

    def __init__(self, provider: GoogleTextProvider | None = None) -> None:
        self.provider = provider or GoogleTextProvider(GoogleProviderConfig.from_env())

    def rank(self, prompt: str, frames: list[SampledFrame], candidate_count: int, model_alias: str) -> SceneSearchResult:
        logical_model, exact_model = resolve_scene_search_model(self.provider_name, model_alias)
        frame_index = [{"index": frame.index, "timestamp_ms": frame.timestamp_ms} for frame in frames]
        contents: list[Any] = [
            "Rank the attached video frames by visual relevance to the user's scene-search prompt. "
            "Use only visible evidence. Return unique frame indices, a 0..1 relevance score, and a concise reason. "
            f"Prompt: {prompt}\nFrames: {json.dumps(frame_index)}"
        ]
        for frame in frames:
            contents.append(f"Frame index {frame.index} at {frame.timestamp_ms}ms")
            contents.append(types.Part.from_bytes(data=frame.content, mime_type=frame.content_type))
        schema = _ranking_schema()
        try:
            response = self.provider.client.models.generate_content(
                model=exact_model,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction="You are a visual scene retrieval ranker. Do not infer details that are not visible.",
                    response_mime_type="application/json",
                    response_json_schema=schema,
                    temperature=0.1,
                ),
            )
        except GoogleProviderError:
            raise
        except Exception as exc:
            raise SceneSearchError(f"Google scene ranking failed: {exc}") from exc
        if not response.text:
            raise SceneSearchError("Google scene ranking returned no result")
        try:
            payload = json.loads(response.text)
        except json.JSONDecodeError as exc:
            raise SceneSearchError("Google scene ranking returned invalid JSON") from exc
        ranked = _ranked_scenes(payload, frames)
        if not ranked:
            raise SceneSearchError("Google scene ranking did not select a valid frame")
        digest = hashlib.sha256(
            json.dumps({"prompt": prompt, "frames": frame_index}, sort_keys=True).encode()
        ).hexdigest()
        return SceneSearchResult(
            tuple(ranked[:candidate_count]),
            self.provider_name,
            logical_model,
            exact_model,
            f"google_{digest[:20]}",
            0,
        )


class OpenAISceneRanker:
    provider_name = "openai"

    def __init__(self, service: OpenAIGenerationServices | None = None) -> None:
        self.service = service or OpenAIGenerationServices(OpenAIProviderConfig.from_env())

    def rank(self, prompt: str, frames: list[SampledFrame], candidate_count: int, model_alias: str) -> SceneSearchResult:
        logical_model, exact_model = resolve_scene_search_model(self.provider_name, model_alias)
        frame_index = [{"index": frame.index, "timestamp_ms": frame.timestamp_ms} for frame in frames]
        content: list[dict[str, Any]] = [{
            "type": "input_text",
            "text": (
                "Rank these video frames by visual relevance to the scene-search prompt. "
                "Use only visible evidence and return unique indices. "
                f"Prompt: {prompt}. Frame metadata: {json.dumps(frame_index)}"
            ),
        }]
        for frame in frames:
            content.append({"type": "input_text", "text": f"Frame index {frame.index} at {frame.timestamp_ms}ms"})
            encoded = base64.b64encode(frame.content).decode()
            content.append({
                "type": "input_image",
                "detail": "low",
                "image_url": f"data:{frame.content_type};base64,{encoded}",
            })
        schema = _ranking_schema()
        try:
            response = self.service.client.responses.create(
                model=exact_model,
                instructions="You are a visual scene retrieval ranker. Do not infer details that are not visible.",
                input=[{"role": "user", "content": content}],
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "scene_rankings",
                        "schema": schema,
                        "strict": True,
                    },
                },
                store=False,
            )
        except Exception as exc:
            raise SceneSearchError(f"OpenAI scene ranking failed: {exc}") from exc
        if not response.output_text:
            raise SceneSearchError("OpenAI scene ranking returned no result")
        try:
            payload = json.loads(response.output_text)
        except json.JSONDecodeError as exc:
            raise SceneSearchError("OpenAI scene ranking returned invalid JSON") from exc
        ranked = _ranked_scenes(payload, frames)
        if not ranked:
            raise SceneSearchError("OpenAI scene ranking did not select a valid frame")
        return SceneSearchResult(
            tuple(ranked[:candidate_count]),
            self.provider_name,
            logical_model,
            exact_model,
            str(response.id),
            0,
        )


class FixtureSceneRanker:
    def __init__(self, requested_provider: str) -> None:
        self.provider_name = requested_provider

    def rank(self, prompt: str, frames: list[SampledFrame], candidate_count: int, model_alias: str) -> SceneSearchResult:
        logical_model, exact_model = resolve_scene_search_model(self.provider_name, model_alias)
        ranked = []
        for frame in frames:
            digest = hashlib.sha256(f"{prompt}:{frame.timestamp_ms}".encode()).digest()
            score = 0.45 + int.from_bytes(digest[:2], "big") / 65535 * 0.54
            ranked.append(RankedScene(frame, round(score, 3), f"Fixture visual match at {frame.timestamp_ms / 1000:.1f}s"))
        ranked.sort(key=lambda item: (-item.score, item.frame.timestamp_ms))
        request_hash = hashlib.sha256(f"fixture:{prompt}".encode()).hexdigest()
        return SceneSearchResult(
            tuple(ranked[:candidate_count]),
            self.provider_name,
            logical_model,
            exact_model,
            f"fixture_{request_hash[:20]}",
            0,
        )


def search_video_scenes(
    video: bytes,
    content_type: str,
    prompt: str,
    *,
    candidate_count: int = 4,
    sample_count: int = 12,
    provider: str = "google",
    model_alias: str | None = None,
) -> SceneSearchResult:
    if not prompt.strip():
        raise SceneSearchError("scene search prompt cannot be empty")
    frames, duration_ms = sample_video_frames(video, content_type, sample_count=sample_count)
    logical_model, _ = resolve_scene_search_model(provider, model_alias)
    ranker = get_scene_ranker(provider)
    ranked = ranker.rank(prompt.strip(), frames, candidate_count, logical_model)
    return SceneSearchResult(
        ranked.scenes,
        ranked.provider,
        ranked.model_alias,
        ranked.exact_model_id,
        ranked.provider_request_id,
        duration_ms,
    )


def get_scene_ranker(provider: str) -> SceneRanker:
    normalized_provider = provider.strip().lower()
    resolve_scene_search_model(normalized_provider, None)
    mode = os.getenv("SCENE_SEARCH_PROVIDER_MODE", "live").strip().lower()
    if mode == "live":
        if normalized_provider == "google":
            try:
                return GoogleSceneRanker()
            except GoogleProviderError as exc:
                raise SceneSearchError(str(exc)) from exc
        if normalized_provider == "openai":
            try:
                return OpenAISceneRanker()
            except RuntimeError as exc:
                raise SceneSearchError(str(exc)) from exc
    if mode == "fixture":
        if os.getenv("APP_ENV") != "test":
            raise SceneSearchError("SCENE_SEARCH_PROVIDER_MODE=fixture is only allowed when APP_ENV=test")
        return FixtureSceneRanker(normalized_provider)
    raise SceneSearchError("SCENE_SEARCH_PROVIDER_MODE must be live or fixture")


def _ranking_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "rankings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "index": {"type": "integer"},
                        "score": {"type": "number"},
                        "reason": {"type": "string"},
                    },
                    "required": ["index", "score", "reason"],
                },
            },
        },
        "required": ["rankings"],
    }


def _ranked_scenes(payload: dict[str, Any], frames: list[SampledFrame]) -> list[RankedScene]:
    frame_by_index = {frame.index: frame for frame in frames}
    ranked: list[RankedScene] = []
    used: set[int] = set()
    for item in payload.get("rankings") or []:
        index = int(item.get("index", -1))
        if index not in frame_by_index or index in used:
            continue
        used.add(index)
        ranked.append(RankedScene(
            frame_by_index[index],
            min(1, max(0, float(item.get("score") or 0))),
            str(item.get("reason") or "Visual match")[:500],
        ))
    ranked.sort(key=lambda item: item.score, reverse=True)
    return ranked


def sample_video_frames(video: bytes, content_type: str, *, sample_count: int) -> tuple[list[SampledFrame], int]:
    if not video:
        raise SceneSearchError("source video is empty")
    with tempfile.TemporaryDirectory(prefix="frameflow-scene-search-") as temp_dir:
        directory = Path(temp_dir)
        suffix = {
            "video/mp4": ".mp4",
            "video/webm": ".webm",
            "video/quicktime": ".mov",
            "video/mkv": ".mkv",
            "video/x-matroska": ".mkv",
        }.get(content_type.split(";", 1)[0].lower(), ".video")
        source = directory / f"source{suffix}"
        source.write_bytes(video)
        probe = _run([
            "ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(source),
        ], timeout=60)
        try:
            duration_ms = max(1, round(float((json.loads(probe.stdout).get("format") or {}).get("duration") or 0) * 1000))
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise SceneSearchError("could not determine source video duration") from exc
        last_timestamp = max(0, duration_ms - 50)
        if sample_count == 1 or last_timestamp == 0:
            timestamps = [0]
        else:
            timestamps = sorted({round(last_timestamp * index / (sample_count - 1)) for index in range(sample_count)})
        frames: list[SampledFrame] = []
        for index, timestamp_ms in enumerate(timestamps):
            output = directory / f"sample-{index:03d}.jpg"
            _run([
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-ss", f"{timestamp_ms / 1000:.3f}", "-i", str(source),
                "-map", "0:v:0", "-frames:v", "1",
                "-vf", "scale=480:-2:force_original_aspect_ratio=decrease",
                "-q:v", "4", str(output),
            ], timeout=90)
            if output.exists() and output.stat().st_size:
                frames.append(SampledFrame(index, timestamp_ms, output.read_bytes()))
        if not frames:
            raise SceneSearchError("scene sampling did not produce any frames")
        return frames, duration_ms


def _run(command: list[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(command, check=True, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise SceneSearchError(f"required media tool is not installed: {command[0]}") from exc
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        detail = (getattr(exc, "stderr", "") or str(exc))[-1200:]
        raise SceneSearchError(f"scene sampling failed: {detail}") from exc
