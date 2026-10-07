"""Call-time Provider configuration. Never writes user keys to os.environ."""
import os

from .access import AccessDenied, require_live_scope

AUTH_FIELDS = {
    "OPENAI_API_KEY": ("openai", "api_key"), "OPENAI_BASE_URL": ("openai", "base_url"), "OPENAI_ORG_ID": ("openai", "organization"), "OPENAI_PROJECT_ID": ("openai", "project"),
    "XAI_API_KEY": ("xai", "api_key"), "FAL_KEY": ("fal", "api_key"),
    "MINIMAX_API_KEY": ("minimax", "api_key"), "ELEVENLABS_API_KEY": ("elevenlabs", "api_key"), "TRIPO_API_KEY": ("tripo", "api_key"),
    "GOOGLE_SERVICE_ACCOUNT_JSON": ("google", "service_account_json"), "GOOGLE_CLOUD_PROJECT": ("google", "project"),
    "GOOGLE_API_KEY": ("google", "api_key"), "GEMINI_API_KEY": ("google", "api_key"),
}


def provider_value(name: str, default=None):
    scope = require_live_scope()
    if scope is None:
        return os.getenv(name, default)
    if name == "GENERATION_PROVIDER_MODE":
        return scope.adapters.provider_mode
    if name == "GOOGLE_APPLICATION_CREDENTIALS":
        return default
    if name in AUTH_FIELDS:
        provider, key = AUTH_FIELDS[name]
        reference = next((ref for ref in scope.context.credential_references if ref.provider == provider), None)
        if reference is None:
            return default
        values = scope.adapters.credentials.resolve(scope.context, reference)
        return values.get(key, default)
    return os.getenv(name, default)
