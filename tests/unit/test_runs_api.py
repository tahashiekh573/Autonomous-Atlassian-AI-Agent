"""End-to-end: command → plan → approval → execution → verification → report."""

from typing import Any

import httpx
from fastapi import FastAPI

from tests.conftest import tested_connection, wait_for_run
from tests.fakes import FakeAtlassian, FakeLLM, StatefulSite, body

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
        {
            "id": "s4",
            "operation": "jsm.configure_sla_calendar",
            "description": "SLA goals",
            "params": {},
        },
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
    assert by_name["jsm.configure_sla_calendar"]["supported"] is False


async def test_long_master_prompt_is_accepted(
    client: httpx.AsyncClient, app: FastAPI, fake_atlassian: FakeAtlassian
) -> None:
    StatefulSite(fake_atlassian)
    connection_id = await tested_connection(client)
    long_text = "# MASTER PROMPT\n" + ("Configure the service desk carefully. " * 400)
    assert len(long_text) > 4000
    created = await client.post(
        "/api/v1/runs", json={"connection_id": connection_id, "text": long_text}
    )
    assert created.status_code == 202, created.text
    await wait_for_run(app, created.json()["id"])

    too_long = await client.post(
        "/api/v1/runs", json={"connection_id": connection_id, "text": "x" * 50001}
    )
    assert too_long.status_code == 422
    assert too_long.json()["error"]["details"]["errors"][0]["loc"][-1] == "text"


async def test_oversized_plan_is_truncated_with_warning(
    client: httpx.AsyncClient,
    app: FastAPI,
    fake_atlassian: FakeAtlassian,
    fake_llm: FakeLLM,
    settings: Any,
) -> None:
    StatefulSite(fake_atlassian)
    n = settings.max_plan_operations + 3
    fake_llm.plan = {
        "summary": "big",
        "operations": [
            {
                "id": f"s{i}",
                "operation": "jira.list_projects",
                "description": f"step {i}",
                "params": {},
            }
            for i in range(1, n + 1)
        ],
    }
    run = await _run(client, app)
    assert len(run["operations"]) == settings.max_plan_operations
    assert any("only the first" in w for w in run["plan"]["warnings"])


async def test_planner_expansion_adds_missing_steps_with_renumbering(
    client: httpx.AsyncClient, app: FastAPI, fake_atlassian: FakeAtlassian, fake_llm: FakeLLM
) -> None:
    StatefulSite(fake_atlassian)
    fake_llm.plan = {
        "summary": "first",
        "operations": [
            {
                "id": "s1",
                "operation": "confluence.create_space",
                "description": "KB space",
                "params": {"key": "KB2", "name": "KB two"},
            }
        ],
    }
    # The model reuses id s1 for its new step and references it: both must be renumbered.
    fake_llm.expansions = [
        {
            "complete": True,
            "operations": [
                {
                    "id": "s1",
                    "operation": "confluence.create_page",
                    "description": "Article",
                    "params": {"space_key": "KB2", "title": "Reset password"},
                },
                {
                    "id": "s2",
                    "operation": "confluence.add_labels",
                    "description": "Label",
                    "params": {"page_id": "${s1.id}", "labels": ["kb"]},
                    "depends_on": ["s1"],
                },
            ],
            "coverage": [{"requirement": "Article: Reset password", "operation_ids": ["s1"]}],
        }
    ]
    run = await _run(client, app)
    ops = {o["op_id"]: o for o in run["operations"]}
    assert list(ops) == ["s1", "s2", "s3"]
    assert ops["s3"]["params"]["page_id"] == "${s2.id}" and ops["s3"]["depends_on"] == ["s2"]
    assert run["plan"]["coverage"][-1]["operation_ids"] == ["s2"]


def test_split_sections_only_for_long_structured_requests() -> None:
    from app.agents.planning_agent import split_sections

    assert split_sections("## A\nshort") == []
    text = "# Title\nintro\n" + "".join(
        f"## Part {i}\n" + ("detail " * 120) + "\n" for i in range(4)
    )
    sections = split_sections(text)
    assert [t for t, _ in sections] == ["Part 0", "Part 1", "Part 2", "Part 3"]


