"""Business logic for saving and testing Atlassian Cloud connections."""

from urllib.parse import urlparse

from pydantic import SecretStr

from app.clients.atlassian.credentials import AtlassianCredentials
from app.clients.atlassian.factory import AtlassianClientFactory
from app.core.exceptions import ConflictError, NotFoundError, RequestValidationAppError
from app.core.security import CredentialCipher
from app.db.base import utcnow
from app.models.atlassian_connection import AtlassianConnection
from app.repositories.connection_repository import ConnectionRepository
from app.schemas.connection import (
    ConnectionCreate,
    ConnectionRead,
    ConnectionTestResult,
    TestStatus,
)
from app.services.atlassian_probe import AtlassianProbe
from app.services.audit_service import AuditService


class ConnectionService:
    def __init__(
        self,
        repository: ConnectionRepository,
        audit: AuditService,
        cipher: CredentialCipher,
        client_factory: AtlassianClientFactory,
        allowed_host_suffixes: list[str],
        probe: AtlassianProbe | None = None,
    ) -> None:
        self._repo = repository
        self._audit = audit
        self._cipher = cipher
        self._factory = client_factory
        self._allowed_suffixes = [s.lower() for s in allowed_host_suffixes]
        self._probe = probe or AtlassianProbe()

    async def create(self, data: ConnectionCreate) -> ConnectionRead:
        self._validate_site_url(data.site_url)
        if await self._repo.get_by_name(data.name):
            raise ConflictError(f"A connection named '{data.name}' already exists.")
        connection = await self._repo.add(
            AtlassianConnection(
                name=data.name,
                site_url=data.site_url,
                email=data.email,
                encrypted_api_token=self._cipher.encrypt(data.api_token.get_secret_value()),
            )
        )
        await self._audit.record(
            action="connection.create",
            resource_type="atlassian_connection",
            resource_id=connection.id,
            outcome="success",
            details={"name": data.name, "site_url": data.site_url},
        )
        return ConnectionRead.model_validate(connection)

    async def list(self) -> list[ConnectionRead]:
        return [ConnectionRead.model_validate(c) for c in await self._repo.list()]

    async def get(self, connection_id: str) -> ConnectionRead:
        return ConnectionRead.model_validate(await self._require(connection_id))

    async def delete(self, connection_id: str) -> None:
        """Remove the locally stored connection. Nothing in Atlassian is touched."""
        connection = await self._require(connection_id)
        await self._repo.delete(connection)
        await self._audit.record(
            action="connection.delete",
            resource_type="atlassian_connection",
            resource_id=connection_id,
            outcome="success",
            details={"name": connection.name},
        )

    async def test(self, connection_id: str) -> ConnectionTestResult:
        connection = await self._require(connection_id)
        credentials = AtlassianCredentials(
            site_url=connection.site_url,
            email=connection.email,
            api_token=SecretStr(self._cipher.decrypt(connection.encrypted_api_token)),
        )
        async with self._factory.open(credentials) as clients:
            probe = await self._probe.run(clients)

        # Assets is an add-on: its absence must not make the whole connection "partial".
        status = _overall_status([p.available for p in probe.products if p.product != "assets"])
        tested_at = utcnow()
        result = ConnectionTestResult(
            connection_id=connection.id,
            status=status,
            tested_at=tested_at,
            account=probe.account,
            is_jira_admin=probe.is_jira_admin,
            products=probe.products,
        )
        await self._repo.record_test_result(
            connection,
            tested_at=tested_at,
            status=status,
            capabilities={
                "account_id": probe.account.account_id if probe.account else None,
                "is_jira_admin": probe.is_jira_admin,
                "products": {p.product: p.available for p in probe.products},
            },
        )
        await self._audit.record(
            action="connection.test",
            resource_type="atlassian_connection",
            resource_id=connection.id,
            outcome=status,
            details={p.product: p.error_code or "ok" for p in probe.products},
        )
        return result

    async def _require(self, connection_id: str) -> AtlassianConnection:
        connection = await self._repo.get(connection_id)
        if connection is None:
            raise NotFoundError(f"Connection '{connection_id}' not found.")
        return connection

    def _validate_site_url(self, site_url: str) -> None:
        parsed = urlparse(site_url)
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or not host:
            raise RequestValidationAppError("site_url must be an https:// URL.")
        if parsed.path not in ("", "/") or parsed.query or parsed.username:
            raise RequestValidationAppError(
                "site_url must be the site root, e.g. https://acme.atlassian.net"
            )
        if not any(host.endswith(suffix) for suffix in self._allowed_suffixes):
            raise RequestValidationAppError(
                f"site_url host must end with one of: {', '.join(self._allowed_suffixes)}"
            )


def _overall_status(available: list[bool]) -> TestStatus:
    if all(available):
        return "ok"
    if any(available):
        return "partial"
    return "failed"
