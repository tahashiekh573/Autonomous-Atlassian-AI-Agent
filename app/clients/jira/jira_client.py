"""Jira Software / Platform REST API v3 + Agile API client.

Docs: https://developer.atlassian.com/cloud/jira/platform/rest/v3/
      https://developer.atlassian.com/cloud/jira/software/rest/
"""

from collections.abc import Iterable

from app.clients.atlassian.http_client import AtlassianHttpClient
from app.clients.jira.agile import JiraAgileMixin
from app.clients.jira.automation import JiraAutomationMixin
from app.clients.jira.configuration import JiraConfigurationMixin
from app.clients.jira.dashboards import JiraDashboardsMixin
from app.clients.jira.issues import JiraIssuesMixin
from app.clients.jira.projects import JiraProjectsMixin
from app.clients.jira.types import JiraServerInfo, JiraUser
from app.clients.jira.workflows import JiraWorkflowsMixin

SERVICE = "jira"


class JiraClient(
    JiraProjectsMixin,
    JiraIssuesMixin,
    JiraConfigurationMixin,
    JiraWorkflowsMixin,
    JiraAgileMixin,
    JiraDashboardsMixin,
    JiraAutomationMixin,
):
    def __init__(self, http: AtlassianHttpClient) -> None:
        self._http = http

    async def get_myself(self) -> JiraUser:
        body = await self._http.request("GET", "/rest/api/3/myself", service=SERVICE)
        return JiraUser.model_validate(body)

    async def get_server_info(self) -> JiraServerInfo:
        body = await self._http.request("GET", "/rest/api/3/serverInfo", service=SERVICE)
        return JiraServerInfo.model_validate(body)

    async def get_my_permissions(self, keys: Iterable[str]) -> dict[str, bool]:
        """Return {permission_key: has_permission} for the authenticated user."""
        body = await self._http.request(
            "GET",
            "/rest/api/3/mypermissions",
            service=SERVICE,
            params={"permissions": ",".join(keys)},
        )
        perms = body.get("permissions") or {}
        return {key: bool(value.get("havePermission")) for key, value in perms.items()}
