from __future__ import annotations

import os
from typing import Any, Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ... import providers as provider_catalog
from ...contexts.administration.application import (
    FontRegistrationCommand,
    FontUpdateCommand,
    ProviderSettingsCommand,
    SkillRegistrationCommand,
)
from ...contexts.administration.domain import (
    AdministrationNotFoundError,
    AdministrationPayloadTooLargeError,
    AdministrationUnsupportedMediaError,
    AdministrationValidationError,
)
from ...database import (
    ArtifactRecord,
    CanvasRecord,
    CanvasRunRecord,
    ExperimentRunRecord,
    FontRecord,
    FormatRecord,
    ProviderSettingRecord,
    ReferenceRecord,
    RunRecord,
    SessionLocal,
    WorkflowDefinitionRecord,
)
from ...domain import NodeStatus
from ...font_registry import FONT_MAX_BYTES, inspect_font, list_fonts, register_font, update_font_profile
from ...project_skills import (
    SKILL_MAX_BYTES,
    activate_project_skill_version,
    list_project_skill_versions,
    list_project_skills,
    parse_project_skill_content,
    register_project_skill,
    set_project_skill_enabled,
)
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
from ...storage import get_storage
from ...video_downloaders import configured_video_downloader_name


class SqlAlchemyAdministrationOperations:
    def __init__(self, session_factory: Callable[[], Session] = SessionLocal) -> None:
        self._session_factory = session_factory

    def list_fonts(self, include_retired: bool) -> list[dict[str, Any]]:
        with self._session_factory() as db:
            return list_fonts(db, include_retired=include_retired)

    def register_font(self, command: FontRegistrationCommand) -> dict[str, Any]:
        if not command.filename.lower().endswith((".ttf", ".otf")):
            raise AdministrationUnsupportedMediaError(
                "only individual TTF and OTF font faces can be registered"
            )
        if not command.content:
            raise AdministrationValidationError("font file is empty")
        if len(command.content) > FONT_MAX_BYTES:
            raise AdministrationPayloadTooLargeError("font file exceeds the 24 MB limit")
        with self._session_factory() as db:
            try:
                inspect_font(command.content)
                payload, created = register_font(
                    db,
                    content=command.content,
                    filename=command.filename,
                    content_type=command.content_type,
                    display_name=command.display_name,
                    license_name=command.license_name,
                    created_by=command.created_by,
                )
            except ValueError as exc:
                raise AdministrationValidationError(str(exc)) from exc
            db.commit()
            return {**payload, "created": created}

    def update_font(self, command: FontUpdateCommand) -> dict[str, Any]:
        with self._session_factory() as db:
            font = db.get(FontRecord, command.font_id)
            if font is None:
                raise AdministrationNotFoundError("font is not registered")
            try:
                result = update_font_profile(db, font, **command.values)
            except ValueError as exc:
                raise AdministrationValidationError(str(exc)) from exc
            db.commit()
            return result

    def storage_operation(self, action: str, values: dict[str, Any]) -> dict[str, Any]:
        from ...storage_profiles import list_storage_profiles, save_storage_profile, check_storage_profile, activate_storage_profile, rotate_storage_credentials
        from ...storage_migration import migration_plan, migrate_batch
        from ...storage import StorageError
        operations = {"rotate": rotate_storage_credentials, "list": list_storage_profiles, "save": save_storage_profile, "test": check_storage_profile,
                      "activate": activate_storage_profile, "plan": migration_plan, "migrate": migrate_batch}
        try:
            return operations[action](**values)
        except (StorageError, ValueError) as exc:
            raise AdministrationValidationError(str(exc)) from exc

    def list_provider_settings(self) -> list[dict[str, Any]]:
        with self._session_factory() as db:
            return [provider_settings_payload(record) for record in ensure_provider_settings(db)]

    def update_provider_settings(self, command: ProviderSettingsCommand) -> dict[str, Any]:
        provider = command.provider.strip().lower()
        if provider not in PROVIDER_DEFINITIONS:
            raise AdministrationNotFoundError("provider not found")
        with self._session_factory() as db:
            record = get_provider_record(db, provider)
            if record is None:
                ensure_provider_settings(db)
                record = get_provider_record(db, provider)
            if record is None:
                raise AdministrationNotFoundError("provider not found")
            try:
                updated = update_provider_settings(
                    db,
                    record,
                    enabled=command.enabled,
                    auth_method=command.auth_method,
                    values=command.values,
                    clear_fields=command.clear_fields,
                )
            except ValueError as exc:
                raise AdministrationValidationError(str(exc)) from exc
            audit(
                db,
                "provider.settings.updated",
                updated.id,
                {
                    "provider": provider,
                    "enabled": updated.enabled,
                    "auth_method": command.auth_method,
                    "updated_fields": sorted(command.values),
                    "cleared_fields": sorted(command.clear_fields),
                },
            )
            db.commit()
            return provider_settings_payload(updated)

    @staticmethod
    def _usage(db: Session) -> dict[str, dict[str, Any]]:
        return {
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

    @staticmethod
    def _usage_for(usage: dict[str, dict[str, Any]], alias: str) -> dict[str, Any]:
        return usage.get(alias, {"usage_count": 0, "recorded_cost_usd": 0.0, "last_used_at": None})

    def list_models(self) -> list[dict[str, Any]]:
        with self._session_factory() as db:
            usage = self._usage(db)
            google = get_provider_record(db, "google")
            google_config = dict(google.configuration or {}) if google else {}
            google_ready = bool(google and provider_is_configured(google))
            project = google_config.get("project_id") or None
            location = str(google_config.get("location") or "us-central1")
            speech_location = str(google_config.get("speech_location") or "us")
            rows = [
                {
                    "logical_alias": alias,
                    "exact_model_id": model_id_for_alias(alias) or model_id,
                    "provider": "Google",
                    "modality": alias.split(".")[1],
                    "region": speech_location if ".stt." in alias else "global" if alias == "google.tts.latest" else location,
                    "status": "active" if google_ready else "disabled",
                    "configured": google_ready,
                    "configuration": project or "Google Service Account is not configured",
                    **self._usage_for(usage, alias),
                }
                for alias, model_id in MODEL_REGISTRY.items()
                if alias != "google.video.omni"
            ]
            rows.append({
                "logical_alias": "google.localization.pipeline",
                "exact_model_id": "chirp_3 + gemini-3.1-pro-preview + gemini-2.5-flash-tts",
                "provider": "Google",
                "modality": "video",
                "region": f"{speech_location} / {location}",
                "status": "active" if google_ready else "disabled",
                "configured": google_ready,
                "configuration": project or "Google Service Account is not configured",
                **self._usage_for(usage, "google.localization.pipeline"),
            })

            openai = get_provider_record(db, "openai")
            openai_auth = provider_auth_method_key(openai) if openai else "api_key"
            openai_ready = bool(openai and openai_auth == "api_key" and provider_is_configured(openai))
            rows.extend(self._model_rows(
                OPENAI_MODEL_REGISTRY,
                usage,
                provider="OpenAI",
                region="OpenAI API",
                configured=openai_ready,
                ready_message="OPENAI_API_KEY configured",
                missing_message="OPENAI_API_KEY is not set",
            ))

            chatgpt_ready = bool(openai and openai_auth == "chatgpt_oauth" and provider_is_configured(openai))
            claude = get_provider_record(db, "claude")
            claude_ready = bool(claude and provider_auth_method_key(claude) == "setup_token" and provider_is_configured(claude))
            for alias, model_id in LOCAL_SUBSCRIPTION_MODEL_REGISTRY.items():
                chatgpt = alias.startswith("chatgpt.")
                ready = chatgpt_ready if chatgpt else claude_ready
                rows.append({
                    "logical_alias": alias,
                    "exact_model_id": model_id,
                    "provider": "ChatGPT Subscription" if chatgpt else "Claude Code",
                    "modality": "text",
                    "region": "Local Codex CLI" if chatgpt else "Local Claude Code CLI",
                    "status": "active" if ready else "disabled",
                    "configured": ready,
                    "configuration": "Codex ChatGPT login ready" if chatgpt and ready else "Codex ChatGPT login is not ready" if chatgpt else "Claude Code setup token ready" if ready else "Claude Code setup token is not ready",
                    **self._usage_for(usage, alias),
                })

            rows.extend(self._configured_registry_rows(db, XAI_MODEL_REGISTRY, usage, "xai", "xAI", "xAI Responses API", "XAI_API_KEY configured", "XAI_API_KEY is not set"))
            rows.extend(self._configured_registry_rows(db, FAL_MODEL_REGISTRY, usage, "fal", "fal.ai", "fal Queue API", "FAL_KEY configured", "FAL_KEY is not set"))
            rows.extend(self._configured_registry_rows(db, provider_catalog.ELEVENLABS_MODEL_REGISTRY, usage, "elevenlabs", "ElevenLabs", "ElevenLabs API", "ELEVENLABS_API_KEY configured", "ELEVENLABS_API_KEY is not set"))
            rows.extend(self._configured_registry_rows(db, provider_catalog.MINIMAX_MODEL_REGISTRY, usage, "minimax", "MiniMax", "MiniMax Video V2 API", "MINIMAX_API_KEY configured", "MINIMAX_API_KEY is not set"))
            tripo_models = getattr(provider_catalog, "TRIPO_MODEL_REGISTRY", {})
            if tripo_models:
                rows.extend(self._configured_registry_rows(db, tripo_models, usage, "tripo", "Tripo", "Tripo API v3", "TRIPO_API_KEY configured", "TRIPO_API_KEY is not set", modality=lambda alias: "3d" if ".3d." in alias else "rig"))
            return rows

    def _configured_registry_rows(
        self,
        db: Session,
        registry: dict[str, str],
        usage: dict[str, dict[str, Any]],
        provider_key: str,
        provider: str,
        region: str,
        ready_message: str,
        missing_message: str,
        *,
        modality: Callable[[str], str] | None = None,
    ) -> list[dict[str, Any]]:
        settings = get_provider_record(db, provider_key)
        configured = bool(settings and provider_is_configured(settings))
        return self._model_rows(
            registry,
            usage,
            provider=provider,
            region=region,
            configured=configured,
            ready_message=ready_message,
            missing_message=missing_message,
            modality=modality,
        )

    def _model_rows(
        self,
        registry: dict[str, str],
        usage: dict[str, dict[str, Any]],
        *,
        provider: str,
        region: str,
        configured: bool,
        ready_message: str,
        missing_message: str,
        modality: Callable[[str], str] | None = None,
    ) -> list[dict[str, Any]]:
        return [
            {
                "logical_alias": alias,
                "exact_model_id": model_id,
                "provider": provider,
                "modality": modality(alias) if modality else alias.split(".")[1],
                "region": region,
                "status": "active" if configured else "disabled",
                "configured": configured,
                "configuration": ready_message if configured else missing_message,
                **self._usage_for(usage, alias),
            }
            for alias, model_id in registry.items()
        ]

    def list_skills(self, include_disabled: bool) -> list[dict[str, Any]]:
        with self._session_factory() as db:
            return [skill.public_payload() for skill in list_project_skills(db, include_disabled=include_disabled)]

    def register_skill(self, command: SkillRegistrationCommand) -> dict[str, Any]:
        if len(command.content) > SKILL_MAX_BYTES:
            raise AdministrationPayloadTooLargeError("Project Skill exceeds the 256 KB limit")
        try:
            text = command.content.decode("utf-8")
            parsed = parse_project_skill_content(text, expected_id=command.expected_id, source="upload")
        except (UnicodeDecodeError, ValueError) as exc:
            raise AdministrationValidationError(str(exc)) from exc
        with self._session_factory() as db:
            stored, created = register_project_skill(db, parsed, created_by=command.created_by)
            audit(db, "skill.version_registered", stored.version_id or stored.id, {
                "skill_id": stored.id,
                "version": stored.version,
                "version_number": stored.version_number,
                "filename": command.filename,
                "created": created,
            })
            db.commit()
            return {**stored.public_payload(), "created": created}

    def list_skill_versions(self, skill_id: str) -> list[dict[str, Any]]:
        with self._session_factory() as db:
            try:
                return [skill.public_payload() for skill in list_project_skill_versions(db, skill_id)]
            except ValueError as exc:
                self._raise_skill_error(exc)

    def activate_skill_version(self, skill_id: str, version_number: int) -> dict[str, Any]:
        with self._session_factory() as db:
            try:
                skill = activate_project_skill_version(db, skill_id, version_number)
            except ValueError as exc:
                self._raise_skill_error(exc)
            audit(db, "skill.version_activated", skill.version_id or skill.id, {"skill_id": skill.id, "version": skill.version, "version_number": skill.version_number})
            db.commit()
            return skill.public_payload()

    def set_skill_enabled(self, skill_id: str, enabled: bool) -> dict[str, Any]:
        with self._session_factory() as db:
            try:
                skill = set_project_skill_enabled(db, skill_id, enabled)
            except ValueError as exc:
                self._raise_skill_error(exc)
            audit(db, "skill.installation_updated", skill.definition_id or skill.id, {"skill_id": skill.id, "enabled": enabled})
            db.commit()
            return skill.public_payload()

    @staticmethod
    def _raise_skill_error(exc: ValueError) -> None:
        if "not registered" in str(exc):
            raise AdministrationNotFoundError(str(exc)) from exc
        raise AdministrationValidationError(str(exc)) from exc

    def health(self) -> dict[str, Any]:
        with self._session_factory() as db:
            settings = {row.provider: row for row in db.scalars(select(ProviderSettingRecord)).all()}
            return {
                "status": "ok",
                "service": "frameflow-api",
                "storage_provider": get_storage().settings.provider,
                "generation_provider_mode": os.getenv("GENERATION_PROVIDER_MODE", "live"),
                "reference_provider_mode": os.getenv("REFERENCE_PROVIDER_MODE", "live"),
                "video_downloader_provider": configured_video_downloader_name(),
                "scene_search_provider_mode": os.getenv("SCENE_SEARCH_PROVIDER_MODE", "live"),
                "reference_analysis_mode": os.getenv("REFERENCE_ANALYSIS_MODE", "live"),
                "reference_audio_separator": os.getenv("REFERENCE_AUDIO_SEPARATOR", "demucs"),
                "format_provider_mode": os.getenv("FORMAT_PROVIDER_MODE", "live"),
                **{f"{provider}_configured": bool(settings.get(provider) and provider_is_configured(settings[provider])) for provider in ("google", "openai", "xai", "claude", "tripo")},
                "execution_backend": os.getenv("EXECUTION_BACKEND", "local").lower(),
            }

    def workspace_summary(self) -> dict[str, Any]:
        with self._session_factory() as db:
            count = lambda record: int(db.scalar(select(func.count()).select_from(record)) or 0)
            regular_runs = count(RunRecord)
            canvas_runs = count(CanvasRunRecord)
            active_statuses = [NodeStatus.READY, NodeStatus.QUEUED, NodeStatus.CLAIMED, NodeStatus.SUBMITTED, NodeStatus.RUNNING, NodeStatus.WAITING_INPUT, NodeStatus.RETRY_WAIT]
            active_regular = int(db.scalar(select(func.count()).select_from(RunRecord).where(RunRecord.status.in_(active_statuses))) or 0)
            active_canvas = int(db.scalar(select(func.count()).select_from(CanvasRunRecord).where(CanvasRunRecord.status.in_(active_statuses))) or 0)
            artifact_counts = {str(kind): int(value) for kind, value in db.execute(select(ArtifactRecord.type, func.count()).group_by(ArtifactRecord.type)).all()}
            return {
                "service": "frameflow-api",
                "environment": os.getenv("APP_ENV", "development"),
                "storage_provider": get_storage().settings.provider,
                "execution_backend": os.getenv("EXECUTION_BACKEND", "local").lower(),
                "references": count(ReferenceRecord),
                "canvases": count(CanvasRecord),
                "workflows": count(WorkflowDefinitionRecord),
                "formats": count(FormatRecord),
                "runs": regular_runs + canvas_runs,
                "regular_runs": regular_runs,
                "canvas_runs": canvas_runs,
                "active_runs": active_regular + active_canvas,
                "experiments": count(ExperimentRunRecord),
                "recorded_cost_usd": float(db.scalar(select(func.coalesce(func.sum(ExperimentRunRecord.cost_usd), 0.0))) or 0),
                "images": artifact_counts.get("Image", 0),
                "characters": artifact_counts.get("Character", 0),
                "videos": artifact_counts.get("Video", 0) + artifact_counts.get("FinalVideo", 0),
                "audio": artifact_counts.get("Audio", 0),
                "artifacts": sum(artifact_counts.values()),
            }
