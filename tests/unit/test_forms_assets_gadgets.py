"""Forms, Assets, gadget resolution, JSM experimental header and LLM pacing."""

import time
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from app.agents.handlers.base import HandlerContext
from app.agents.handlers.jira_dashboards import gadget_reference
from app.agents.jira_agent import JiraAgent
from app.agents.jsm_agent import JsmAgent
from app.agents.verification_agent import VerificationAgent
from app.clients.atlassian.credentials import AtlassianCredentials, HttpPolicy
from app.clients.atlassian.factory import AtlassianClientFactory
from app.clients.llm.rate_limiter import RateLimiter
from app.schemas.agents import OperationRequest, VerificationRequest
from tests.fakes import SITE_URL, FakeAtlassian, StatefulSite, body

CREDS = AtlassianCredentials(SITE_URL, "ada@acme.com", SecretStr("t"))
FORMS = "/jira/forms/cloud/cloud-1/project/ITSD/form"
ASSETS = "/jsm/assets/workspace/ws-1/v1"


@pytest.fixture
async def ctx(fake_atlassian: FakeAtlassian) -> AsyncIterator[HandlerContext]:
    factory = AtlassianClientFactory(HttpPolicy(max_retries=0), transport=fake_atlassian.transport)
    async with factory.open(CREDS) as clients:
        yield HandlerContext(
            clients=clients,
            site_url=SITE_URL,
            run_id="run-1234567890",
            op_id="s1",
            account_id="acc-1",
        )


def req(operation: str, params: dict[str, Any]) -> OperationRequest:
    return OperationRequest(run_id="run-1234567890", op_id="s1", operation=operation, params=params)


def desk(fake: FakeAtlassian) -> None:
    fake.add(
        "GET",
        "/rest/servicedeskapi/servicedesk",
        json={
            "values": [{"id": "9", "projectId": "10", "projectKey": "ITSD", "projectName": "IT"}],
            "isLastPage": True,
        },
    )


# --- gadgets -----------------------------------------------------------------------------------

PIE_URI = (
    "rest/gadgets/1.0/g/com.atlassian.jira.gadgets:pie-chart-gadget/gadgets/piechart-gadget.xml"
)
REPORT_KEY = "com.atlassian.servicedesk.servicedesk-reports-plugin:custom-report-dashboard-item"
DIRECTORY = [
    {"uri": PIE_URI},
    {"moduleKey": REPORT_KEY},
]


def test_gadget_reference_uses_uri_or_module_key() -> None:
    assert gadget_reference(DIRECTORY, "pie_chart") == {"uri": DIRECTORY[0]["uri"]}
    assert gadget_reference(DIRECTORY, "service_project_report") == {
        "moduleKey": DIRECTORY[1]["moduleKey"]
    }
    assert gadget_reference(DIRECTORY, "heat_map") is None


async def test_dashboard_skips_missing_gadgets_instead_of_failing(
    ctx: HandlerContext, fake_atlassian: FakeAtlassian
) -> None:
    fake_atlassian.add("GET", "/rest/api/3/dashboard/search", json={"values": [], "isLast": True})
    fake_atlassian.add("GET", "/rest/api/3/dashboard/gadgets", json={"gadgets": DIRECTORY})
    fake_atlassian.add("POST", "/rest/api/3/dashboard", json={"id": "77", "name": "SD"})
    fake_atlassian.add("POST", "/rest/api/3/dashboard/77/gadget", json={"id": 1})
    fake_atlassian.add("GET", "/rest/api/3/dashboard/77", json={"id": "77", "name": "SD"})
    fake_atlassian.add("GET", "/rest/api/3/dashboard/77/gadget", json={"gadgets": [{"id": 1}]})
    params = {"name": "SD", "gadgets": [{"type": "pie_chart"}, {"type": "heat_map"}]}
    outcome = await JiraAgent(ctx).run(req("jira.create_dashboard", params))
    assert outcome.succeeded, outcome.message
    sent = body(fake_atlassian.calls_to("/rest/api/3/dashboard/77/gadget", "POST")[0])
    assert "uri" in sent and "moduleKey" not in sent
    assert "heat_map (not installed on this site)" in outcome.message
    verified = await VerificationAgent(ctx, 0).run(
        VerificationRequest(operation="jira.create_dashboard", params=params, outcome=outcome)
    )
    assert verified.verified, verified


# --- JSM request types --------------------------------------------------------------------------


