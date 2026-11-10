"""Builds per-site product clients that share one authenticated HTTP connection pool."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import httpx

from app.clients.atlassian.credentials import AtlassianCredentials, HttpPolicy
from app.clients.atlassian.http_client import AtlassianHttpClient
from app.clients.confluence.confluence_client import ConfluenceClient
from app.clients.jira.jira_client import JiraClient
from app.clients.jsm.jsm_client import JsmClient


@dataclass(frozen=True)
class AtlassianClients:
    jira: JiraClient
    jsm: JsmClient
    confluence: ConfluenceClient


class AtlassianClientFactory:
    def __init__(
        self, policy: HttpPolicy, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._policy = policy
        self._transport = transport  # injectable for tests

    @asynccontextmanager
    async def open(self, credentials: AtlassianCredentials) -> AsyncIterator[AtlassianClients]:
        http = AtlassianHttpClient(credentials, self._policy, transport=self._transport)
        try:
            yield AtlassianClients(
                jira=JiraClient(http), jsm=JsmClient(http), confluence=ConfluenceClient(http)
            )
        finally:
            await http.aclose()
