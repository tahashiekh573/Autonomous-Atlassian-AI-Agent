"""Jira administration: issue types + schemes, fields, screens, field configs, priorities,
statuses."""

from typing import Any

from app.clients.atlassian.http_client import AtlassianHttpClient
from app.clients.atlassian.paths import seg

SERVICE = "jira"


class JiraConfigurationMixin:
    _http: AtlassianHttpClient

    # --- issue types ----------------------------------------------------------------------
    async def list_issue_types(self) -> list[dict[str, Any]]:
        body: list[dict[str, Any]] = await self._http.request(
            "GET", "/rest/api/3/issuetype", service=SERVICE
        )
        return body

    async def create_issue_type(
        self, name: str, description: str, hierarchy_level: int
    ) -> dict[str, Any]:
        body: dict[str, Any] = await self._http.request(
            "POST",
            "/rest/api/3/issuetype",
            service=SERVICE,
            json={"name": name, "description": description, "hierarchyLevel": hierarchy_level},
        )
        return body

    async def create_issue_type_scheme(
        self, name: str, description: str, issue_type_ids: list[str], default_id: str | None
    ) -> str:
        payload: dict[str, Any] = {
            "name": name,
            "description": description,
            "issueTypeIds": issue_type_ids,
        }
        if default_id:
            payload["defaultIssueTypeId"] = default_id
        body = await self._http.request(
            "POST", "/rest/api/3/issuetypescheme", service=SERVICE, json=payload
        )
        return str(body["issueTypeSchemeId"])

    async def list_issue_type_scheme_names(self) -> list[str]:
        return [
            str(item.get("name") or "")
            async for item in self._http.paginate_offset(
                "/rest/api/3/issuetypescheme", service=SERVICE
            )
        ]

    async def assign_issue_type_scheme(self, scheme_id: str, project_id: str) -> None:
        await self._http.request(
            "PUT",
            "/rest/api/3/issuetypescheme/project",
            service=SERVICE,
            json={"issueTypeSchemeId": scheme_id, "projectId": project_id},
        )

    async def get_project_issue_type_scheme(self, project_id: str) -> dict[str, Any] | None:
        body = await self._http.request(
            "GET",
            "/rest/api/3/issuetypescheme/project",
            service=SERVICE,
            params={"projectId": project_id},
        )
        values = body.get("values") or []
        return values[0].get("issueTypeScheme") if values else None

    async def list_issue_type_scheme_items(self, scheme_id: str) -> list[str]:
        return [
            str(item["issueTypeId"])
            async for item in self._http.paginate_offset(
                "/rest/api/3/issuetypescheme/mapping",
                service=SERVICE,
                params={"issueTypeSchemeId": scheme_id},
            )
        ]

    # --- fields ---------------------------------------------------------------------------
    async def list_fields(self) -> list[dict[str, Any]]:
        body: list[dict[str, Any]] = await self._http.request(
            "GET", "/rest/api/3/field", service=SERVICE
        )
        return body

    async def find_field(self, field_id: str) -> dict[str, Any] | None:
        """Look a field up by id (fresh, unlike the cached full field list)."""
        body = await self._http.request(
            "GET", "/rest/api/3/field/search", service=SERVICE, params={"id": field_id}
        )
        values = (body or {}).get("values") or []
        return values[0] if values else None

    async def create_custom_field(
        self, name: str, description: str, field_type: str, searcher_key: str
    ) -> dict[str, Any]:
        body: dict[str, Any] = await self._http.request(
            "POST",
            "/rest/api/3/field",
            service=SERVICE,
            json={
                "name": name,
                "description": description,
                "type": field_type,
                "searcherKey": searcher_key,
            },
        )
        return body

    async def list_field_contexts(self, field_id: str) -> list[dict[str, Any]]:
        return [
            item
            async for item in self._http.paginate_offset(
                f"/rest/api/3/field/{seg(field_id)}/context", service=SERVICE
            )
        ]

    async def list_field_options(self, field_id: str, context_id: str) -> list[dict[str, Any]]:
        return [
            item
            async for item in self._http.paginate_offset(
                f"/rest/api/3/field/{seg(field_id)}/context/{seg(context_id)}/option",
                service=SERVICE,
            )
        ]

    async def add_field_options(self, field_id: str, context_id: str, values: list[str]) -> None:
        await self._http.request(
            "POST",
            f"/rest/api/3/field/{seg(field_id)}/context/{seg(context_id)}/option",
            service=SERVICE,
            json={"options": [{"value": v, "disabled": False} for v in values]},
        )

    # --- screens --------------------------------------------------------------------------
    async def search_screens(self, name: str) -> list[dict[str, Any]]:
        return [
            item
            async for item in self._http.paginate_offset(
                "/rest/api/3/screens", service=SERVICE, params={"queryString": name}
            )
        ]

    async def create_screen(self, name: str, description: str) -> dict[str, Any]:
        body: dict[str, Any] = await self._http.request(
            "POST",
            "/rest/api/3/screens",
            service=SERVICE,
            json={"name": name, "description": description},
        )
        return body

    async def get_screen_tabs(self, screen_id: str) -> list[dict[str, Any]]:
        body: list[dict[str, Any]] = await self._http.request(
            "GET", f"/rest/api/3/screens/{seg(screen_id)}/tabs", service=SERVICE
        )
        return body

    async def create_screen_tab(self, screen_id: str, name: str) -> dict[str, Any]:
        body: dict[str, Any] = await self._http.request(
            "POST",
            f"/rest/api/3/screens/{seg(screen_id)}/tabs",
            service=SERVICE,
            json={"name": name},
        )
        return body

    async def get_tab_fields(self, screen_id: str, tab_id: str) -> list[dict[str, Any]]:
        body: list[dict[str, Any]] = await self._http.request(
            "GET",
            f"/rest/api/3/screens/{seg(screen_id)}/tabs/{seg(tab_id)}/fields",
            service=SERVICE,
        )
        return body

    async def add_field_to_tab(self, screen_id: str, tab_id: str, field_id: str) -> None:
        await self._http.request(
            "POST",
            f"/rest/api/3/screens/{seg(screen_id)}/tabs/{seg(tab_id)}/fields",
            service=SERVICE,
            json={"fieldId": field_id},
        )

    # --- field configurations ---------------------------------------------------------------
    async def search_field_configurations(self, name: str) -> list[dict[str, Any]]:
        return [
            item
            async for item in self._http.paginate_offset(
                "/rest/api/3/fieldconfiguration", service=SERVICE, params={"query": name}
            )
        ]

    async def create_field_configuration(self, name: str, description: str) -> dict[str, Any]:
        body: dict[str, Any] = await self._http.request(
            "POST",
            "/rest/api/3/fieldconfiguration",
            service=SERVICE,
            json={"name": name, "description": description},
        )
        return body

    async def get_field_configuration_items(self, config_id: str) -> list[dict[str, Any]]:
        return [
            item
            async for item in self._http.paginate_offset(
                f"/rest/api/3/fieldconfiguration/{seg(config_id)}/fields", service=SERVICE
            )
        ]

    async def update_field_configuration_items(
        self, config_id: str, items: list[dict[str, Any]]
    ) -> None:
        await self._http.request(
            "PUT",
            f"/rest/api/3/fieldconfiguration/{seg(config_id)}/fields",
            service=SERVICE,
            json={"fieldConfigurationItems": items},
        )

    # --- priorities & statuses ------------------------------------------------------------
    async def search_priorities(self, name: str) -> list[dict[str, Any]]:
        return [
            item
            async for item in self._http.paginate_offset(
                "/rest/api/3/priority/search", service=SERVICE, params={"priorityName": name}
            )
        ]

    async def create_priority(self, payload: dict[str, Any]) -> dict[str, Any]:
        body: dict[str, Any] = await self._http.request(
            "POST", "/rest/api/3/priority", service=SERVICE, json=payload
        )
        return body

    async def search_statuses(self, name: str) -> list[dict[str, Any]]:
        return [
            item
            async for item in self._http.paginate_offset(
                "/rest/api/3/statuses/search", service=SERVICE, params={"searchString": name}
            )
        ]

    async def create_statuses(
        self, scope: dict[str, Any], statuses: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        body: list[dict[str, Any]] = await self._http.request(
            "POST",
            "/rest/api/3/statuses",
            service=SERVICE,
            json={"scope": scope, "statuses": statuses},
        )
        return body
