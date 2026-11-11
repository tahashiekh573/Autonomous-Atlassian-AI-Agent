"""Jira Service Management Assets (CMDB) REST API.

Docs: https://developer.atlassian.com/cloud/assets/rest/
Base: https://api.atlassian.com/jsm/assets/workspace/{workspaceId}/v1/
Access requires the Assets REST API to be enabled for the site's JSM plan and Assets
permissions for the account; otherwise Atlassian answers 403 "Access to Assets API was denied".
"""

from typing import Any

from app.clients.atlassian.http_client import AtlassianHttpClient
from app.clients.atlassian.paths import seg

SERVICE = "jsm-assets"

# Assets "default" attribute data types (attribute type 0).
DEFAULT_TYPE_IDS: dict[str, int] = {
    "text": 0,
    "integer": 1,
    "boolean": 2,
    "double": 3,
    "date": 4,
    "time": 5,
    "datetime": 6,
    "url": 7,
    "email": 8,
    "textarea": 9,
    "select": 10,
    "ipaddress": 11,
}


class AssetsClient:
    def __init__(self, platform: AtlassianHttpClient) -> None:
        self._http = platform  # base URL https://api.atlassian.com

    @staticmethod
    def _base(workspace_id: str) -> str:
        return f"/jsm/assets/workspace/{seg(workspace_id)}/v1"

    async def _get(self, workspace_id: str, path: str, **params: Any) -> Any:
        return await self._http.request(
            "GET", f"{self._base(workspace_id)}{path}", service=SERVICE, params=params or None
        )

    async def _post(
        self, workspace_id: str, path: str, payload: Any, *, idempotent: bool = False
    ) -> Any:
        return await self._http.request(
            "POST",
            f"{self._base(workspace_id)}{path}",
            service=SERVICE,
            json=payload,
            idempotent=idempotent,
        )

    # --- schemas & types ------------------------------------------------------------------
    async def list_schemas(self, workspace_id: str) -> list[dict[str, Any]]:
        body = await self._get(workspace_id, "/objectschema/list")
        return list((body or {}).get("values") or [])

    async def create_schema(
        self, workspace_id: str, name: str, key: str, description: str
    ) -> dict[str, Any]:
        body: dict[str, Any] = await self._post(
            workspace_id,
            "/objectschema/create",
            {"name": name, "objectSchemaKey": key, "description": description},
        )
        return body

    async def list_object_types(self, workspace_id: str, schema_id: str) -> list[dict[str, Any]]:
        body = await self._get(workspace_id, f"/objectschema/{seg(schema_id)}/objecttypes/flat")
        return list(body or [])

    async def list_global_icons(self, workspace_id: str) -> list[dict[str, Any]]:
        body = await self._get(workspace_id, "/icon/global")
        return list(body or [])

    async def create_object_type(
        self, workspace_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        body: dict[str, Any] = await self._post(workspace_id, "/objecttype/create", payload)
        return body

    async def list_attributes(self, workspace_id: str, object_type_id: str) -> list[dict[str, Any]]:
        body = await self._get(workspace_id, f"/objecttype/{seg(object_type_id)}/attributes")
        return list(body or [])

    async def create_attribute(
        self, workspace_id: str, object_type_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        body: dict[str, Any] = await self._post(
            workspace_id, f"/objecttypeattribute/{seg(object_type_id)}", payload
        )
        return body

    # --- objects --------------------------------------------------------------------------
    async def find_objects(
        self, workspace_id: str, aql: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        body = await self._post(
            workspace_id, "/object/aql", {"qlQuery": aql, "maxResults": limit}, idempotent=True
        )
        return list((body or {}).get("values") or [])

    async def create_object(self, workspace_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        body: dict[str, Any] = await self._post(workspace_id, "/object/create", payload)
        return body

    async def get_object(self, workspace_id: str, object_id: str) -> dict[str, Any]:
        body: dict[str, Any] = await self._get(workspace_id, f"/object/{seg(object_id)}")
        return body
