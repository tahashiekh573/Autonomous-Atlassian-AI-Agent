"""Read-only checks against a real Atlassian Cloud test site.

Set ATLASSIAN_TEST_SITE_URL, ATLASSIAN_TEST_EMAIL and ATLASSIAN_TEST_API_TOKEN to run.
Nothing in the instance is modified.
"""

import os

import pytest
from pydantic import SecretStr

from app.clients.atlassian.credentials import AtlassianCredentials, HttpPolicy
from app.clients.atlassian.factory import AtlassianClientFactory
from app.services.atlassian_probe import AtlassianProbe

pytestmark = pytest.mark.integration

_ENV = ("ATLASSIAN_TEST_SITE_URL", "ATLASSIAN_TEST_EMAIL", "ATLASSIAN_TEST_API_TOKEN")


@pytest.fixture
def credentials() -> AtlassianCredentials:
    missing = [name for name in _ENV if not os.environ.get(name)]
    if missing:
        pytest.skip(f"integration env not configured: {', '.join(missing)}")
    return AtlassianCredentials(
        site_url=os.environ["ATLASSIAN_TEST_SITE_URL"].rstrip("/"),
        email=os.environ["ATLASSIAN_TEST_EMAIL"],
        api_token=SecretStr(os.environ["ATLASSIAN_TEST_API_TOKEN"]),
    )


async def test_probe_live_site(credentials: AtlassianCredentials) -> None:
    async with AtlassianClientFactory(HttpPolicy()).open(credentials) as clients:
        result = await AtlassianProbe().run(clients)
    jira = next(p for p in result.products if p.product == "jira")
    assert jira.available, jira.detail
    assert result.account is not None


async def test_list_projects_paginates_live(credentials: AtlassianCredentials) -> None:
    async with AtlassianClientFactory(HttpPolicy()).open(credentials) as clients:
        projects = await clients.jira.list_projects(max_items=100)
    assert all(p.key for p in projects)
