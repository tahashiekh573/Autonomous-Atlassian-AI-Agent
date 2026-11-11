"""In-process fakes of Atlassian Cloud, the LLM and speech providers — unit tests only."""

import json
import re
from collections.abc import Callable
from typing import Any

import httpx

from app.clients.llm.base import LLMClient
from app.clients.speech.base import SpeechToText

Responder = Callable[[httpx.Request], httpx.Response]

SITE_URL = "https://acme.atlassian.net"


class FakeAtlassian:
    def __init__(self) -> None:
        self._routes: dict[tuple[str, str], list[Responder]] = {}
        self._patterns: list[tuple[str, re.Pattern[str], Callable[..., httpx.Response]]] = []
        self.calls: list[httpx.Request] = []

    def add(
        self,
        method: str,
        path: str,
        status: int = 200,
        json: Any = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        """Queue a canned response. The last queued response for a route repeats forever."""
        self.add_handler(
            method, path, lambda _req: httpx.Response(status, json=json, headers=headers)
        )

    def set(self, method: str, path: str, status: int = 200, json: Any = None) -> None:
        """Replace any queued responses for a route."""
        self._routes.pop((method.upper(), path), None)
        self.add(method, path, status, json)

    def add_handler(self, method: str, path: str, responder: Responder) -> None:
        self._routes.setdefault((method.upper(), path), []).append(responder)

    def add_pattern(
        self, method: str, pattern: str, responder: Callable[..., httpx.Response]
    ) -> None:
        """Responder receives (request, *regex_groups)."""
        self._patterns.append((method.upper(), re.compile(f"^{pattern}$"), responder))

    def calls_to(self, path: str, method: str | None = None) -> list[httpx.Request]:
        return [
            c for c in self.calls if c.url.path == path and (method is None or c.method == method)
        ]

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        queue = self._routes.get((request.method, request.url.path))
        if queue:
            responder = queue.pop(0) if len(queue) > 1 else queue[0]
            return responder(request)
        for method, regex, responder in self._patterns:
            match = regex.match(request.url.path)
            if method == request.method and match:
                return responder(request, *match.groups())
        return httpx.Response(404, json={"errorMessages": ["no fake route"]})

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)


def body(request: httpx.Request) -> Any:
    return json.loads(request.content or b"null")


def add_healthy_site(fake: FakeAtlassian, *, admin: bool = True) -> None:
    fake.add(
        "GET",
        "/rest/api/3/myself",
        json={"accountId": "acc-1", "displayName": "Ada Admin", "emailAddress": "ada@acme.com"},
    )
    fake.add(
        "GET",
        "/rest/api/3/serverInfo",
        json={"baseUrl": SITE_URL, "version": "1001.0.0", "deploymentType": "Cloud"},
    )
    fake.add(
        "GET",
        "/rest/api/3/mypermissions",
        json={
            "permissions": {
                "ADMINISTER": {"havePermission": admin},
                "BROWSE_PROJECTS": {"havePermission": True},
                "CREATE_ISSUES": {"havePermission": True},
            }
        },
    )
    fake.add("GET", "/rest/servicedeskapi/info", json={"version": "10.0.0"})
    fake.add(
        "GET",
        "/rest/servicedeskapi/servicedesk",
        json={
            "values": [
                {"id": "1", "projectId": "10000", "projectKey": "ITSD", "projectName": "IT SD"}
            ],
            "isLastPage": True,
        },
    )
    fake.add(
        "GET",
        "/wiki/api/v2/spaces",
        json={"results": [{"id": "98", "key": "KB", "name": "Knowledge Base"}], "_links": {}},
    )


