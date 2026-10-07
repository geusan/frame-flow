"""Public, provider-independent access and per-execution composition contracts."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Callable, Iterator, Mapping, Protocol


class AccessDenied(Exception):
    def __init__(self, status: int = 403, code: str = "access_denied"):
        self.status, self.code = status, code
        super().__init__(code)


@dataclass(frozen=True)
class Principal:
    id: str
    kind: str = "user"
    purpose: str | None = None
    session_id: str | None = None


@dataclass(frozen=True)
class WorkspaceContext:
    principal: Principal
    workspace_id: str
    request_id: str
    organization_id: str | None = None
    run_id: str | None = None
    action: str = "read"
    credential_references: tuple[CredentialReference, ...] = ()


@dataclass(frozen=True)
class CredentialReference:
    id: str
    revision: int
    provider: str
    workspace_id: str


class IdentityProvider(Protocol):
    async def authenticate(self, headers: Mapping[str, str], cookies: Mapping[str, str], method: str) -> Principal: ...


class Authorizer(Protocol):
    async def authorize(self, principal: Principal, workspace_hint: str | None, operation: str, request_id: str) -> WorkspaceContext: ...
    def revalidate(self, context: WorkspaceContext) -> None: ...


class CredentialResolver(Protocol):
    def resolve(self, context: WorkspaceContext, reference: CredentialReference) -> Mapping[str, str]: ...


@dataclass(frozen=True)
class RuntimeAdapters:
    identity: IdentityProvider
    authorization: Authorizer
    credentials: CredentialResolver
    sessions: Callable[[WorkspaceContext], Any]
    storage: Callable[[WorkspaceContext], Any]
    provider_mode: str = "live"
    artifact_url: Callable[[WorkspaceContext, str], str] | None = None
    allow_fixtures: bool = False
    execution_policy: Any | None = None
    execution_backend: str = "local"
    temporal_address: str = "localhost:7233"
    temporal_namespace: str = "default"
    temporal_queue: str = "frameflow-generation-v1"
    cost_sessions: Callable[[WorkspaceContext],Any] | None = None
    scheduler: Any | None = None


@dataclass(frozen=True)
class ExecutionScope:
    context: WorkspaceContext
    adapters: RuntimeAdapters


_scope: ContextVar[ExecutionScope | None] = ContextVar("core_execution_scope", default=None)
_active_session: ContextVar[Any | None] = ContextVar("core_active_session",default=None)


def current_session():
    return _active_session.get()


def current_scope() -> ExecutionScope | None:
    return _scope.get()


@contextmanager
def execution_scope(context: WorkspaceContext, adapters: RuntimeAdapters) -> Iterator[ExecutionScope]:
    adapters.authorization.revalidate(context)
    scope = ExecutionScope(context, adapters)
    token = _scope.set(scope)
    session_token=_active_session.set(None)
    try:
        yield scope
    finally:
        _active_session.reset(session_token)
        _scope.reset(token)


def require_live_scope() -> ExecutionScope | None:
    scope = current_scope()
    if scope:
        scope.adapters.authorization.revalidate(scope.context)
    return scope


def safe_error(error: Exception) -> str:
    return f"Execution failed ({type(error).__name__})" if current_scope() else str(error)


def credential_scope_key() -> str:
    import hashlib
    scope = current_scope()
    if scope is None:
        return "local"
    values = sorted(f"{ref.provider}:{ref.id}:{ref.revision}" for ref in scope.context.credential_references)
    return hashlib.sha256("|".join(values).encode()).hexdigest()
