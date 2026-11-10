"""Confluence Cloud REST API client (v2 for reads and pages, v1 where v2 has no equivalent).

Docs: https://developer.atlassian.com/cloud/confluence/rest/v2/
      https://developer.atlassian.com/cloud/confluence/rest/v1/
"""

from typing import Any

from app.clients.atlassian.http_client import AtlassianHttpClient
from app.clients.atlassian.paths import seg
from app.clients.confluence.types import ConfluenceSpace
from app.core.exceptions import AtlassianNotFoundError

SERVICE = "confluence"
_V2 = "/wiki/api/v2"
_V1 = "/wiki/rest/api"


class ConfluenceClient:
    def __init__(self, http: AtlassianHttpClient) -> None:
        self._http = http

    # --- spaces ---------------------------------------------------------------------------
    async def list_spaces(self, *, max_items: int | None = None) -> list[ConfluenceSpace]:
        return [
            ConfluenceSpace.model_validate(item)
            async for item in self._http.paginate_cursor(
                f"{_V2}/spaces", service=SERVICE, params={"limit": 25}, max_items=max_items
            )
        ]

    async def get_space_by_key(self, key: str) -> dict[str, Any] | None:
        body = await self._http.request(
            "GET", f"{_V2}/spaces", service=SERVICE, params={"keys": key, "limit": 1}
        )
        results = body.get("results") or []
        return results[0] if results else None

    async def create_space(self, key: str, name: str, description: str) -> dict[str, Any]:
        body: dict[str, Any] = await self._http.request(
            "POST",
            f"{_V1}/space",
            service=SERVICE,
            json={
                "key": key,
                "name": name,
                "description": {"plain": {"value": description, "representation": "plain"}},
            },
        )
        return body

    async def update_space(self, key: str, payload: dict[str, Any]) -> dict[str, Any]:
        body: dict[str, Any] = await self._http.request(
            "PUT", f"{_V1}/space/{seg(key)}", service=SERVICE, json=payload
        )
        return body

    async def get_space_v1(self, key: str) -> dict[str, Any]:
        body: dict[str, Any] = await self._http.request(
            "GET",
            f"{_V1}/space/{seg(key)}",
            service=SERVICE,
            params={"expand": "description.plain,homepage"},
        )
        return body

    async def add_space_permission(self, key: str, payload: dict[str, Any]) -> dict[str, Any]:
        body: dict[str, Any] = await self._http.request(
            "POST", f"{_V1}/space/{seg(key)}/permission", service=SERVICE, json=payload
        )
        return body

    async def list_space_permissions(self, space_id: str) -> list[dict[str, Any]]:
        return [
            item
            async for item in self._http.paginate_cursor(
                f"{_V2}/spaces/{seg(space_id)}/permissions", service=SERVICE
            )
        ]

    # --- pages ----------------------------------------------------------------------------
    async def get_page(self, page_id: str, *, with_body: bool = True) -> dict[str, Any]:
        params = {"body-format": "storage"} if with_body else None
        body: dict[str, Any] = await self._http.request(
            "GET", f"{_V2}/pages/{seg(page_id)}", service=SERVICE, params=params
        )
        return body

    async def find_page(self, space_id: str, title: str) -> dict[str, Any] | None:
        body = await self._http.request(
            "GET",
            f"{_V2}/pages",
            service=SERVICE,
            params={"space-id": space_id, "title": title, "status": "current", "limit": 5},
        )
        for page in body.get("results") or []:
            if page.get("title") == title:
                return dict(page)
        return None

    async def create_page(
        self, space_id: str, title: str, storage_body: str, parent_id: str | None
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "spaceId": space_id,
            "status": "current",
            "title": title,
            "body": {"representation": "storage", "value": storage_body},
        }
        if parent_id:
            payload["parentId"] = parent_id
        body: dict[str, Any] = await self._http.request(
            "POST", f"{_V2}/pages", service=SERVICE, json=payload
        )
        return body

    async def update_page(
        self, page_id: str, title: str, storage_body: str, version: int, message: str
    ) -> dict[str, Any]:
        body: dict[str, Any] = await self._http.request(
            "PUT",
            f"{_V2}/pages/{seg(page_id)}",
            service=SERVICE,
            json={
                "id": page_id,
                "status": "current",
                "title": title,
                "body": {"representation": "storage", "value": storage_body},
                "version": {"number": version, "message": message},
            },
        )
        return body

    async def delete_page(self, page_id: str) -> None:
        """Moves the page to the space trash (recoverable)."""
        await self._http.request("DELETE", f"{_V2}/pages/{seg(page_id)}", service=SERVICE)

    async def page_exists(self, page_id: str) -> bool:
        try:
            page = await self.get_page(page_id, with_body=False)
        except AtlassianNotFoundError:
            return False
        return page.get("status") == "current"

    async def list_children(self, page_id: str) -> list[dict[str, Any]]:
        return [
            item
            async for item in self._http.paginate_cursor(
                f"{_V2}/pages/{seg(page_id)}/children", service=SERVICE
            )
        ]

    # --- labels ---------------------------------------------------------------------------
    async def add_labels(self, page_id: str, labels: list[str]) -> None:
        await self._http.request(
            "POST",
            f"{_V1}/content/{seg(page_id)}/label",
            service=SERVICE,
            json=[{"prefix": "global", "name": label} for label in labels],
            idempotent=True,
        )

    async def get_labels(self, page_id: str) -> list[str]:
        return [
            str(item.get("name"))
            async for item in self._http.paginate_cursor(
                f"{_V2}/pages/{seg(page_id)}/labels", service=SERVICE
            )
        ]
