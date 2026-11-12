"""Jira dashboards and gadgets."""

from typing import Any

from app.clients.atlassian.http_client import AtlassianHttpClient
from app.clients.atlassian.paths import seg

SERVICE = "jira"


class JiraDashboardsMixin:
    _http: AtlassianHttpClient

    async def create_dashboard(self, payload: dict[str, Any]) -> dict[str, Any]:
        body: dict[str, Any] = await self._http.request(
            "POST", "/rest/api/3/dashboard", service=SERVICE, json=payload
        )
        return body

    async def get_dashboard(self, dashboard_id: str) -> dict[str, Any]:
        body: dict[str, Any] = await self._http.request(
            "GET", f"/rest/api/3/dashboard/{seg(dashboard_id)}", service=SERVICE
        )
        return body

    async def search_dashboards(self, name: str) -> list[dict[str, Any]]:
        return [
            item
            async for item in self._http.paginate_offset(
                "/rest/api/3/dashboard/search", service=SERVICE, params={"dashboardName": name}
            )
        ]

    async def add_gadget(self, dashboard_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        body: dict[str, Any] = await self._http.request(
            "POST",
            f"/rest/api/3/dashboard/{seg(dashboard_id)}/gadget",
            service=SERVICE,
            json=payload,
        )
        return body

    async def list_available_gadgets(self) -> list[dict[str, Any]]:
        """Gadget directory: legacy gadgets have a ``uri``, dashboard items a ``moduleKey``."""
        body = await self._http.request("GET", "/rest/api/3/dashboard/gadgets", service=SERVICE)
        return list(body.get("gadgets") or [])

    async def get_gadget_prefs(self, dashboard_id: str, gadget_id: str) -> dict[str, str]:
        """Legacy gadget preferences (the gadget's Configure form), name -> value.

        Internal endpoint used by Jira's own dashboard; there is no public one for legacy gadgets.
        """
        body = await self._http.request(
            "GET",
            f"/rest/dashboards/1.0/{seg(dashboard_id)}/gadget/{seg(gadget_id)}/prefs",
            service=SERVICE,
        )
        fields = (body or {}).get("fields") or []
        return {str(f.get("name")): str(f.get("value", "")) for f in fields}

    async def set_gadget_prefs(
        self, dashboard_id: str, gadget_id: str, prefs: dict[str, str]
    ) -> None:
        await self._http.request(
            "PUT",
            f"/rest/dashboards/1.0/{seg(dashboard_id)}/gadget/{seg(gadget_id)}/prefs",
            service=SERVICE,
            json={f"up_{k}": v for k, v in prefs.items()},
            headers={"X-Atlassian-Token": "no-check"},
        )

    async def get_gadgets(self, dashboard_id: str) -> list[dict[str, Any]]:
        body = await self._http.request(
            "GET", f"/rest/api/3/dashboard/{seg(dashboard_id)}/gadget", service=SERVICE
        )
        return list(body.get("gadgets") or [])
