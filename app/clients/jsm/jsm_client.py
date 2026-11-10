"""Jira Service Management REST API client.

Docs: https://developer.atlassian.com/cloud/jira/service-desk/rest/
Service projects themselves are created with the Jira platform project API.
"""

from collections.abc import AsyncIterator
from typing import Any

from app.clients.atlassian.http_client import AtlassianHttpClient
from app.clients.atlassian.paths import seg
from app.clients.jsm.types import JsmInfo, ServiceDesk

SERVICE = "jsm"
_BASE = "/rest/servicedeskapi"
_EXPERIMENTAL = {"X-ExperimentalApi": "opt-in"}


class JsmClient:
    def __init__(self, http: AtlassianHttpClient) -> None:
        self._http = http

    def _pages(
        self, path: str, params: dict[str, Any] | None = None
    ) -> AsyncIterator[dict[str, Any]]:
        return self._http.paginate_offset(
            path,
            service=SERVICE,
            params=params,
            start_param="start",
            limit_param="limit",
            last_page_key="isLastPage",
        )

    async def get_info(self) -> JsmInfo:
        body = await self._http.request("GET", f"{_BASE}/info", service=SERVICE)
        return JsmInfo.model_validate(body)

    # --- service desks ----------------------------------------------------------------------
    async def list_service_desks(self, *, max_items: int | None = None) -> list[ServiceDesk]:
        out: list[ServiceDesk] = []
        async for item in self._pages(f"{_BASE}/servicedesk"):
            out.append(ServiceDesk.model_validate(item))
            if max_items is not None and len(out) >= max_items:
                break
        return out

    async def find_service_desk_by_project(self, project_key: str) -> ServiceDesk | None:
        for desk in await self.list_service_desks():
            if desk.project_key.upper() == project_key.upper():
                return desk
        return None

    # --- request types ----------------------------------------------------------------------
    async def list_request_types(self, service_desk_id: str) -> list[dict[str, Any]]:
        return [
            item
            async for item in self._pages(f"{_BASE}/servicedesk/{seg(service_desk_id)}/requesttype")
        ]

    async def create_request_type(
        self, service_desk_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        body: dict[str, Any] = await self._http.request(
            "POST",
            f"{_BASE}/servicedesk/{seg(service_desk_id)}/requesttype",
            service=SERVICE,
            json=payload,
        )
        return body

    async def list_request_type_groups(self, service_desk_id: str) -> list[dict[str, Any]]:
        return [
            item
            async for item in self._pages(
                f"{_BASE}/servicedesk/{seg(service_desk_id)}/requesttypegroup"
            )
        ]

    async def list_queues(self, service_desk_id: str) -> list[dict[str, Any]]:
        return [
            item
            async for item in self._pages(
                f"{_BASE}/servicedesk/{seg(service_desk_id)}/queue", {"includeCount": "true"}
            )
        ]

    # --- organizations & customers ------------------------------------------------------------
    async def list_organizations(self, service_desk_id: str | None = None) -> list[dict[str, Any]]:
        path = (
            f"{_BASE}/servicedesk/{seg(service_desk_id)}/organization"
            if service_desk_id
            else f"{_BASE}/organization"
        )
        return [item async for item in self._pages(path)]

    async def create_organization(self, name: str) -> dict[str, Any]:
        body: dict[str, Any] = await self._http.request(
            "POST", f"{_BASE}/organization", service=SERVICE, json={"name": name}
        )
        return body

    async def add_organization_to_service_desk(self, service_desk_id: str, org_id: str) -> None:
        await self._http.request(
            "POST",
            f"{_BASE}/servicedesk/{seg(service_desk_id)}/organization",
            service=SERVICE,
            json={"organizationId": int(org_id)},
            idempotent=True,
        )

    async def add_users_to_organization(self, org_id: str, account_ids: list[str]) -> None:
        await self._http.request(
            "POST",
            f"{_BASE}/organization/{seg(org_id)}/user",
            service=SERVICE,
            json={"accountIds": account_ids},
            idempotent=True,
        )

    async def create_customer(self, email: str, display_name: str) -> dict[str, Any]:
        body: dict[str, Any] = await self._http.request(
            "POST",
            f"{_BASE}/customer",
            service=SERVICE,
            json={"email": email, "displayName": display_name},
        )
        return body

    async def add_customers(self, service_desk_id: str, account_ids: list[str]) -> None:
        await self._http.request(
            "POST",
            f"{_BASE}/servicedesk/{seg(service_desk_id)}/customer",
            service=SERVICE,
            json={"accountIds": account_ids},
            headers=_EXPERIMENTAL,
            idempotent=True,
        )

    async def list_customers(self, service_desk_id: str) -> list[dict[str, Any]]:
        return [
            item
            async for item in self._pages(f"{_BASE}/servicedesk/{seg(service_desk_id)}/customer")
        ]

    # --- requests -------------------------------------------------------------------------
    async def create_request(self, payload: dict[str, Any]) -> dict[str, Any]:
        body: dict[str, Any] = await self._http.request(
            "POST", f"{_BASE}/request", service=SERVICE, json=payload
        )
        return body

    async def get_request(self, key: str) -> dict[str, Any]:
        body: dict[str, Any] = await self._http.request(
            "GET", f"{_BASE}/request/{seg(key)}", service=SERVICE
        )
        return body

    async def add_participants(self, key: str, account_ids: list[str]) -> None:
        await self._http.request(
            "POST",
            f"{_BASE}/request/{seg(key)}/participant",
            service=SERVICE,
            json={"accountIds": account_ids},
            idempotent=True,
        )

    async def list_participants(self, key: str) -> list[dict[str, Any]]:
        return [item async for item in self._pages(f"{_BASE}/request/{seg(key)}/participant")]

    async def get_request_slas(self, key: str) -> list[dict[str, Any]]:
        return [item async for item in self._pages(f"{_BASE}/request/{seg(key)}/sla")]

    async def search_knowledge_base(self, service_desk_id: str, query: str) -> list[dict[str, Any]]:
        return [
            item
            async for item in self._pages(
                f"{_BASE}/servicedesk/{seg(service_desk_id)}/knowledgebase/article",
                {"query": query},
            )
        ]
