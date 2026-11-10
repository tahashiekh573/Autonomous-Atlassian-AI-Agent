"""Jira Automation rule-management REST API.

Docs: https://developer.atlassian.com/cloud/automation/rest/
Availability depends on site plan and rollout; a 404 is reported as an unsupported operation.
"""

from typing import Any

from app.clients.atlassian.http_client import AtlassianHttpClient
from app.clients.atlassian.paths import seg
from app.core.exceptions import AtlassianNotFoundError, AtlassianUnsupportedError

SERVICE = "jira-automation"


class JiraAutomationMixin:
    _http: AtlassianHttpClient

    async def get_cloud_id(self) -> str:
        body = await self._http.request("GET", "/_edge/tenant_info", service=SERVICE)
        return str(body["cloudId"])

    def _automation_base(self, cloud_id: str) -> str:
        return f"/gateway/api/automation/public/jira/{seg(cloud_id)}/rest/v1"

    async def create_automation_rule(self, cloud_id: str, rule: dict[str, Any]) -> dict[str, Any]:
        try:
            body: dict[str, Any] = await self._http.request(
                "POST", f"{self._automation_base(cloud_id)}/rule", service=SERVICE, json=rule
            )
        except AtlassianNotFoundError as exc:
            raise AtlassianUnsupportedError(
                "The Automation REST API is not available on this site.",
                service=SERVICE,
                upstream_status=404,
            ) from exc
        return body

    async def list_automation_rules(self, cloud_id: str) -> list[dict[str, Any]]:
        """Rule summaries (uuid, name, state), following the cursor in ``links.next``."""
        rules: list[dict[str, Any]] = []
        params: dict[str, Any] | None = {"limit": 100}
        path = f"{self._automation_base(cloud_id)}/rule/summary"
        try:
            while path and len(rules) < 2000:
                body = await self._http.request("GET", path, service=SERVICE, params=params)
                rules.extend(body.get("data") or [])
                nxt = str((body.get("links") or {}).get("next") or "")
                # Only follow site-relative links so credentials never go to another host.
                path, params = (nxt if nxt.startswith("/") else ""), None
        except AtlassianNotFoundError:
            return rules
        return rules

    async def get_automation_rule(self, cloud_id: str, rule_uuid: str) -> dict[str, Any]:
        body: dict[str, Any] = await self._http.request(
            "GET", f"{self._automation_base(cloud_id)}/rule/{seg(rule_uuid)}", service=SERVICE
        )
        return body