class StatefulSite:
    """A tiny in-memory Jira + Confluence that remembers what was created."""

    def __init__(self, fake: FakeAtlassian) -> None:
        self.projects: dict[str, dict[str, Any]] = {}
        self.issues: dict[str, dict[str, Any]] = {}
        self.spaces: dict[str, dict[str, Any]] = {}
        self.pages: dict[str, dict[str, Any]] = {}
        self.labels: dict[str, list[str]] = {}
        self._ids = 7000
        fake.add(
            "GET", "/rest/api/3/myself", json={"accountId": "acc-1", "displayName": "Ada Admin"}
        )
        fake.add(
            "GET", "/rest/api/3/serverInfo", json={"baseUrl": SITE_URL, "deploymentType": "Cloud"}
        )
        fake.add(
            "GET",
            "/rest/api/3/mypermissions",
            json={"permissions": {"ADMINISTER": {"havePermission": True}}},
        )
        fake.add("GET", "/rest/servicedeskapi/info", json={"version": "10.0.0"})
        fake.add("GET", "/rest/servicedeskapi/servicedesk", json={"values": [], "isLastPage": True})
        fake.add_handler("GET", "/rest/api/3/project/search", self._project_search)
        fake.add_handler("POST", "/rest/api/3/project", self._create_project)
        fake.add_pattern("GET", r"/rest/api/3/project/([^/]+)", self._get_project)
        fake.add_handler("POST", "/rest/api/3/search/jql", self._search)
        fake.add_handler("POST", "/rest/api/3/issue", self._create_issue)
        fake.add_pattern("GET", r"/rest/api/3/issue/([^/]+)", self._get_issue)
        fake.add_pattern("DELETE", r"/rest/api/3/issue/([^/]+)", self._delete_issue)
        fake.add_handler("GET", "/wiki/api/v2/spaces", self._get_spaces)
        fake.add_handler("POST", "/wiki/rest/api/space", self._create_space)
        fake.add_handler("GET", "/wiki/api/v2/pages", self._find_pages)
        fake.add_handler("POST", "/wiki/api/v2/pages", self._create_page)
        fake.add_pattern("GET", r"/wiki/api/v2/pages/(\d+)", self._get_page)
        fake.add_pattern("GET", r"/wiki/api/v2/pages/(\d+)/labels", self._get_labels)
        fake.add_pattern("POST", r"/wiki/rest/api/content/(\d+)/label", self._add_labels)

    def _next(self) -> str:
        self._ids += 1
        return str(self._ids)

    # --- jira ---
    def _project_search(self, _: httpx.Request) -> httpx.Response:
        values = [{"id": p["id"], "key": k, "name": p["name"]} for k, p in self.projects.items()]
        return httpx.Response(200, json={"values": values, "isLast": True})

    def _create_project(self, request: httpx.Request) -> httpx.Response:
        data = body(request)
        project = {
            "id": self._next(),
            "key": data["key"],
            "name": data["name"],
            "projectTypeKey": data["projectTypeKey"],
            "description": data.get("description", ""),
            "style": "classic",
            "issueTypes": [{"id": "1", "name": "Task"}, {"id": "2", "name": "Bug"}],
        }
        self.projects[data["key"]] = project
        return httpx.Response(201, json={"id": int(project["id"]), "key": data["key"]})

    def _get_project(self, _: httpx.Request, key: str) -> httpx.Response:
        if key not in self.projects:
            return httpx.Response(404, json={"errorMessages": ["No project could be found"]})
        return httpx.Response(200, json=self.projects[key])

    def _search(self, request: httpx.Request) -> httpx.Response:
        jql = body(request)["jql"]
        label = re.search(r'labels = "([^"]+)"', jql)
        issues = [
            i for i in self.issues.values() if label and label.group(1) in i["fields"]["labels"]
        ]
        return httpx.Response(200, json={"issues": issues, "isLast": True})

    def _create_issue(self, request: httpx.Request) -> httpx.Response:
        fields = body(request)["fields"]
        key = f"{fields['project']['key']}-{len(self.issues) + 1}"
        self.issues[key] = {
            "id": self._next(),
            "key": key,
            "fields": {
                "summary": fields["summary"],
                "issuetype": fields["issuetype"],
                "labels": fields.get("labels", []),
                "parent": fields.get("parent"),
                "description": fields.get("description"),
                "issuelinks": [],
                "subtasks": [],
            },
        }
        return httpx.Response(201, json={"id": self.issues[key]["id"], "key": key})

    def _get_issue(self, _: httpx.Request, key: str) -> httpx.Response:
        if key not in self.issues:
            return httpx.Response(404, json={"errorMessages": ["Issue does not exist"]})
        return httpx.Response(200, json=self.issues[key])

    def _delete_issue(self, _: httpx.Request, key: str) -> httpx.Response:
        self.issues.pop(key, None)
        return httpx.Response(204)

    # --- confluence ---
    def _get_spaces(self, request: httpx.Request) -> httpx.Response:
        keys = request.url.params.get("keys")
        spaces = [s for k, s in self.spaces.items() if keys is None or k == keys]
        return httpx.Response(200, json={"results": spaces, "_links": {}})

    def _create_space(self, request: httpx.Request) -> httpx.Response:
        data = body(request)
        home = self._next()
        space = {"id": self._next(), "key": data["key"], "name": data["name"], "homepageId": home}
        self.spaces[data["key"]] = space
        self.pages[home] = {
            "id": home,
            "title": f"{data['name']} Home",
            "spaceId": space["id"],
            "status": "current",
            "body": {"storage": {"value": "<p>Home</p>"}},
        }
        return httpx.Response(
            200, json={"id": int(space["id"]), "key": data["key"], "name": data["name"]}
        )

    def _find_pages(self, request: httpx.Request) -> httpx.Response:
        params = request.url.params
        found = [
            p
            for p in self.pages.values()
            if p["spaceId"] == params.get("space-id") and p["title"] == params.get("title")
        ]
        return httpx.Response(200, json={"results": found, "_links": {}})

    def _create_page(self, request: httpx.Request) -> httpx.Response:
        data = body(request)
        page_id = self._next()
        page = {
            "id": page_id,
            "title": data["title"],
            "spaceId": data["spaceId"],
            "parentId": data.get("parentId"),
            "status": "current",
            "version": {"number": 1},
            "body": {"storage": {"value": data["body"]["value"]}},
            "_links": {"webui": f"/spaces/X/pages/{page_id}"},
        }
        self.pages[page_id] = page
        return httpx.Response(200, json=page)

    def _get_page(self, _: httpx.Request, page_id: str) -> httpx.Response:
        if page_id not in self.pages:
            return httpx.Response(404, json={"errors": [{"title": "Not found"}]})
        return httpx.Response(200, json=self.pages[page_id])

    def _get_labels(self, _: httpx.Request, page_id: str) -> httpx.Response:
        return httpx.Response(
            200, json={"results": [{"name": n} for n in self.labels.get(page_id, [])], "_links": {}}
        )

    def _add_labels(self, request: httpx.Request, page_id: str) -> httpx.Response:
        self.labels.setdefault(page_id, []).extend(lbl["name"] for lbl in body(request))
        return httpx.Response(200, json={"results": []})