async def test_request_type_creation_sends_experimental_header(
    ctx: HandlerContext, fake_atlassian: FakeAtlassian
) -> None:
    desk(fake_atlassian)
    site = StatefulSite(fake_atlassian)
    site.projects["ITSD"] = {
        "id": "10",
        "key": "ITSD",
        "name": "IT",
        "issueTypes": [{"id": "5", "name": "[System] Incident"}],
    }
    desk(fake_atlassian)
    fake_atlassian.set(
        "GET",
        "/rest/servicedeskapi/servicedesk",
        json={
            "values": [{"id": "9", "projectId": "10", "projectKey": "ITSD", "projectName": "IT"}],
            "isLastPage": True,
        },
    )
    fake_atlassian.add(
        "GET",
        "/rest/servicedeskapi/servicedesk/9/requesttype",
        json={"values": [], "isLastPage": True},
    )
    fake_atlassian.add("POST", "/rest/servicedeskapi/servicedesk/9/requesttype", json={"id": "301"})
    outcome = await JsmAgent(ctx).run(
        req(
            "jsm.create_request_type",
            {"service_desk": "ITSD", "name": "Report incident", "issue_type": "Incident"},
        )
    )
    assert outcome.succeeded, outcome.message
    call = fake_atlassian.calls_to("/rest/servicedeskapi/servicedesk/9/requesttype", "POST")[0]
    assert call.headers["X-ExperimentalApi"] == "opt-in"


# --- Forms -------------------------------------------------------------------------------------


async def test_create_form_builds_design_and_publishes_on_portal(
    ctx: HandlerContext, fake_atlassian: FakeAtlassian
) -> None:
    desk(fake_atlassian)
    fake_atlassian.add("GET", "/_edge/tenant_info", json={"cloudId": "cloud-1"})
    fake_atlassian.add(
        "GET",
        "/rest/servicedeskapi/servicedesk/9/requesttype",
        json={"values": [{"id": "301", "name": "Get new laptop"}], "isLastPage": True},
    )
    fake_atlassian.add("GET", FORMS, json=[])
    fake_atlassian.add("POST", FORMS, json={"id": "f-1"})
    params = {
        "service_desk": "ITSD",
        "name": "Laptop request",
        "request_types": ["Get new laptop"],
        "questions": [
            {"label": "Full name", "type": "short_text", "required": True},
            {"label": "Model", "type": "dropdown", "choices": ["MacBook", "ThinkPad"]},
            {"label": "Needed by", "type": "date"},
        ],
    }
    outcome = await JsmAgent(ctx).run(req("jsm.create_form", params))
    assert outcome.succeeded, outcome.message
    call = fake_atlassian.calls_to(FORMS, "POST")[0]
    assert call.url.host == "api.atlassian.com"
    sent = body(call)
    questions = sent["design"]["questions"]
    assert [q["type"] for q in questions.values()] == ["ts", "cd", "da"]
    assert questions["1"]["validation"] == {"rq": True}
    assert [c["label"] for c in questions["2"]["choices"]] == ["MacBook", "ThinkPad"]
    layout_ids = [n["attrs"]["parameters"]["id"] for n in sent["design"]["layout"][0]["content"]]
    assert layout_ids == [1, 2, 3]
    assert sent["publish"]["portal"]["portalRequestTypeIds"] == [301]

    fake_atlassian.add(
        "GET",
        f"{FORMS}/f-1",
        json={
            "design": {"settings": {"name": "Laptop request"}, "questions": questions},
            "publish": {"portal": {"portalRequestTypeIds": [301]}},
        },
    )
    verified = await VerificationAgent(ctx, 0).run(
        VerificationRequest(operation="jsm.create_form", params=params, outcome=outcome)
    )
    assert verified.verified, verified


async def test_choice_question_without_choices_is_rejected(
    ctx: HandlerContext, fake_atlassian: FakeAtlassian
) -> None:
    desk(fake_atlassian)
    fake_atlassian.add("GET", "/_edge/tenant_info", json={"cloudId": "cloud-1"})
    fake_atlassian.add("GET", FORMS, json=[])
    outcome = await JsmAgent(ctx).run(
        req(
            "jsm.create_form",
            {
                "service_desk": "ITSD",
                "name": "x",
                "questions": [{"label": "Pick", "type": "dropdown"}],
            },
        )
    )
    assert outcome.error_code == "operation_invalid_input"
    assert fake_atlassian.calls_to(FORMS, "POST") == []


# --- Assets ------------------------------------------------------------------------------------


