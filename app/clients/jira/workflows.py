"""Jira workflows and workflow schemes (bulk workflow API)."""

from typing import Any

from app.clients.atlassian.http_client import AtlassianHttpClient
from app.clients.atlassian.paths import seg

SERVICE = "jira"


class JiraWorkflowsMixin:
    _http: AtlassianHttpClient

    async def search_workflows(self, name: str) -> list[dict[str, Any]]:
        return [
            item
            async for item in self._http.paginate_offset(
                "/rest/api/3/workflows/search", service=SERVICE, params={"queryString": name}
            )
        ]

    async def validate_workflow_create(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        """Dry-run validation; returns the list of validation errors (may include warnings)."""
        body = await self._http.request(
            "POST",
            "/rest/api/3/workflows/create/validation",
            service=SERVICE,
            json={"payload": payload, "validationOptions": {"levels": ["ERROR", "WARNING"]}},
            idempotent=True,
        )
        return list((body or {}).get("errors") or [])

    async def create_workflows(self, payload: dict[str, Any]) -> dict[str, Any]:
        body: dict[str, Any] = await self._http.request(
            "POST", "/rest/api/3/workflows/create", service=SERVICE, json=payload
        )
        return body

    async def list_workflow_schemes(self) -> list[dict[str, Any]]:
        return [
            item
            async for item in self._http.paginate_offset(
                "/rest/api/3/workflowscheme", service=SERVICE
            )
        ]

    async def create_workflow_scheme(self, payload: dict[str, Any]) -> dict[str, Any]:
        body: dict[str, Any] = await self._http.request(
            "POST", "/rest/api/3/workflowscheme", service=SERVICE, json=payload
        )
        return body

    async def assign_workflow_scheme(self, scheme_id: str, project_id: str) -> None:
        """Only allowed while the project has no issues (Jira rejects otherwise)."""
        await self._http.request(
            "PUT",
            "/rest/api/3/workflowscheme/project",
            service=SERVICE,
            json={"workflowSchemeId": scheme_id, "projectId": project_id},
        )

    async def get_project_workflow_scheme(self, project_id: str) -> dict[str, Any] | None:
        body = await self._http.request(
            "GET",
            "/rest/api/3/workflowscheme/project",
            service=SERVICE,
            params={"projectId": project_id},
        )
        values = body.get("values") or []
        return values[0].get("workflowScheme") if values else None

    async def get_workflows_by_name(self, names: list[str]) -> dict[str, Any]:
        """Bulk get: {"workflows": [...with statuses/transitions/version], "statuses": [...]}."""
        body: dict[str, Any] = await self._http.request(
            "POST",
            "/rest/api/3/workflows",
            service=SERVICE,
            json={"workflowNames": names},
            idempotent=True,
        )
        return body

    async def get_issue_type_workflow(self, project_id: str, issue_type_id: str) -> dict[str, Any]:
        """Bulk get by project + issue type (how team-managed workflows are addressed)."""
        body: dict[str, Any] = await self._http.request(
            "POST",
            "/rest/api/3/workflows",
            service=SERVICE,
            json={
                "projectAndIssueTypes": [{"projectId": project_id, "issueTypeId": issue_type_id}]
            },
            idempotent=True,
        )
        return body

    async def validate_workflow_update(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        body = await self._http.request(
            "POST",
            "/rest/api/3/workflows/update/validation",
            service=SERVICE,
            json={"payload": payload, "validationOptions": {"levels": ["ERROR", "WARNING"]}},
            idempotent=True,
        )
        return list((body or {}).get("errors") or [])

    async def update_workflows(self, payload: dict[str, Any]) -> dict[str, Any]:
        body: dict[str, Any] = await self._http.request(
            "POST", "/rest/api/3/workflows/update", service=SERVICE, json=payload
        )
        return body

    async def get_workflow_scheme(self, scheme_id: str) -> dict[str, Any]:
        body: dict[str, Any] = await self._http.request(
            "GET", f"/rest/api/3/workflowscheme/{seg(scheme_id)}", service=SERVICE
        )
        return body

    async def switch_workflow_scheme(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Switch a project with issues to another scheme (async task, migrates statuses)."""
        body: dict[str, Any] = await self._http.request(
            "POST", "/rest/api/3/workflowscheme/project/switch", service=SERVICE, json=payload
        )
        return body

    async def get_task(self, task_id: str) -> dict[str, Any]:
        body: dict[str, Any] = await self._http.request(
            "GET", f"/rest/api/3/task/{seg(task_id)}", service=SERVICE
        )
        return body
