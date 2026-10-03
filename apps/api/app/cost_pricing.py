"""Versioned public rates. Calculated list-price costs are never invoice amounts."""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

CATALOG_VERSION = "public-rates.2026-10-02"
VALID_UNTIL = date(2026, 11, 1)
OPENAI_SOURCE = "https://developers.openai.com/api/docs/pricing"
GOOGLE_SOURCE = "https://cloud.google.com/vertex-ai/generative-ai/pricing"

# USD per million tokens; cached and cache-write tokens are separate input buckets.
OPENAI_TEXT = {
    "chat-latest": ("5", "0.5", None, "30"),
    "gpt-5.6-luna": ("0.2", "0.02", "0.25", "1.2"),
    "gpt-5.6-terra": ("2", "0.2", "2.5", "12"),
}
GOOGLE_TEXT = {
    "gemini-3.6-flash": ("0.75", "0.075", "3.75"),
    "gemini-3.5-flash": ("1.5", "0.15", "9"),
    "gemini-3.5-flash-lite": ("0.3", "0.03", "2.5"),
    "gemini-3.1-pro-preview": ("2", "0.2", "12"),
    "gemini-3.1-flash-lite": ("0.25", "0.025", "1.5"),
    "gemini-3.1-flash-image": ("0.5", "0.05", "3"),
    "gemini-3.1-flash-lite-image": ("0.25", "0.025", "1.5"),
    "gemini-3-pro-image": ("2", "0.2", "12"),
}
GOOGLE_IMAGE_OUTPUT = {"gemini-3.1-flash-image": "60", "gemini-3.1-flash-lite-image": "30", "gemini-3-pro-image": "120"}
GOOGLE_TTS = {
    "gemini-2.5-flash-tts": ("0.5", "10"),
    "gemini-2.5-pro-tts": ("1", "20"),
    "gemini-3.1-flash-tts-preview": ("1", "20"),
}


