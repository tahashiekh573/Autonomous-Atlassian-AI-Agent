"""Dependency-injection providers (the composition root for request-scoped objects)."""

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Annotated

from fastapi import Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.atlassian.factory import AtlassianClientFactory
from app.core.config import Settings
from app.core.exceptions import AuthenticationError, AuthorizationError
from app.core.security import CredentialCipher, TokenService, api_key_matches
from app.db.session import Database
from app.repositories.audit_log_repository import AuditLogRepository
from app.repositories.connection_repository import ConnectionRepository
from app.repositories.run_repository import RunRepository
from app.repositories.user_repository import UserRepository
from app.schemas.auth import Principal
from app.services.audit_service import AuditService
from app.services.auth_service import AuthService
from app.services.connection_service import ConnectionService
from app.services.run_engine import RunEngine
from app.services.run_service import RunService
from app.services.voice_service import VoiceService
from app.services.workspace_service import WorkspaceService

SERVICE_PRINCIPAL = Principal(
    user_id="service", email="api-key", role="admin", display_name="API key"
)
DEV_PRINCIPAL = Principal(
    user_id="dev", email="dev@local", role="admin", display_name="Local developer"
)


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_database(request: Request) -> Database:
    database: Database = request.app.state.database
    return database


def get_cipher(request: Request) -> CredentialCipher:
    cipher: CredentialCipher = request.app.state.cipher
    return cipher


def get_client_factory(request: Request) -> AtlassianClientFactory:
    factory: AtlassianClientFactory = request.app.state.client_factory
    return factory


def get_engine(request: Request) -> RunEngine:
    engine: RunEngine = request.app.state.engine
    return engine


def get_voice_service(request: Request) -> VoiceService:
    voice: VoiceService = request.app.state.voice
    return voice


async def get_session(
    database: Annotated[Database, Depends(get_database)],
) -> AsyncIterator[AsyncSession]:
    async with database.session() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
CipherDep = Annotated[CredentialCipher, Depends(get_cipher)]
FactoryDep = Annotated[AtlassianClientFactory, Depends(get_client_factory)]


def get_tokens(request: Request) -> TokenService:
    tokens: TokenService = request.app.state.tokens
    return tokens


# --- authentication ------------------------------------------------------------------------


async def get_principal(
    request: Request,
    settings: SettingsDep,
    session: SessionDep,
    authorization: Annotated[str | None, Header()] = None,
) -> Principal:
    """Bearer ADMIN_API_KEY (service account) or a user's JWT access token."""
    scheme, _, token = (authorization or "").partition(" ")
    token = token.strip()
    if scheme.lower() == "bearer" and token:
        key = settings.admin_api_key
        if key is not None and key.get_secret_value() and api_key_matches(token, key):
            principal = SERVICE_PRINCIPAL
        else:
            auth = AuthService(
                UserRepository(session),
                get_tokens(request),
                AuditService(AuditLogRepository(session)),
            )
            principal = await auth.principal_from_token(token)
    elif settings.open_dev_mode:
        principal = DEV_PRINCIPAL
    else:
        raise AuthenticationError("Missing bearer token.")
    request.state.principal = principal
    return principal


PrincipalDep = Annotated[Principal, Depends(get_principal)]


def require_role(role: str) -> Callable[[Principal], Awaitable[Principal]]:
    async def dependency(principal: PrincipalDep) -> Principal:
        if not principal.has_role(role):
            raise AuthorizationError(f"This action requires the '{role}' role.")
        return principal

    return dependency


ViewerDep = Annotated[Principal, Depends(require_role("viewer"))]
OperatorDep = Annotated[Principal, Depends(require_role("operator"))]
AdminDep = Annotated[Principal, Depends(require_role("admin"))]


# --- services ------------------------------------------------------------------------------


def get_audit_service(request: Request, session: SessionDep) -> AuditService:
    principal: Principal | None = getattr(request.state, "principal", None)
    return AuditService(
        AuditLogRepository(session), actor=principal.email if principal else "anonymous"
    )


AuditServiceDep = Annotated[AuditService, Depends(get_audit_service)]


def get_auth_service(request: Request, session: SessionDep, audit: AuditServiceDep) -> AuthService:
    return AuthService(UserRepository(session), get_tokens(request), audit)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]


def get_connection_service(
    session: SessionDep,
    settings: SettingsDep,
    audit: AuditServiceDep,
    cipher: CipherDep,
    factory: FactoryDep,
) -> ConnectionService:
    return ConnectionService(
        repository=ConnectionRepository(session),
        audit=audit,
        cipher=cipher,
        client_factory=factory,
        allowed_host_suffixes=settings.atlassian_allowed_host_suffixes,
    )


ConnectionServiceDep = Annotated[ConnectionService, Depends(get_connection_service)]


def get_run_service(
    session: SessionDep, audit: AuditServiceDep, engine: Annotated[RunEngine, Depends(get_engine)]
) -> RunService:
    return RunService(RunRepository(session), ConnectionRepository(session), audit, engine)


RunServiceDep = Annotated[RunService, Depends(get_run_service)]


def get_workspace_service(
    session: SessionDep, cipher: CipherDep, factory: FactoryDep
) -> WorkspaceService:
    return WorkspaceService(ConnectionRepository(session), cipher, factory)


WorkspaceServiceDep = Annotated[WorkspaceService, Depends(get_workspace_service)]
VoiceServiceDep = Annotated[VoiceService, Depends(get_voice_service)]