class FakeAssets:
    def __init__(self, fake: FakeAtlassian) -> None:
        self.schemas: list[dict[str, Any]] = []
        self.types: list[dict[str, Any]] = []
        self.attrs: dict[str, list[dict[str, Any]]] = {}
        self.objects: list[dict[str, Any]] = []
        fake.add(
            "GET",
            "/rest/servicedeskapi/assets/workspace",
            json={"values": [{"workspaceId": "ws-1"}]},
        )
        fake.add_handler(
            "GET",
            f"{ASSETS}/objectschema/list",
            lambda r: httpx.Response(200, json={"values": self.schemas}),
        )
        fake.add_handler("POST", f"{ASSETS}/objectschema/create", self._schema)
        fake.add_pattern(
            "GET",
            f"{ASSETS}/objectschema/(\\d+)/objecttypes/flat",
            lambda r, sid: httpx.Response(200, json=[t for t in self.types if t["schema"] == sid]),
        )
        fake.add("GET", f"{ASSETS}/icon/global", json=[{"id": "13", "name": "Laptop"}])
        fake.add_handler("POST", f"{ASSETS}/objecttype/create", self._type)
        fake.add_pattern(
            "GET",
            f"{ASSETS}/objecttype/(\\d+)/attributes",
            lambda r, tid: httpx.Response(200, json=self.attrs.get(tid, [])),
        )
        fake.add_pattern("POST", f"{ASSETS}/objecttypeattribute/(\\d+)", self._attr)
        fake.add_handler("POST", f"{ASSETS}/object/aql", self._aql)
        fake.add_handler("POST", f"{ASSETS}/object/create", self._object)

    def _schema(self, r: httpx.Request) -> httpx.Response:
        data = body(r)
        s = {
            "id": str(len(self.schemas) + 1),
            "name": data["name"],
            "objectSchemaKey": data["objectSchemaKey"],
        }
        self.schemas.append(s)
        return httpx.Response(201, json=s)

    def _type(self, r: httpx.Request) -> httpx.Response:
        data = body(r)
        t = {
            "id": str(100 + len(self.types)),
            "name": data["name"],
            "schema": data["objectSchemaId"],
            "parent": data.get("parentObjectTypeId"),
        }
        self.types.append(t)
        self.attrs[t["id"]] = [
            {"id": f"{t['id']}-1", "name": "Name"},
            {"id": f"{t['id']}-2", "name": "Key"},
        ]
        return httpx.Response(201, json=t)

    def _attr(self, r: httpx.Request, tid: str) -> httpx.Response:
        data = body(r)
        a = {"id": f"{tid}-{len(self.attrs[tid]) + 1}", "name": data["name"], **data}
        self.attrs[tid].append(a)
        return httpx.Response(201, json=a)

    def _aql(self, r: httpx.Request) -> httpx.Response:
        query = body(r)["qlQuery"]
        hits = [
            o
            for o in self.objects
            if f'Name = "{o["name"]}"' in query and f"objectTypeId = {o['type']}" in query
        ]
        return httpx.Response(200, json={"values": hits})

    def _object(self, r: httpx.Request) -> httpx.Response:
        data = body(r)
        name_attr = f"{data['objectTypeId']}-1"
        name = next(
            a["objectAttributeValues"][0]["value"]
            for a in data["attributes"]
            if a["objectTypeAttributeId"] == name_attr
        )
        o = {
            "id": str(len(self.objects) + 1),
            "objectKey": f"ITAM-{len(self.objects) + 1}",
            "name": name,
            "type": data["objectTypeId"],
        }
        self.objects.append(o)
        return httpx.Response(201, json=o)


async def test_assets_schema_types_attributes_and_objects(
    ctx: HandlerContext, fake_atlassian: FakeAtlassian
) -> None:
    assets = FakeAssets(fake_atlassian)
    agent = JsmAgent(ctx)
    schema_params = {
        "name": "IT Assets",
        "key": "ITAM",
        "object_types": [
            {"name": "Hardware"},
            {
                "name": "Laptop",
                "parent": "Hardware",
                "attributes": [
                    {"name": "Serial number"},
                    {"name": "Status", "type": "select", "options": ["In use", "Spare"]},
                ],
            },
        ],
    }
    schema = await agent.run(req("assets.create_schema", schema_params))
    assert schema.succeeded, schema.message
    laptop = next(t for t in assets.types if t["name"] == "Laptop")
    assert laptop["parent"] == next(t for t in assets.types if t["name"] == "Hardware")["id"]
    status = next(a for a in assets.attrs[laptop["id"]] if a["name"] == "Status")
    assert status["defaultTypeId"] == 10 and status["options"] == "In use,Spare"
    assert (
        await VerificationAgent(ctx, 0).run(
            VerificationRequest(
                operation="assets.create_schema", params=schema_params, outcome=schema
            )
        )
    ).verified

    again = await agent.run(req("assets.create_schema", schema_params))
    assert again.reused_existing and len(assets.types) == 2

    objects_params = {
        "schema_key": "ITAM",
        "object_type": "Laptop",
        "objects": [
            {"attributes": {"Name": "LT-001", "Serial number": "C02X", "Status": "In use"}},
            {"attributes": {"Name": "LT-002", "Status": "Spare"}},
        ],
    }
    created = await agent.run(req("assets.create_objects", objects_params))
    assert created.succeeded, created.message
    assert created.outputs["object_keys"] == ["ITAM-1", "ITAM-2"]
    assert (
        await VerificationAgent(ctx, 0).run(
            VerificationRequest(
                operation="assets.create_objects", params=objects_params, outcome=created
            )
        )
    ).verified
    repeat = await agent.run(req("assets.create_objects", objects_params))
    assert repeat.reused_existing and len(assets.objects) == 2


