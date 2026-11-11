"""Execution agents against the in-memory fake Atlassian site."""

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from app.agents.confluence_agent import ConfluenceAgent
from app.agents.handlers.base import HandlerContext
from app.agents.handlers.jira_workflows import build_workflow_payload
from app.agents.handlers.storage_format import is_well_formed, normalise_entities
from app.agents.jira_agent import JiraAgent
from app.agents.jsm_agent import JsmAgent
from app.agents.verification_agent import VerificationAgent
from app.clients.atlassian.credentials import AtlassianCredentials, HttpPolicy
from app.clients.atlassian.factory import AtlassianClientFactory
from app.schemas.agents import OperationRequest, VerificationRequest
from app.schemas.operations.jira_ops import CreateWorkflowParams
from tests.fakes import SITE_URL, FakeAtlassian, StatefulSite, body

CREDS = AtlassianCredentials(SITE_URL, "ada@acme.com", SecretStr("t"))


class Writer:
    def __init__(self, html: str = "<h2>Steps</h2><p>Reset&nbsp;it.</p>") -> None:
        self.html = html
        self.calls: list[dict[str, str]] = []

    async def write(self, *, page_kind: str, title: str, brief: str, existing: str = "") -> str:
        self.calls.append({"kind": page_kind, "title": title, "brief": brief})
        return self.html


@pytest.fixture
async def ctx(fake_atlassian: FakeAtlassian) -> AsyncIterator[HandlerContext]:
    factory = AtlassianClientFactory(HttpPolicy(max_retries=0), transport=fake_atlassian.transport)
    async with factory.open(CREDS) as clients:
        yield HandlerContext(
            clients=clients,
            site_url=SITE_URL,
            run_id="run-1234567890",
            op_id="",
            account_id="acc-1",
            content_writer=Writer(),
        )


def req(
    operation: str, params: dict[str, Any], op_id: str = "s1", mode: str = "execute"
) -> OperationRequest:
    return OperationRequest(
        run_id="run-1234567890", op_id=op_id, operation=operation, params=params, mode=mode
    )  # type: ignore[arg-type]


async def test_create_project_then_reuse_and_verify(
    ctx: HandlerContext, fake_atlassian: FakeAtlassian
) -> None:
    site = StatefulSite(fake_atlassian)
    agent = JiraAgent(ctx)
    params = {"key": "BANK", "name": "Bank IT", "template": "scrum"}

    first = await agent.run(req("jira.create_project", params))
    assert first.succeeded, first.message
    sent = body(fake_atlassian.calls_to("/rest/api/3/project", "POST")[0])
    assert sent["projectTemplateKey"].endswith("gh-simplified-scrum-classic")
    assert sent["leadAccountId"] == "acc-1"
    assert first.outputs["url"] == f"{SITE_URL}/browse/BANK"

    second = await agent.run(req("jira.create_project", params))
    assert second.succeeded and second.reused_existing
    assert len(site.projects) == 1

    verified = await VerificationAgent(ctx, 0).run(
        VerificationRequest(operation="jira.create_project", params=params, outcome=first)
    )
    assert verified.verified, verified


async def test_create_project_conflict_on_key_used_elsewhere(
    ctx: HandlerContext, fake_atlassian: FakeAtlassian
) -> None:
    site = StatefulSite(fake_atlassian)
    site.projects["BANK"] = {"id": "1", "key": "BANK", "name": "Something else"}
    agent = JiraAgent(ctx)
    check = await agent.run(
        req("jira.create_project", {"key": "BANK", "name": "Bank IT"}, mode="check")
    )
    assert check.conflict and not check.succeeded
    outcome = await agent.run(req("jira.create_project", {"key": "BANK", "name": "Bank IT"}))
    assert not outcome.succeeded and outcome.error_code == "operation_conflict"


async def test_invalid_params_are_rejected_without_api_calls(
    ctx: HandlerContext, fake_atlassian: FakeAtlassian
) -> None:
    outcome = await JiraAgent(ctx).run(req("jira.create_project", {"key": "lower", "name": "X"}))
    assert outcome.error_code == "operation_invalid_input"
    assert fake_atlassian.calls == []