def number(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        value = Decimal(str(value))
        return value if value.is_finite() and value >= 0 else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def calculate(provider: str, model: str, operation: str, usage: dict, context: dict, *, today: date | None = None):
    """Return (amount, reproducible pricing snapshot, unresolved reason)."""
    if (today or date.today()) >= VALID_UNTIL:
        return None, {}, "pricing_catalog_expired"
    # Never guess a dated snapshot's tariff from a model-name prefix.
    parts: list[dict[str, str]] = []
    source = OPENAI_SOURCE if provider == "openai" else GOOGLE_SOURCE

    def add(unit, quantity, rate, divisor="1000000"):
        q, r = number(quantity), number(rate)
        if q is None or r is None:
            raise ValueError("usage_or_rate_missing")
        parts.append({"unit": unit, "quantity": str(q), "unit_price_usd": str(r), "per": divisor,
                      "amount_usd": str(q * r / Decimal(divisor))})

    try:
        if provider in {"openai", "xai"}:
            if context.get("service_tier", "default") not in {"default", "auto", "standard", None}:
                return None, {}, "service_tier_price_unavailable"
            if context.get("custom_endpoint"):
                return None, {}, "custom_endpoint_price_unavailable"
            if provider == "openai" and model == "gpt-image-2" and operation in {"images.generate", "images.edit"}:
                details = usage.get("input_tokens_details") or {}
                if number(details.get("text_tokens")) is None or number(details.get("image_tokens")) is None:
                    return None, {}, "image_token_breakdown_missing"
                add("input_text_tokens", details["text_tokens"], "5")
                add("input_image_tokens", details["image_tokens"], "8")
                add("output_image_tokens", usage.get("output_tokens"), "30")
            elif provider == "openai" and model in OPENAI_TEXT:
                i, c, w, o = OPENAI_TEXT[model]
                count = number(usage.get("input_tokens", usage.get("prompt_tokens")))
                details = usage.get("input_tokens_details", usage.get("prompt_tokens_details")) or {}
                cached = number(details.get("cached_tokens", 0))
                writes = number(details.get("cache_write_tokens", 0))
                if count is None or cached is None or writes is None or cached + writes > count:
                    return None, {}, "input_usage_missing_or_inconsistent"
                if any(number(details.get(k, 0)) for k in ("audio_tokens", "image_tokens")):
                    return None, {}, "modality_price_unavailable"
                if count > 272000:
                    if model == "chat-latest":
                        return None, {}, "long_context_price_unavailable"
                    i, c, w, o = str(Decimal(i)*2), str(Decimal(c)*2), str(Decimal(w)*2), str(Decimal(o)*Decimal("1.5"))
                add("uncached_input_tokens", count-cached-writes, i)
                add("cached_input_tokens", cached, c)
                if writes:
                    add("cache_write_tokens", writes, w)
                add("output_tokens", usage.get("output_tokens", usage.get("completion_tokens")), o)
            elif provider == "openai" and model in {"tts-1", "tts-1-hd"}:
                add("input_characters", usage.get("input_characters"), "15" if model == "tts-1" else "30")
            elif provider == "openai" and model == "whisper-1":
                seconds = number(usage.get("audio_seconds"))
                if seconds is None:
                    return None, {}, "transcription_duration_missing"
                add("reported_audio_seconds", seconds, "0.006", "60")
            else:
                return None, {}, "model_price_unavailable"
        elif provider == "google" and model in GOOGLE_TTS:
            if context.get("channel") != "vertex":
                return None, {}, "endpoint_price_unavailable"
            source = "https://cloud.google.com/text-to-speech/pricing"
            i, o = GOOGLE_TTS[model]
            add("input_text_tokens", usage.get("prompt_token_count"), i)
            add("output_audio_tokens", usage.get("candidates_token_count"), o)
        elif provider == "google" and model in {"veo-3.1-generate-001", "veo-3.1-fast-generate-001"}:
            videos = usage.get("videos") or []
            seconds = number(context.get("duration_seconds"))
            if context.get("channel") != "vertex" or context.get("generate_audio") is not True:
                return None, {}, "video_billing_mode_unverified"
            if not videos or seconds is None or any(abs(Decimal(v["duration_seconds"])-seconds) > Decimal("0.15") for v in videos):
                return None, {}, "generated_video_duration_unverified"
            for video in videos:
                size = min(video["width"], video["height"])
                resolution = "4k" if size >= 2160 else "1080p" if size >= 1080 else "720p" if size >= 720 else None
                if resolution != context.get("resolution"):
                    return None, {}, "generated_video_resolution_unverified"
                rate = {"720p": "0.4", "1080p": "0.4", "4k": "0.6"} if model == "veo-3.1-generate-001" else {"720p": "0.10", "1080p": "0.12", "4k": "0.30"}
                add("generated_video_seconds", seconds, rate[resolution], "1")
        elif provider == "google" and model in GOOGLE_TEXT:
            if context.get("channel") != "vertex":
                return None, {}, "endpoint_price_unavailable"
            count = number(usage.get("prompt_token_count"))
            cached = number(usage.get("cached_content_token_count", 0))
            out = number(usage.get("candidates_token_count"))
            thoughts = number(usage.get("thoughts_token_count", 0))
            if None in (count, cached, out, thoughts) or cached > count:
                return None, {}, "token_usage_missing_or_inconsistent"
            i, c, o = GOOGLE_TEXT[model]
            if count > 200000:
                if model not in {"gemini-3.1-pro-preview", "gemini-3-pro-image"}:
                    return None, {}, "long_context_price_unavailable"
                i, c, o = "4", "0.4", "18"
            multiplier = Decimal("1")
            regional_models = {"gemini-3.6-flash", "gemini-3.5-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-3.1-flash-image"}
            if context.get("location") != "global":
                if model not in regional_models:
                    return None, {}, "regional_price_unavailable"
                multiplier = Decimal("1.1")
            prompt_details = usage.get("prompt_tokens_details") or []
            if any(str(d.get("modality", "")).upper().endswith("AUDIO") and d.get("token_count") for d in prompt_details):
                return None, {}, "audio_input_price_unavailable"
            add("uncached_input_tokens", count-cached, Decimal(i)*multiplier)
            add("cached_input_tokens", cached, Decimal(c)*multiplier)
            if model in GOOGLE_IMAGE_OUTPUT:
                output_details = usage.get("candidates_tokens_details") or []
                image = sum((number(d.get("token_count")) or Decimal(0)) for d in output_details if str(d.get("modality", "")).upper().endswith("IMAGE"))
                if not image or image > out:
                    return None, {}, "image_output_breakdown_missing"
                add("output_image_tokens", image, Decimal(GOOGLE_IMAGE_OUTPUT[model])*multiplier)
                add("output_text_tokens", out-image+thoughts, Decimal(o)*multiplier)
            else:
                add("output_tokens", out+thoughts, Decimal(o)*multiplier)
        else:
            return None, {}, "model_price_unavailable"
    except (ValueError, TypeError):
        return None, {}, "usage_or_rate_missing"
    snapshot = {"version": CATALOG_VERSION, "source": source,
                "retrieved_at": "2026-10-02", "valid_until": VALID_UNTIL.isoformat(), "currency": "USD",
                "basis": "public_list_price", "context": context, "line_items": parts}
    return sum((Decimal(p["amount_usd"]) for p in parts), Decimal(0)), snapshot, None