async def test_unknown_asset_attribute_is_reported(
    ctx: HandlerContext, fake_atlassian: FakeAtlassian
) -> None:
    FakeAssets(fake_atlassian)
    agent = JsmAgent(ctx)
    await agent.run(
        req(
            "assets.create_schema",
            {"name": "IT", "key": "ITAM", "object_types": [{"name": "Laptop"}]},
        )
    )
    outcome = await agent.run(
        req(
            "assets.create_objects",
            {
                "schema_key": "ITAM",
                "object_type": "Laptop",
                "objects": [{"attributes": {"Name": "x", "Colour": "red"}}],
            },
        )
    )
    assert outcome.error_code == "operation_invalid_input" and "colour" in outcome.message


async def test_assets_permission_denied_shows_in_probe(
    ctx: HandlerContext, fake_atlassian: FakeAtlassian
) -> None:
    from app.services.atlassian_probe import AtlassianProbe

    fake_atlassian.add(
        "GET", "/rest/servicedeskapi/assets/workspace", json={"values": [{"workspaceId": "ws-1"}]}
    )
    fake_atlassian.add(
        "GET",
        f"{ASSETS}/objectschema/list",
        status=403,
        json={"message": "Access to Assets API was denied"},
    )
    status = await AtlassianProbe()._probe_assets(ctx.clients, jsm_available=True)
    assert not status.available and "Premium" in status.detail


# --- LLM pacing --------------------------------------------------------------------------------


async def test_rate_limiter_spaces_requests() -> None:
    limiter = RateLimiter(per_minute=2, window_seconds=0.3)
    start = time.monotonic()
    for _ in range(3):
        await limiter.acquire()
    assert time.monotonic() - start >= 0.25
    assert not RateLimiter(0).enabled


def test_priority_icon_follows_name() -> None:
    from app.agents.handlers.jira_config import priority_icon

    assert priority_icon("Critical (P1)").endswith("highest_new")
    assert priority_icon("High (P2)").endswith("high_new")
    assert priority_icon("Medium (P3)").endswith("medium_new")
    assert priority_icon("Low (P4)").endswith("low_new")
    assert priority_icon("Lowest").endswith("lowest_new")


# --- workflow schemes & updates ---------------------------------------------------------------


def _workflows_response(request: httpx.Request) -> httpx.Response:
    names = body(request)["workflowNames"]
    all_wf = {
        "Old WF": {
            "id": "w-old",
            "name": "Old WF",
            "version": {"id": "v", "versionNumber": 1},
            "statuses": [{"statusReference": "1"}, {"statusReference": "3"}],
            "transitions": [
                {"id": "1", "type": "INITIAL", "name": "Create", "toStatusReference": "1"}
            ],
        },
        "Incident WF": {
            "id": "w-inc",
            "name": "Incident WF",
            "version": {"id": "v2", "versionNumber": 3},
            "statuses": [
                {"statusReference": "10"},
                {"statusReference": "11"},
                {"statusReference": "12"},
            ],
            "transitions": [
                {"id": "1", "type": "INITIAL", "name": "Create", "toStatusReference": "10"},
                {
                    "id": "11",
                    "type": "DIRECTED",
                    "name": "Resolve",
                    "toStatusReference": "12",
                    "links": [{"fromStatusReference": "11"}],
                },
            ],
        },
    }
    statuses = [
        {"id": "1", "statusReference": "1", "name": "Open", "statusCategory": "TODO"},
        {"id": "3", "statusReference": "3", "name": "Done", "statusCategory": "DONE"},
        {"id": "10", "statusReference": "10", "name": "New", "statusCategory": "TODO"},
        {
            "id": "11",
            "statusReference": "11",
            "name": "In Progress",
            "statusCategory": "IN_PROGRESS",
        },
        {"id": "12", "statusReference": "12", "name": "Resolved", "statusCategory": "DONE"},
    ]
    return httpx.Response(
        200, json={"workflows": [all_wf[n] for n in names if n in all_wf], "statuses": statuses}
    )


