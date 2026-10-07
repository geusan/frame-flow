from __future__ import annotations

from sqlalchemy.orm import Session

from ...nodes.contracts import NodeProviderAuth
from ...provider_settings import (
    get_provider_record,
    provider_auth_method_key,
    provider_is_configured,
)


class SqlAlchemyNodeProviderSettings:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_auth(self, provider_key: str) -> NodeProviderAuth | None:
        from ...access import require_live_scope
        scope = require_live_scope()
        if scope:
            reference = next((ref for ref in scope.context.credential_references if ref.provider == provider_key), None)
            return NodeProviderAuth(auth_method="api_key", configured=reference is not None, setup_token="")
        record = get_provider_record(self._session, provider_key)
        if record is None:
            return None
        return NodeProviderAuth(
            auth_method=provider_auth_method_key(record),
            configured=provider_is_configured(record),
            setup_token=str((record.secrets or {}).get("setup_token") or ""),
        )
