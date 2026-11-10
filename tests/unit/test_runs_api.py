"""End-to-end: command → plan → approval → execution → verification → report."""

from typing import Any

import httpx
from fastapi import FastAPI

from tests.conftest import tested_connection, wait_for_run
from tests.fakes import FakeAtlassian, FakeLLM, StatefulSite

PLAN: dict[str, Any] = {
    "summary": "Create the Bank IT project and its documentation space.",
    "operations": [
        {
            "id": "s1",
            "operation": "jira.create_project",
            "description": "Create project",
            "params": {"key": "BANK", "name": "Bank IT", "template": "scrum"},
        },
        {
            "id": "s2",
            "operation": "confluence.create_space",
            "description": "Create docs space",
            "params": {"key": "BANKDOC", "name": "Bank IT Docs"},
        },
        {
            "id": "s3",
            "operation": "confluence.create_page",
            "description": "Password reset guide",
            "params": {
                "space_key": "${s2.key}",
                "title": "Password reset",
                "page_kind": "how_to",
                "brief": "Steps",
            },
        },
        {"id": "s4", "operation": "jsm.configure_sla", "description": "SLA goals", "params": {}},
    ],
}


async def _run(
    client: httpx.AsyncClient, app: FastAPI, text: str = "Create Bank IT"
) -> dict[str, Any]:
    connection_id = await tested_connection(client)
    created = await client.post("/api/v1/runs", json={"connection_id": connection_id, "text": text})
    assert created.status_code == 202, created.text
    run_id = created.json()["id"]
    await wait_for_run(app, run_id)
    run: dict[str, Any] = (await client.get(f"/api/v1/runs/{run_id}")).json()
    return run


async def test_full_run_executes_only_after_approval(
    client: httpx.AsyncClient, app: FastAPI, fake_atlassian: FakeAtlassian, fake_llm: FakeLLM
) -> None:
    site = StatefulSite(fake_atlassian)
    fake_llm.intent = {
        "language": "roman_ur",
        "normalized_instruction": "Create Bank IT",
        "products": ["jira", "confluence"],
        "is_actionable": True,
    }
    fake_llm.plan = PLAN

    run = await _run(client, app, "Bank IT ka project aur docs banao")
    assert run["status"] == "awaiting_approval", run
    assert [o["status"] for o in run["operations"]] == ["requires_approval"] * 3 + ["pending"]
    assert run["operations"][3]["supported"] is False
    assert site.projects == {}, "nothing may be created before approval"
    assert run["operations"][0]["preflight"]["message"] == "Project key BANK is free."

    approved = await client.post(f"/api/v1/runs/{run['id']}/approve", json={})
    assert approved.status_code == 200, approved.text
    await wait_for_run(app, run["id"])
    run = (await client.get(f"/api/v1/runs/{run['id']}")).json()

    statuses = {o["op_id"]: o["status"] for o in run["operations"]}
    assert statuses == {"s1": "completed", "s2": "completed", "s3": "completed", "s4": "skipped"}
    assert run["status"] == "completed_with_errors"
    assert "BANK" in site.projects and "BANKDOC" in site.spaces
    page_op = run["operations"][2]
    assert page_op["resolved_params"]["space_key"] == "BANKDOC"
    assert page_op["verification"]["verified"] is True
    assert "Manual step" in run["operations"][3]["message"]
    report = run["report"]
    assert report["completed"] == 3 and report["skipped"] == 1
    assert {r["type"] for r in report["created_resources"]} == {
        "jira_project",
        "confluence_space",
        "confluence_page",
    }

    audit = (await client.get("/api/v1/audit-logs?limit=100")).json()
    actions = [a["action"] for a in audit]
    assert actions.count("operation.completed") == 3 and "run.approve" in actions


async def test_auto_approval_executes_immediately(
    client: httpx.AsyncClient, app: FastAPI, fake_atlassian: FakeAtlassian, fake_llm: FakeLLM
) -> None:
    StatefulSite(fake_atlassian)
    fake_llm.plan = {
        "summary": "List projects",
        "operations": [
            {"id": "s1", "operation": "jira.list_projects", "description": "List", "params": {}}
        ],
    }
    run = await _run(client, app)
    assert run["status"] == "completed", run
    assert run["operations"][0]["verification"]["verified"] is True


async def test_clarification_round_trip(
    client: httpx.AsyncClient, app: FastAPI, fake_atlassian: FakeAtlassian, fake_llm: FakeLLM
) -> None:
    StatefulSite(fake_atlassian)
    fake_llm.intent = {
        "language": "en",
        "normalized_instruction": "Delete old issues",
        "is_actionable": False,
        "clarification_questions": ["Which issues should be deleted?"],
    }
    run = await _run(client, app, "delete the old issues")
    assert run["status"] == "needs_clarification"
    assert run["conversation"][-1]["content"] == "Which issues should be deleted?"

    fake_llm.intent = {
        "language": "en",
        "normalized_instruction": "List projects",
        "is_actionable": True,
    }
    fake_llm.plan = {
        "summary": "List",
        "operations": [
            {"id": "s1", "operation": "jira.list_projects", "description": "List", "params": {}}
        ],
    }
    response = await client.post(
        f"/api/v1/runs/{run['id']}/clarify", json={"answer": "none, just list projects"}
    )
    assert response.status_code == 200
    await wait_for_run(app, run["id"])
    run = (await client.get(f"/api/v1/runs/{run['id']}")).json()
    assert run["status"] == "completed"
    assert [t["role"] for t in run["conversation"]] == ["user", "assistant", "user", "assistant"]