async def test_unsupported_operation_explains_alternative(ctx: HandlerContext) -> None:
    outcome = await JsmAgent(ctx).run(req("jsm.configure_sla", {}))
    assert outcome.error_code == "operation_unsupported"
    assert "Project settings" in outcome.message


async def test_create_issue_is_idempotent_and_uses_adf(
    ctx: HandlerContext, fake_atlassian: FakeAtlassian
) -> None:
    site = StatefulSite(fake_atlassian)
    site.projects["BANK"] = {
        "id": "1",
        "key": "BANK",
        "name": "Bank",
        "issueTypes": [{"id": "1", "name": "Task"}],
    }
    agent = JiraAgent(ctx)
    params = {
        "project_key": "BANK",
        "issue_type": "Task",
        "summary": "Set up VPN",
        "description": "First line\n\n- step one\n- step two",
    }
    first = await agent.run(req("jira.create_issue", params, op_id="s4"))
    again = await agent.run(req("jira.create_issue", params, op_id="s4"))
    assert first.outputs["key"] == again.outputs["key"] == "BANK-1"
    assert again.reused_existing and len(site.issues) == 1
    fields = body(fake_atlassian.calls_to("/rest/api/3/issue", "POST")[0])["fields"]
    assert fields["description"]["content"][1]["type"] == "bulletList"
    # The retry marker is an invisible issue property - never a visible label.
    assert not any("run" in label or "agent" in label for label in fields.get("labels", []))
    props = body(fake_atlassian.calls_to("/rest/api/3/issue", "POST")[0])["properties"]
    assert props == [{"key": "automation.step", "value": {"step": "run-run12345-s4"}}]
    verified = await VerificationAgent(ctx, 0).run(
        VerificationRequest(operation="jira.create_issue", params=params, outcome=first)
    )
    assert verified.verified, verified


async def test_verification_reports_mismatch(
    ctx: HandlerContext, fake_atlassian: FakeAtlassian
) -> None:
    site = StatefulSite(fake_atlassian)
    site.projects["BANK"] = {
        "id": "1",
        "key": "BANK",
        "name": "Bank",
        "issueTypes": [{"id": "1", "name": "Task"}],
    }
    params = {"project_key": "BANK", "issue_type": "Task", "summary": "Original"}
    outcome = await JiraAgent(ctx).run(req("jira.create_issue", params))
    site.issues["BANK-1"]["fields"]["summary"] = "Changed by someone"
    verified = await VerificationAgent(ctx, 0).run(
        VerificationRequest(operation="jira.create_issue", params=params, outcome=outcome)
    )
    assert not verified.verified
    assert "summary" in verified.message


async def test_create_page_generates_content_under_space_home(
    ctx: HandlerContext, fake_atlassian: FakeAtlassian
) -> None:
    site = StatefulSite(fake_atlassian)
    agent = ConfluenceAgent(ctx)
    space = await agent.run(req("confluence.create_space", {"key": "ITKB", "name": "IT KB"}))
    assert space.succeeded, space.message
    params = {
        "space_key": "ITKB",
        "title": "Password reset",
        "page_kind": "how_to",
        "brief": "How staff reset passwords",
        "labels": ["password-reset"],
    }
    page = await agent.run(req("confluence.create_page", params, op_id="s2"))
    assert page.succeeded, page.message
    stored = site.pages[page.outputs["id"]]
    assert stored["parentId"] == space.outputs["homepage_id"]
    assert "&#160;" in stored["body"]["storage"]["value"]  # &nbsp; normalised for XML
    assert site.labels[page.outputs["id"]] == ["password-reset"]
    verified = await VerificationAgent(ctx, 0).run(
        VerificationRequest(operation="confluence.create_page", params=params, outcome=page)
    )
    assert verified.verified, verified