async def test_long_request_is_planned_section_by_section(
    client: httpx.AsyncClient, app: FastAPI, fake_atlassian: FakeAtlassian, fake_llm: FakeLLM
) -> None:
    StatefulSite(fake_atlassian)
    connection_id = await tested_connection(client)
    fake_llm.expansions = [
        {
            "complete": True,
            "operations": [
                {
                    "id": "s1",
                    "operation": "jira.list_projects",
                    "description": "List A",
                    "params": {},
                }
            ],
        },
        {"complete": True, "operations": []},  # an instructions-only section
        {
            "complete": True,
            "operations": [
                {
                    "id": "s2",
                    "operation": "jira.list_projects",
                    "description": "List C",
                    "params": {},
                }
            ],
        },
    ]
    text = "# Big\n" + "".join(f"## Section {c}\n" + ("words " * 150) + "\n" for c in "ABC")
    created = await client.post("/api/v1/runs", json={"connection_id": connection_id, "text": text})
    await wait_for_run(app, created.json()["id"])
    run = (await client.get(f"/api/v1/runs/{created.json()['id']}")).json()
    assert [o["description"] for o in run["operations"]] == ["List A", "List C"]
    section_prompts = [p for s, p in fake_llm.prompts if "Section to plan now" in p]
    assert len(section_prompts) == 3


async def test_invalid_params_are_repaired_by_the_planner(
    client: httpx.AsyncClient, app: FastAPI, fake_atlassian: FakeAtlassian, fake_llm: FakeLLM
) -> None:
    StatefulSite(fake_atlassian)
    fake_llm.plan = {
        "summary": "p",
        "operations": [
            {
                "id": "s1",
                "operation": "jira.create_priority",
                "description": "Critical",
                "params": {"name": "Critical", "color": "red"},
            }
        ],
    }
    fake_llm.param_fixes = [{"id": "s1", "params": {"name": "Critical", "color": "#FF0000"}}]
    run = await _run(client, app)
    assert run["status"] == "awaiting_approval", run["plan_issues"]
    assert run["operations"][0]["params"]["color"] == "#FF0000"


def test_merge_drops_duplicate_steps_and_redirects_references() -> None:
    from app.agents.planning_agent import _merge
    from app.schemas.agents import ExecutionPlan, PlanExpansion

    plan = ExecutionPlan.model_validate(
        {
            "summary": "",
            "operations": [
                {
                    "id": "s1",
                    "operation": "jira.create_issue",
                    "description": "Outage",
                    "params": {
                        "project_key": "EITSD",
                        "issue_type": "Incident",
                        "summary": "Network outage",
                    },
                }
            ],
        }
    )
    expansion = PlanExpansion.model_validate(
        {
            "complete": True,
            "operations": [
                {
                    "id": "s2",
                    "operation": "jira.create_issue",
                    "description": "Outage again",
                    "params": {
                        "project_key": "EITSD",
                        "issue_type": "Incident",
                        "summary": "network outage ",
                    },
                },
                {
                    "id": "s3",
                    "operation": "jira.link_issues",
                    "description": "link",
                    "params": {"from_issue": "${s2.key}", "to_issue": "EITSD-1"},
                    "depends_on": ["s2"],
                },
            ],
        }
    )
    assert _merge(plan, expansion) == 1
    assert [o.id for o in plan.operations] == ["s1", "s3"]
    assert plan.operations[1].params["from_issue"] == "${s1.key}"
    assert plan.operations[1].depends_on == ["s1"]


async def test_unsafe_automation_step_is_skipped_not_blocking(
    client: httpx.AsyncClient, app: FastAPI, fake_atlassian: FakeAtlassian, fake_llm: FakeLLM
) -> None:
    StatefulSite(fake_atlassian)
    fake_llm.plan = {
        "summary": "p",
        "operations": [
            {"id": "s1", "operation": "jira.list_projects", "description": "list", "params": {}},
            {
                "id": "s2",
                "operation": "jira.create_automation_rule",
                "description": "Auto-close",
                "params": {
                    "name": "Auto-close",
                    "project_key": "EITSD",
                    "trigger": "issue_updated",
                    "actions": [{"type": "transition", "value": "Closed"}],
                },
            },
        ],
    }
    run = await _run(client, app)
    assert run["status"] == "completed_with_errors", run["plan_issues"]
    ops = {o["op_id"]: o for o in run["operations"]}
    assert ops["s1"]["status"] == "completed"
    assert ops["s2"]["status"] == "skipped" and "every issue" in ops["s2"]["message"]


