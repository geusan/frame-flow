from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...database import ExperimentRunRecord, get_db
from ...domain import ProviderSettingsUpdateRequest
from ...provider_settings import (
    PROVIDER_DEFINITIONS,
    ensure_provider_settings,
    get_provider_record,
    provider_auth_method_key,
    provider_is_configured,
    provider_settings_payload,
    update_provider_settings,
)
from ...providers import (
    FAL_MODEL_REGISTRY,
    LOCAL_SUBSCRIPTION_MODEL_REGISTRY,
    MODEL_REGISTRY,
    OPENAI_MODEL_REGISTRY,
    XAI_MODEL_REGISTRY,
    model_id_for_alias,
)
from ...service import audit


router = APIRouter(tags=["settings"])


@router.get("/settings/providers")
def list_provider_settings(
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    return [
        provider_settings_payload(record) for record in ensure_provider_settings(db)
    ]


@router.put("/settings/providers/{provider}")
def save_provider_settings(
    provider: str,
    payload: ProviderSettingsUpdateRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    normalized_provider = provider.strip().lower()
    if normalized_provider not in PROVIDER_DEFINITIONS:
        raise HTTPException(404, "provider not found")
    record = get_provider_record(db, normalized_provider)
    if not record:
        ensure_provider_settings(db)
        record = get_provider_record(db, normalized_provider)
    if not record:
        raise HTTPException(404, "provider not found")
    try:
        updated = update_provider_settings(
            db,
            record,
            enabled=payload.enabled,
            auth_method=payload.auth_method,
            values=payload.values,
            clear_fields=payload.clear_fields,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    audit(
        db,
        "provider.settings.updated",
        updated.id,
        {
            "provider": normalized_provider,
            "enabled": updated.enabled,
            "auth_method": payload.auth_method,
            "updated_fields": sorted(payload.values),
            "cleared_fields": sorted(payload.clear_fields),
        },
    )
    db.commit()
    return provider_settings_payload(updated)


@router.get("/models")
def list_models(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    usage = {
        str(alias): {
            "usage_count": int(count),
            "recorded_cost_usd": float(cost or 0),
            "last_used_at": last_used_at,
        }
        for alias, count, cost, last_used_at in db.execute(
            select(
                ExperimentRunRecord.model_alias,
                func.count(),
                func.coalesce(func.sum(ExperimentRunRecord.cost_usd), 0.0),
                func.max(ExperimentRunRecord.created_at),
            ).group_by(ExperimentRunRecord.model_alias)
        ).all()
    }
    google_settings = get_provider_record(db, "google")
    google_configuration = (
        dict(google_settings.configuration or {}) if google_settings else {}
    )
    configured = bool(google_settings and provider_is_configured(google_settings))
    google_project = google_configuration.get("project_id") or None
    location = str(google_configuration.get("location") or "us-central1")
    speech_location = str(google_configuration.get("speech_location") or "us")
    rows = [
        {
            "logical_alias": alias,
            "exact_model_id": model_id_for_alias(alias) or model_id,
            "provider": "Google",
            "modality": alias.split(".")[1],
            "region": (
                speech_location
                if ".stt." in alias
                else "global"
                if alias == "google.tts.latest"
                else location
            ),
            "status": "active" if configured else "disabled",
            "configured": configured,
            "configuration": (
                google_project or "Google Service Account is not configured"
            ),
            **usage.get(
                alias,
                {
                    "usage_count": 0,
                    "recorded_cost_usd": 0.0,
                    "last_used_at": None,
                },
            ),
        }
        for alias, model_id in MODEL_REGISTRY.items()
        if alias != "google.video.omni"
    ]
    rows.append(
        {
            "logical_alias": "google.localization.pipeline",
            "exact_model_id": (
                "chirp_3 + gemini-3.1-pro-preview + gemini-2.5-flash-tts"
            ),
            "provider": "Google",
            "modality": "video",
            "region": f"{speech_location} / {location}",
            "status": "active" if configured else "disabled",
            "configured": configured,
            "configuration": (
                google_project or "Google Service Account is not configured"
            ),
            **usage.get(
                "google.localization.pipeline",
                {
                    "usage_count": 0,
                    "recorded_cost_usd": 0.0,
                    "last_used_at": None,
                },
            ),
        }
    )
    openai_settings = get_provider_record(db, "openai")
    openai_auth_method = (
        provider_auth_method_key(openai_settings) if openai_settings else "api_key"
    )
    openai_configured = bool(
        openai_settings
        and openai_auth_method == "api_key"
        and provider_is_configured(openai_settings)
    )
    rows.extend(
        {
            "logical_alias": alias,
            "exact_model_id": model_id,
            "provider": "OpenAI",
            "modality": alias.split(".")[1],
            "region": "OpenAI API",
            "status": "active" if openai_configured else "disabled",
            "configured": openai_configured,
            "configuration": (
                "OPENAI_API_KEY configured"
                if openai_configured
                else "OPENAI_API_KEY is not set"
            ),
            **usage.get(
                alias,
                {
                    "usage_count": 0,
                    "recorded_cost_usd": 0.0,
                    "last_used_at": None,
                },
            ),
        }
        for alias, model_id in OPENAI_MODEL_REGISTRY.items()
    )
    chatgpt_configured = bool(
        openai_settings
        and openai_auth_method == "chatgpt_oauth"
        and provider_is_configured(openai_settings)
    )
    claude_settings = get_provider_record(db, "claude")
    claude_auth_method = (
        provider_auth_method_key(claude_settings) if claude_settings else "api_key"
    )
    claude_configured = bool(
        claude_settings
        and claude_auth_method == "setup_token"
        and provider_is_configured(claude_settings)
    )
    rows.extend(
        {
            "logical_alias": alias,
            "exact_model_id": model_id,
            "provider": (
                "ChatGPT Subscription"
                if alias.startswith("chatgpt.")
                else "Claude Code"
            ),
            "modality": "text",
            "region": (
                "Local Codex CLI"
                if alias.startswith("chatgpt.")
                else "Local Claude Code CLI"
            ),
            "status": (
                "active"
                if (
                    chatgpt_configured
                    if alias.startswith("chatgpt.")
                    else claude_configured
                )
                else "disabled"
            ),
            "configured": (
                chatgpt_configured
                if alias.startswith("chatgpt.")
                else claude_configured
            ),
            "configuration": (
                "Codex ChatGPT login ready"
                if alias.startswith("chatgpt.") and chatgpt_configured
                else "Codex ChatGPT login is not ready"
                if alias.startswith("chatgpt.")
                else "Claude Code setup token ready"
                if claude_configured
                else "Claude Code setup token is not ready"
            ),
            **usage.get(
                alias,
                {
                    "usage_count": 0,
                    "recorded_cost_usd": 0.0,
                    "last_used_at": None,
                },
            ),
        }
        for alias, model_id in LOCAL_SUBSCRIPTION_MODEL_REGISTRY.items()
    )
    xai_settings = get_provider_record(db, "xai")
    xai_configured = bool(
        xai_settings and provider_is_configured(xai_settings)
    )
    rows.extend(
        {
            "logical_alias": alias,
            "exact_model_id": model_id,
            "provider": "xAI",
            "modality": "text",
            "region": "xAI Responses API",
            "status": "active" if xai_configured else "disabled",
            "configured": xai_configured,
            "configuration": (
                "XAI_API_KEY configured"
                if xai_configured
                else "XAI_API_KEY is not set"
            ),
            **usage.get(
                alias,
                {
                    "usage_count": 0,
                    "recorded_cost_usd": 0.0,
                    "last_used_at": None,
                },
            ),
        }
        for alias, model_id in XAI_MODEL_REGISTRY.items()
    )
    fal_settings = get_provider_record(db, "fal")
    fal_configured = bool(fal_settings and provider_is_configured(fal_settings))
    rows.extend(
        {
            "logical_alias": alias,
            "exact_model_id": model_id,
            "provider": "fal.ai",
            "modality": alias.split(".")[1],
            "region": "fal Queue API",
            "status": "active" if fal_configured else "disabled",
            "configured": fal_configured,
            "configuration": (
                "FAL_KEY configured" if fal_configured else "FAL_KEY is not set"
            ),
            **usage.get(
                alias,
                {
                    "usage_count": 0,
                    "recorded_cost_usd": 0.0,
                    "last_used_at": None,
                },
            ),
        }
        for alias, model_id in FAL_MODEL_REGISTRY.items()
    )
    return rows