async def test_configure_scheme_switches_project_with_issues(
    ctx: HandlerContext, fake_atlassian: FakeAtlassian
) -> None:
    fake_atlassian.add(
        "GET",
        "/rest/api/3/project/EITSD",
        json={
            "id": "10239",
            "key": "EITSD",
            "issueTypes": [{"id": "10196", "name": "Incident"}, {"id": "10004", "name": "Task"}],
        },
    )
    fake_atlassian.add(
        "GET",
        "/rest/api/3/workflowscheme/project",
        json={"values": [{"workflowScheme": {"id": "500"}}]},
    )
    fake_atlassian.add(
        "GET",
        "/rest/api/3/workflowscheme/500",
        json={"id": "500", "defaultWorkflow": "jira", "issueTypeMappings": {"10196": "Old WF"}},
    )
    fake_atlassian.add("GET", "/rest/api/3/workflowscheme", json={"values": [], "isLast": True})
    fake_atlassian.add("POST", "/rest/api/3/workflowscheme", json={"id": 600})
    fake_atlassian.add("POST", "/rest/api/3/search/approximate-count", json={"count": 9})
    fake_atlassian.add_handler("POST", "/rest/api/3/workflows", _workflows_response)
    # Live Jira answers 303 with an empty body and the task URL in Location.
    fake_atlassian.add_handler(
        "POST",
        "/rest/api/3/workflowscheme/project/switch",
        lambda r: httpx.Response(
            303, headers={"Location": "https://acme.atlassian.net/rest/api/3/task/t1"}
        ),
    )
    fake_atlassian.add("GET", "/rest/api/3/task/t1", json={"status": "COMPLETE"})
    outcome = await JiraAgent(ctx).run(
        req(
            "jira.configure_workflow_scheme",
            {
                "project_key": "EITSD",
                "mappings": [{"workflow_name": "Incident WF", "issue_types": ["Incident"]}],
            },
        )
    )
    assert outcome.succeeded, outcome.message
    created = body(fake_atlassian.calls_to("/rest/api/3/workflowscheme", "POST")[0])
    assert (
        created["issueTypeMappings"] == {"10196": "Incident WF"}
        and created["defaultWorkflow"] == "jira"
    )
    switch = body(fake_atlassian.calls_to("/rest/api/3/workflowscheme/project/switch", "POST")[0])
    assert switch["targetSchemeId"] == "600"
    # Open (TODO) -> New (initial); Done (DONE) -> Resolved
    assert switch["mappingsByIssueTypeOverride"] == [
        {
            "issueTypeId": "10196",
            "statusMappings": [
                {"oldStatusId": "1", "newStatusId": "10"},
                {"oldStatusId": "3", "newStatusId": "12"},
            ],
        }
    ]
    assert outcome.outputs["previous_scheme_id"] == "500"


async def test_update_workflow_adds_transition_after_validation(
    ctx: HandlerContext, fake_atlassian: FakeAtlassian
) -> None:
    fake_atlassian.add_handler("POST", "/rest/api/3/workflows", _workflows_response)
    fake_atlassian.add("POST", "/rest/api/3/workflows/update/validation", json={"errors": []})
    fake_atlassian.add("POST", "/rest/api/3/workflows/update", json={"workflows": []})
    outcome = await JiraAgent(ctx).run(
        req(
            "jira.update_workflow",
            {
                "workflow_name": "Incident WF",
                "add_transitions": [
                    {"name": "Reopen", "from_statuses": ["Resolved"], "to_status": "In Progress"}
                ],
            },
        )
    )
    assert outcome.succeeded, outcome.message
    payload = body(fake_atlassian.calls_to("/rest/api/3/workflows/update", "POST")[0])
    wf = payload["workflows"][0]
    assert wf["version"] == {"id": "v2", "versionNumber": 3}
    reopen = wf["transitions"][-1]
    assert reopen["name"] == "Reopen" and reopen["id"] == "21"
    assert (
        reopen["links"] == [{"fromStatusReference": "12"}] and reopen["toStatusReference"] == "11"
    )