async def test_malformed_generated_content_falls_back_to_plain_text(
    ctx: HandlerContext, fake_atlassian: FakeAtlassian
) -> None:
    site = StatefulSite(fake_atlassian)
    ctx.content_writer = Writer("<p>unclosed <b>tag</p>")
    agent = ConfluenceAgent(ctx)
    await agent.run(req("confluence.create_space", {"key": "ITKB", "name": "IT KB"}))
    page = await agent.run(
        req("confluence.create_page", {"space_key": "ITKB", "title": "T", "brief": "A & B"}, "s2")
    )
    assert site.pages[page.outputs["id"]]["body"]["storage"]["value"] == "<p>A &amp; B</p>"


def test_storage_format_validation() -> None:
    assert is_well_formed('<ac:structured-macro ac:name="toc" /><p>a&amp;b</p>')
    assert not is_well_formed("<p>open")
    assert normalise_entities("a&nbsp;b&amp;") == "a&#160;b&amp;"


async def test_workflow_payload_maps_transitions(
    ctx: HandlerContext, fake_atlassian: FakeAtlassian
) -> None:
    fake_atlassian.add(
        "GET",
        "/rest/api/3/statuses/search",
        json={"values": [{"id": "3", "name": "Done", "scope": {"type": "GLOBAL"}}], "isLast": True},
    )
    params = CreateWorkflowParams.model_validate(
        {
            "name": "Incident WF",
            "initial_status": "Open",
            "statuses": [
                {"name": "Open", "category": "TODO"},
                {"name": "Investigating", "category": "IN_PROGRESS"},
                {"name": "Done", "category": "DONE"},
            ],
            "transitions": [
                {"name": "Investigate", "from_statuses": ["Open"], "to_status": "Investigating"},
                {"name": "Resolve", "to_status": "Done"},
            ],
        }
    )
    payload = await build_workflow_payload(ctx, params)
    statuses = {s["name"]: s for s in payload["statuses"]}
    assert statuses["Done"]["id"] == "3" and "id" not in statuses["Open"]
    transitions = payload["workflows"][0]["transitions"]
    assert [t["type"] for t in transitions] == ["INITIAL", "DIRECTED", "GLOBAL"]
    assert transitions[1]["links"][0]["fromStatusReference"] == statuses["Open"]["statusReference"]


async def test_service_project_returns_service_desk(
    ctx: HandlerContext, fake_atlassian: FakeAtlassian
) -> None:
    StatefulSite(fake_atlassian)
    fake_atlassian.set(
        "GET",
        "/rest/servicedeskapi/servicedesk",
        json={
            "values": [
                {"id": "9", "projectId": "7001", "projectKey": "BITSD", "projectName": "Bank IT"}
            ],
            "isLastPage": True,
        },
    )
    outcome = await JsmAgent(ctx).run(
        req("jsm.create_service_project", {"key": "BITSD", "name": "Bank IT", "template": "itsm"})
    )
    assert outcome.succeeded, outcome.message
    assert outcome.outputs["service_desk_id"] == "9"
    assert outcome.outputs["portal_url"].endswith("/servicedesk/customer/portal/9")
    sent = body(fake_atlassian.calls_to("/rest/api/3/project", "POST")[0])
    assert sent["projectTypeKey"] == "service_desk"


async def test_automation_unavailable_returns_importable_rule(
    ctx: HandlerContext, fake_atlassian: FakeAtlassian
) -> None:
    site = StatefulSite(fake_atlassian)
    site.projects["ITSD"] = {"id": "10", "key": "ITSD", "name": "IT"}
    fake_atlassian.add("GET", "/_edge/tenant_info", json={"cloudId": "cloud-1"})
    outcome = await JiraAgent(ctx).run(
        req(
            "jira.create_automation_rule",
            {
                "name": "Assign P1",
                "project_key": "ITSD",
                "trigger": "issue_created",
                "jql_condition": "priority = Highest",
                "actions": [{"type": "assign", "value": "acc-9"}],
            },
        )
    )
    assert not outcome.succeeded
    rule = outcome.error_details["rule_json"]["rule"]
    assert rule["trigger"]["value"]["eventFilters"] == ["ari:cloud:jira:cloud-1:project/10"]
    assert rule["components"][0]["value"] == "priority = Highest"


