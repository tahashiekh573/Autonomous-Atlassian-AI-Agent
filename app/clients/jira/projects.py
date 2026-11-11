"""Jira projects and users."""

from typing import Any

from app.clients.atlassian.http_client import AtlassianHttpClient
from app.clients.atlassian.paths import seg
from app.clients.jira.types import JiraProject
from app.core.exceptions import AtlassianNotFoundError

SERVICE = "jira"


class JiraProjectsMixin:
    _http: AtlassianHttpClient

    async def list_projects(self, *, max_items: int | None = None) -> list[JiraProject]:
        return [
            JiraProject.model_validate(item)
            async for item in self._http.paginate_offset(
                "/rest/api/3/project/search",
                service=SERVICE,
                params={"expand": "issueTypes"},
                max_items=max_items,
            )
        ]

    async def get_project(self, key_or_id: str) -> dict[str, Any]:
        body: dict[str, Any] = await self._http.request(
            "GET", f"/rest/api/3/project/{seg(key_or_id)}", service=SERVICE
        )
        return body

    async def find_project(self, key_or_id: str) -> dict[str, Any] | None:
        try:
            return await self.get_project(key_or_id)
        except AtlassianNotFoundError:
            return None

    async def create_project(self, payload: dict[str, Any]) -> dict[str, Any]:
        body: dict[str, Any] = await self._http.request(
            "POST", "/rest/api/3/project", service=SERVICE, json=payload
        )
        return body

    async def update_project(self, key: str, payload: dict[str, Any]) -> dict[str, Any]:
        body: dict[str, Any] = await self._http.request(
            "PUT", f"/rest/api/3/project/{seg(key)}", service=SERVICE, json=payload
        )
        return body

    async def find_users(self, query: str) -> list[dict[str, Any]]:
        body: list[dict[str, Any]] = await self._http.request(
            "GET", "/rest/api/3/user/search", service=SERVICE, params={"query": query}
        )
        return body
