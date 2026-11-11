"""Builds per-site product clients that share authenticated HTTP connection pools."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace

import httpx

from app.clients.atlassian.credentials import AtlassianCredentials, HttpPolicy
from app.clients.atlassian.http_client import AtlassianHttpClient
from app.clients.confluence.confluence_client import ConfluenceClient
from app.clients.jira.jira_client import JiraClient
from app.clients.jsm.assets_client import AssetsClient
from app.clients.jsm.forms_client import FormsClient
from app.clients.jsm.jsm_client import JsmClient

# Fixed Atlassian platform host used by the Forms and Assets APIs (never user-supplied).
PLATFORM_URL = "https://api.atlassian.com"


@dataclass(frozen=True)
class AtlassianClients:
    jira: JiraClient
    jsm: JsmClient
    confluence: ConfluenceClient
    forms: FormsClient
    assets: AssetsClient


class AtlassianClientFactory:
    def __init__(
        self, policy: HttpPolicy, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._policy = policy
        self._transport = transport  # injectable for tests

    @asynccontextmanager
    async def open(self, credentials: AtlassianCredentials) -> AsyncIterator[AtlassianClients]:
        site = AtlassianHttpClient(credentials, self._policy, transport=self._transport)
        platform = AtlassianHttpClient(
            replace(credentials, site_url=PLATFORM_URL), self._policy, transport=self._transport
        )
        try:
            yield AtlassianClients(
                jira=JiraClient(site),
                jsm=JsmClient(site),
                confluence=ConfluenceClient(site),
                forms=FormsClient(platform),
                assets=AssetsClient(platform),
            )
        finally:
            await site.aclose()
            await platform.aclose()