async def test_transport_errors_become_failed_outcomes(
    ctx: HandlerContext, fake_atlassian: FakeAtlassian
) -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"errorMessages": ["You are not an administrator"]})

    fake_atlassian.add_handler("GET", "/rest/api/3/project/BANK", boom)
    outcome = await JiraAgent(ctx).run(req("jira.create_project", {"key": "BANK", "name": "Bank"}))
    assert outcome.error_code == "atlassian_permission_denied"
    assert "administrator" in outcome.message


def test_automation_rule_matches_live_api_shape() -> None:
    """Shape confirmed against a live site: these fields are what made create succeed."""
    from app.agents.handlers.jira_automation import build_rule
    from app.schemas.operations.jira_ops import CreateAutomationRuleParams

    p = CreateAutomationRuleParams.model_validate(
        {
            "name": "Triage",
            "project_key": "AIDEMO",
            "trigger": "issue_created",
            "jql_condition": "issuetype = Bug",
            "actions": [{"type": "assign", "value": "acc-1"}, {"type": "comment", "value": "hi"}],
        }
    )
    rule = build_rule(p, "cloud-1", "10", "acc-1", {})["rule"]
    assert rule["writeAccessType"] == "OWNER_ONLY"
    assert rule["ruleScopeARIs"] == ["ari:cloud:jira:cloud-1:project/10"]
    assert "ruleScope" not in rule
    condition, assign, _ = rule["components"]
    assert (condition["type"], condition["schemaVersion"]) == ("jira.jql.condition", -1)
    assert (assign["type"], assign["schemaVersion"]) == ("jira.issue.assign", 5)
    assert all(c["conditions"] == [] and c["children"] == [] for c in rule["components"])


async def test_automation_rejects_smart_value_assignee(ctx: HandlerContext) -> None:
    outcome = await JiraAgent(ctx).run(
        req(
            "jira.create_automation_rule",
            {
                "name": "x",
                "project_key": "AIDEMO",
                "trigger": "issue_created",
                "actions": [{"type": "assign", "value": "{{project.lead.accountId}}"}],
            },
        )
    )
    assert outcome.error_code == "operation_invalid_input"


def test_set_priority_action_uses_priority_id() -> None:
    from app.agents.handlers.jira_automation import build_rule
    from app.schemas.operations.jira_ops import CreateAutomationRuleParams

    p = CreateAutomationRuleParams.model_validate(
        {
            "name": "P",
            "project_key": "EITSD",
            "trigger": "issue_created",
            "jql_condition": "summary ~ outage",
            "actions": [{"type": "set_priority", "value": "Highest"}],
        }
    )
    rule = build_rule(p, "c", "1", "acc", {"highest": "1"})["rule"]
    op = rule["components"][1]["value"]["operations"][0]
    assert op["value"] == {"type": "ID", "value": "1"}


def test_scheduled_summary_rule_shape() -> None:
    from app.agents.handlers.jira_automation import build_rule
    from app.schemas.operations.jira_ops import CreateAutomationRuleParams

    p = CreateAutomationRuleParams.model_validate(
        {
            "name": "Daily SLA Summary",
            "project_key": "EITSD",
            "trigger": "scheduled",
            "schedule_cron": "0 0 8 ? * MON-FRI",
            "actions": [
                {
                    "type": "email_issue_list",
                    "value": "project = EITSD AND statusCategory != Done",
                    "email_to": ["lead@example.com"],
                }
            ],
        }
    )
    rule = build_rule(p, "c", "1", "acc", {})["rule"]
    assert rule["trigger"]["type"] == "jira.jql.scheduled"
    assert rule["trigger"]["value"]["schedule"]["cronExpression"] == "0 0 8 ? * MON-FRI"
    assert rule["trigger"]["value"]["executionMode"] == "nosearch"
    lookup, email = rule["components"]
    assert lookup["type"] == "jira.lookup.issues" and lookup["value"]["id"]
    assert email["type"] == "jira.issue.outgoing.email" and email["schemaVersion"] == 3
    assert email["value"]["to"] == [{"type": "FREE", "value": "lead@example.com"}]
