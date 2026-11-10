"""Read-only overview of a connected site for the dashboard's product sections.

Infrastructure read (like the connection probe), so the service calls clients directly.
"""

from typing import Any

from pydantic import SecretStr

from app.clients.atlassian.credentials import AtlassianCredentials
from app.clients.atlassian.factory import AtlassianClientFactory
from app.core.exceptions import AtlassianError, NotFoundError
from app.core.security import CredentialCipher
from app.repositories.connection_repository import ConnectionRepository
from app.schemas.operations.catalog import CATALOG
from app.schemas.run import OperationCatalogEntry


class WorkspaceService:
    def __init__(
        self,
        connections: ConnectionRepository,
        cipher: CredentialCipher,
        factory: AtlassianClientFactory,
    ) -> None:
        self._connections = connections
        self._cipher = cipher
        self._factory = factory

    async def overview(self, connection_id: str) -> dict[str, Any]:
        connection = await self._connections.get(connection_id)
        if connection is None:
            raise NotFoundError(f"Connection '{connection_id}' not found.")
        credentials = AtlassianCredentials(
            site_url=connection.site_url,
            email=connection.email,
            api_token=SecretStr(self._cipher.decrypt(connection.encrypted_api_token)),
        )
        products = (connection.capabilities or {}).get("products") or {}
        result: dict[str, Any] = {
            "site_url": connection.site_url,
            "capabilities": connection.capabilities,
            "errors": {},
        }
        async with self._factory.open(credentials) as clients:
            if products.get("jira"):
                try:
                    result["jira_projects"] = [
                        p.model_dump() for p in await clients.jira.list_projects(max_items=100)
                    ]
                except AtlassianError as exc:
                    result["errors"]["jira"] = exc.message
            if products.get("jsm"):
                try:
                    result["service_desks"] = [
                        d.model_dump() for d in await clients.jsm.list_service_desks(max_items=100)
                    ]
                except AtlassianError as exc:
                    result["errors"]["jsm"] = exc.message
            if products.get("confluence"):
                try:
                    result["spaces"] = [
                        s.model_dump() for s in await clients.confluence.list_spaces(max_items=100)
                    ]
                except AtlassianError as exc:
                    result["errors"]["confluence"] = exc.message
        return result


def operation_catalog() -> list[OperationCatalogEntry]:
    return [
        OperationCatalogEntry(
            name=s.name,
            agent=s.agent,
            risk=s.risk,
            description=s.description,
            supported=s.supported,
            needs_jira_admin=s.needs_jira_admin,
            limitation=s.limitation,
            alternative=s.alternative,
            params_schema=s.params.model_json_schema() if s.supported else {},
        )
        for s in CATALOG.values()
    ]