async def test_destructive_steps_need_explicit_admin_approval(
    client: httpx.AsyncClient, app: FastAPI, fake_atlassian: FakeAtlassian, fake_llm: FakeLLM
) -> None:
    site = StatefulSite(fake_atlassian)
    site.issues["BANK-1"] = {
        "id": "1",
        "key": "BANK-1",
        "fields": {"summary": "Old", "labels": [], "subtasks": []},
    }
    fake_llm.plan = {
        "summary": "Delete",
        "operations": [
            {
                "id": "s1",
                "operation": "jira.delete_issue",
                "description": "Delete BANK-1",
                "params": {"issue_key": "BANK-1"},
            }
        ],
    }
    run = await _run(client, app)
    assert "permanently delete BANK-1" in run["operations"][0]["preflight"]["message"]

    blanket = await client.post(f"/api/v1/runs/{run['id']}/approve", json={})
    assert blanket.status_code == 422, "destructive steps must be named explicitly"
    explicit = await client.post(
        f"/api/v1/runs/{run['id']}/approve", json={"operation_ids": ["s1"]}
    )
    assert explicit.status_code == 200
    await wait_for_run(app, run["id"])
    run = (await client.get(f"/api/v1/runs/{run['id']}")).json()
    assert run["operations"][0]["status"] == "completed"
    assert "BANK-1" not in site.issues


async def test_blocked_plan_cannot_be_approved(
    client: httpx.AsyncClient, app: FastAPI, fake_atlassian: FakeAtlassian, fake_llm: FakeLLM
) -> None:
    StatefulSite(fake_atlassian)
    fake_llm.plan = {
        "summary": "bad",
        "operations": [
            {
                "id": "s1",
                "operation": "jira.create_project",
                "description": "x",
                "params": {"key": "x"},
            }
        ],
    }
    run = await _run(client, app)
    assert run["status"] == "blocked"
    assert any("Invalid param" in i["message"] for i in run["plan_issues"])
    assert (await client.post(f"/api/v1/runs/{run['id']}/approve", json={})).status_code == 409
    rejected = await client.post(f"/api/v1/runs/{run['id']}/reject", json={"reason": "wrong"})
    assert rejected.json()["status"] == "rejected"


async def test_invalid_llm_output_is_repaired(
    client: httpx.AsyncClient, app: FastAPI, fake_atlassian: FakeAtlassian, fake_llm: FakeLLM
) -> None:
    StatefulSite(fake_atlassian)
    fake_llm.invalid_first = {"planning"}
    fake_llm.plan = {
        "summary": "List",
        "operations": [
            {"id": "s1", "operation": "jira.list_projects", "description": "List", "params": {}}
        ],
    }
    run = await _run(client, app)
    assert run["status"] == "completed"
    assert any("previous answer was invalid" in p for _, p in fake_llm.prompts)


async def test_run_requires_tested_connection(client: httpx.AsyncClient) -> None:
    created = await client.post(
        "/api/v1/connections",
        json={
            "name": "n",
            "site_url": "https://acme.atlassian.net",
            "email": "a@acme.com",
            "api_token": "x",
        },
    )
    response = await client.post(
        "/api/v1/runs", json={"connection_id": created.json()["id"], "text": "hi"}
    )
    assert response.status_code == 422
    assert "Test the Atlassian connection" in response.json()["error"]["message"]


async def test_idempotency_key_returns_same_run(
    client: httpx.AsyncClient, app: FastAPI, fake_atlassian: FakeAtlassian
) -> None:
    StatefulSite(fake_atlassian)
    connection_id = await tested_connection(client)
    headers = {"Idempotency-Key": "abc-123"}
    first = await client.post(
        "/api/v1/runs", json={"connection_id": connection_id, "text": "x"}, headers=headers
    )
    await wait_for_run(app, first.json()["id"])
    second = await client.post(
        "/api/v1/runs", json={"connection_id": connection_id, "text": "x"}, headers=headers
    )
    assert first.json()["id"] == second.json()["id"]
    assert len((await client.get("/api/v1/runs")).json()) == 1


async def test_operation_catalog_endpoint(client: httpx.AsyncClient) -> None:
    entries = (await client.get("/api/v1/operations")).json()
    by_name = {e["name"]: e for e in entries}
    assert by_name["jira.create_project"]["supported"] is True
    assert by_name["jsm.configure_sla"]["supported"] is False
