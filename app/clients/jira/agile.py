"""Jira Software Agile API: filters, boards, sprints, backlog."""

from typing import Any

from app.clients.atlassian.http_client import AtlassianHttpClient
from app.clients.atlassian.paths import seg

SERVICE = "jira"


class JiraAgileMixin:
    _http: AtlassianHttpClient

    # Filters live in the platform API but are the data source for every board.
    async def create_filter(self, payload: dict[str, Any]) -> dict[str, Any]:
        body: dict[str, Any] = await self._http.request(
            "POST", "/rest/api/3/filter", service=SERVICE, json=payload
        )
        return body

    async def get_filter(self, filter_id: str) -> dict[str, Any]:
        body: dict[str, Any] = await self._http.request(
            "GET", f"/rest/api/3/filter/{seg(filter_id)}", service=SERVICE
        )
        return body

    async def search_filters(self, name: str) -> list[dict[str, Any]]:
        return [
            item
            async for item in self._http.paginate_offset(
                "/rest/api/3/filter/search",
                service=SERVICE,
                params={"filterName": name, "expand": "jql"},
            )
        ]

    async def create_board(self, payload: dict[str, Any]) -> dict[str, Any]:
        body: dict[str, Any] = await self._http.request(
            "POST", "/rest/agile/1.0/board", service=SERVICE, json=payload
        )
        return body

    async def get_board(self, board_id: str) -> dict[str, Any]:
        body: dict[str, Any] = await self._http.request(
            "GET", f"/rest/agile/1.0/board/{seg(board_id)}", service=SERVICE
        )
        return body

    async def get_board_configuration(self, board_id: str) -> dict[str, Any]:
        body: dict[str, Any] = await self._http.request(
            "GET", f"/rest/agile/1.0/board/{seg(board_id)}/configuration", service=SERVICE
        )
        return body

    async def find_boards(self, project_key: str, name: str | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"projectKeyOrId": project_key}
        if name:
            params["name"] = name
        return [
            item
            async for item in self._http.paginate_offset(
                "/rest/agile/1.0/board", service=SERVICE, params=params
            )
        ]

    async def create_sprint(self, payload: dict[str, Any]) -> dict[str, Any]:
        body: dict[str, Any] = await self._http.request(
            "POST", "/rest/agile/1.0/sprint", service=SERVICE, json=payload
        )
        return body

    async def get_sprint(self, sprint_id: str) -> dict[str, Any]:
        body: dict[str, Any] = await self._http.request(
            "GET", f"/rest/agile/1.0/sprint/{seg(sprint_id)}", service=SERVICE
        )
        return body

    async def update_sprint(self, sprint_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Partial update (POST semantics in the Agile API)."""
        body: dict[str, Any] = await self._http.request(
            "POST", f"/rest/agile/1.0/sprint/{seg(sprint_id)}", service=SERVICE, json=payload
        )
        return body

    async def list_sprints(self, board_id: str) -> list[dict[str, Any]]:
        return [
            item
            async for item in self._http.paginate_offset(
                f"/rest/agile/1.0/board/{seg(board_id)}/sprint", service=SERVICE
            )
        ]

    async def move_issues_to_backlog(self, issue_keys: list[str]) -> None:
        await self._http.request(
            "POST",
            "/rest/agile/1.0/backlog/issue",
            service=SERVICE,
            json={"issues": issue_keys},
            idempotent=True,
        )

    async def get_agile_issue(self, key: str, fields: str = "sprint,status") -> dict[str, Any]:
        body: dict[str, Any] = await self._http.request(
            "GET", f"/rest/agile/1.0/issue/{seg(key)}", service=SERVICE, params={"fields": fields}
        )
        return body

    async def move_issues_to_sprint(self, sprint_id: str, issue_keys: list[str]) -> None:
        await self._http.request(
            "POST",
            f"/rest/agile/1.0/sprint/{seg(sprint_id)}/issue",
            service=SERVICE,
            json={"issues": issue_keys},
            idempotent=True,
        )

    async def get_sprint_issues(
        self, sprint_id: str, fields: str = "status"
    ) -> list[dict[str, Any]]:
        return [
            item
            async for item in self._http.paginate_offset(
                f"/rest/agile/1.0/sprint/{seg(sprint_id)}/issue",
                service=SERVICE,
                params={"fields": fields},
                items_key="issues",
            )
        ]
