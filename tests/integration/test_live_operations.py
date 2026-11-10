"""Real create → verify → delete cycles against a controlled Atlassian test site.

Opt-in: requires the ATLASSIAN_TEST_* credentials (see test_live_connection.py) plus
  ATLASSIAN_TEST_ALLOW_WRITES=1
  ATLASSIAN_TEST_PROJECT_KEY=<existing test project>   (Jira issue cycle)
  ATLASSIAN_TEST_SPACE_KEY=<existing test space>       (Confluence page cycle)
Everything created is deleted at the end of each test.
"""

import os
import uuid
from collections.abc import AsyncIterator

import pytest
from pydantic import SecretStr

from app.agents.confluence_agent import ConfluenceAgent
from app.agents.handlers.base import HandlerContext
from app.agents.jira_agent import JiraAgent
from app.agents.verification_agent import VerificationAgent
from app.clients.atlassian.credentials import AtlassianCredentials, HttpPolicy
from app.clients.atlassian.factory import AtlassianClientFactory
from app.schemas.agents import OperationRequest, VerificationRequest

pytestmark = pytest.mark.integration


def _env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        pytest.skip(f"{name} not set")
    return value


@pytest.fixture
async def ctx() -> AsyncIterator[HandlerContext]:
    if os.environ.get("ATLASSIAN_TEST_ALLOW_WRITES") != "1":
        pytest.skip("set ATLASSIAN_TEST_ALLOW_WRITES=1 to run write tests")
    credentials = AtlassianCredentials(
        site_url=_env("ATLASSIAN_TEST_SITE_URL").rstrip("/"),
        email=_env("ATLASSIAN_TEST_EMAIL"),
        api_token=SecretStr(_env("ATLASSIAN_TEST_API_TOKEN")),
    )
    async with AtlassianClientFactory(HttpPolicy()).open(credentials) as clients:
        me = await clients.jira.get_myself()
        yield HandlerContext(
            clients=clients,
            site_url=credentials.site_url,
            run_id=str(uuid.uuid4()),
            op_id="",
            account_id=me.account_id,
        )


def _req(ctx: HandlerContext, operation: str, params: dict[str, object]) -> OperationRequest:
    return OperationRequest(run_id=ctx.run_id, op_id="s1", operation=operation, params=params)


async def test_issue_create_verify_delete(ctx: HandlerContext) -> None:
    project = _env("ATLASSIAN_TEST_PROJECT_KEY")
    params = {
        "project_key": project,
        "issue_type": "Task",
        "summary": f"AI agent integration test {ctx.run_id[:8]}",
        "description": "Temporary.",
    }
    outcome = await JiraAgent(ctx).run(_req(ctx, "jira.create_issue", params))
    assert outcome.succeeded, outcome.message
    try:
        result = await VerificationAgent(ctx).run(
            VerificationRequest(operation="jira.create_issue", params=params, outcome=outcome)
        )
        assert result.verified, result
    finally:
        await ctx.jira.delete_issue(str(outcome.outputs["key"]))


async def test_page_create_verify_delete(ctx: HandlerContext) -> None:
    space = _env("ATLASSIAN_TEST_SPACE_KEY")
    params = {
        "space_key": space,
        "title": f"AI agent integration test {ctx.run_id[:8]}",
        "body_storage": "<h2>Test</h2><p>Temporary page.</p>",
        "labels": ["ai-agent-test"],
    }
    outcome = await ConfluenceAgent(ctx).run(_req(ctx, "confluence.create_page", params))
    assert outcome.succeeded, outcome.message
    try:
        result = await VerificationAgent(ctx).run(
            VerificationRequest(operation="confluence.create_page", params=params, outcome=outcome)
        )
        assert result.verified, result
    finally:
        await ctx.confluence.delete_page(str(outcome.outputs["id"]))