# --- LLM / speech fakes ----------------------------------------------------------------------


class FakeLLM(LLMClient):
    """Answers by agent role (detected from the system prompt) with scripted outputs."""

    provider = "fake"
    model = "fake-1"

    def __init__(self) -> None:
        self.intent: dict[str, Any] = {
            "language": "en",
            "normalized_instruction": "Do it",
            "products": ["jira"],
            "is_actionable": True,
        }
        self.plan: dict[str, Any] = {"summary": "Nothing", "operations": []}
        self.narrative: dict[str, Any] = {"summary": "All done.", "next_steps": []}
        self.page_body = "<h2>Overview</h2><p>Generated &amp; verified.</p>"
        self.prompts: list[tuple[str, str]] = []
        self.invalid_first: set[str] = set()
        self.expansions: list[dict[str, Any]] = []
        self.param_fixes: list[dict[str, Any]] = []

    async def generate(self, *, system: str, prompt: str, json_mode: bool = False) -> str:
        self.prompts.append((system[:60], prompt))
        if "Input Understanding Agent" in system:
            role, payload = "understanding", self.intent
        elif "Planning Agent" in system and "Steps with invalid params" in prompt:
            role, payload = "repair", {"fixes": self.param_fixes}
        elif "Planning Agent" in system and (
            "## Current plan" in prompt
            or "Section to plan now" in prompt
            or "Steps already planned for this section" in prompt
        ):
            role = "expansion"
            payload = (
                self.expansions.pop(0) if self.expansions else {"operations": [], "complete": True}
            )
        elif "Planning Agent" in system:
            role, payload = "planning", self.plan
        elif "Response Agent" in system:
            role, payload = "response", self.narrative
        else:
            return self.page_body
        if role in self.invalid_first:
            self.invalid_first.discard(role)
            return '{"oops": true}'
        return json.dumps(payload)


class FakeSTT(SpeechToText):
    provider = "fake"

    def __init__(self, text: str = "Jira mein ek Scrum project banao") -> None:
        self.text = text

    async def transcribe(self, audio: bytes, mime_type: str) -> str:
        return self.text