async def test_requirements_ledger_reports_what_was_asked_not_just_steps(
    client: httpx.AsyncClient, app: FastAPI, fake_atlassian: FakeAtlassian, fake_llm: FakeLLM
) -> None:
    StatefulSite(fake_atlassian)
    fake_llm.plan = PLAN
    fake_llm.requirements = [
        "Project BANK",
        "Documentation space BANKDOC",
        "Welcome article",
        "2 sample tickets",
        "Portal logo",
    ]
    fake_llm.coverage = [
        {"requirement": "Project BANK", "operation_ids": ["s1"]},
        {"requirement": "Documentation space BANKDOC", "operation_ids": ["s2"]},
        {"requirement": "Welcome article", "operation_ids": ["s3"]},
        {"requirement": "2 sample tickets", "operation_ids": []},
        {"requirement": "Portal logo", "operation_ids": [], "manual_reason": "No API"},
    ]
    run = await _run(client, app, "Bank IT ka project, docs aur 2 sample tickets banao")
    # the forgotten item was sent back to the planner as a gap
    assert any(
        "does not fully deliver yet" in p and "2 sample tickets" in p for _, p in fake_llm.prompts
    )
    await client.post(f"/api/v1/runs/{run['id']}/approve", json={})
    await wait_for_run(app, run["id"])
    report = (await client.get(f"/api/v1/runs/{run['id']}")).json()["report"]
    states = {r["requirement"]: r["status"] for r in report["requirements"]}
    assert states == {
        "Project BANK": "done",
        "Documentation space BANKDOC": "done",
        "Welcome article": "done",
        "2 sample tickets": "missing",
        "Portal logo": "manual",
        "SLA goals": "manual",  # an unsupported step no requirement claimed is still listed
    }
    assert report["completion_percent"] == 75
    assert "3 of 6 done" in report["summary"] and "1 not planned" in report["summary"]


async def test_rejected_step_is_auto_corrected_instead_of_skipped(
    client: httpx.AsyncClient, app: FastAPI, fake_atlassian: FakeAtlassian, fake_llm: FakeLLM
) -> None:
    StatefulSite(fake_atlassian)
    filters: dict[str, dict[str, Any]] = {}

    def parse(request: httpx.Request) -> httpx.Response:
        queries = body(request)["queries"]
        return httpx.Response(
            200,
            json={
                "queries": [
                    {
                        "query": q,
                        "errors": ["Expecting operator but got '('."] if "slaFunction" in q else [],
                    }
                    for q in queries
                ]
            },
        )

    def create(request: httpx.Request) -> httpx.Response:
        data = body(request)
        filters["900"] = {"id": "900", "name": data["name"], "jql": data["jql"]}
        return httpx.Response(200, json=filters["900"])

    fake_atlassian.add_handler("POST", "/rest/api/3/jql/parse", parse)
    fake_atlassian.add("GET", "/rest/api/3/filter/search", json={"values": [], "isLast": True})
    fake_atlassian.add_handler("POST", "/rest/api/3/filter", create)
    fake_atlassian.add_pattern(
        "GET", r"/rest/api/3/filter/(\d+)", lambda _r, fid: httpx.Response(200, json=filters[fid])
    )
    fake_llm.plan = {
        "summary": "SLA filter",
        "operations": [
            {
                "id": "s1",
                "operation": "jira.create_filter",
                "description": "SLA breached filter",
                "params": {
                    "name": "SLA Breached",
                    "jql": "resolution = Unresolved AND (slaFunction(breached()))",
                },
            }
        ],
    }
    fake_llm.step_repairs = [
        {
            "fixable": True,
            "params": {"name": "SLA Breached", "jql": '"Time to resolution" = breached()'},
            "explanation": "slaFunction is not JQL; SLA fields support breached() directly",
        }
    ]
    run = await _run(client, app, "SLA breached tickets ka filter banao")
    assert not [i for i in run["plan_issues"] if i["severity"] == "error"], run["plan_issues"]
    assert run["operations"][0]["params"]["jql"] == '"Time to resolution" = breached()'
    await client.post(f"/api/v1/runs/{run['id']}/approve", json={})
    await wait_for_run(app, run["id"])
    done = (await client.get(f"/api/v1/runs/{run['id']}")).json()
    assert done["operations"][0]["status"] == "completed"
    assert filters["900"]["jql"] == '"Time to resolution" = breached()'
