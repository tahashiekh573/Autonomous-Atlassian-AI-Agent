"""Jira Service Management Forms (ProForma) REST API.

Docs: https://developer.atlassian.com/cloud/forms/rest/
Base: https://api.atlassian.com/jira/forms/cloud/{cloudId}/  (basic auth with API token)
Form design shape (settings, questions, ADF layout with question extensions) mirrors forms read
back from a live site.
"""

from typing import Any

from app.clients.atlassian.http_client import AtlassianHttpClient
from app.clients.atlassian.paths import seg

SERVICE = "jsm-forms"
_HEADERS = {"X-ExperimentalApi": "opt-in"}


class FormsClient:
    def __init__(self, platform: AtlassianHttpClient) -> None:
        self._http = platform  # base URL https://api.atlassian.com

    @staticmethod
    def _base(cloud_id: str, project: str) -> str:
        return f"/jira/forms/cloud/{seg(cloud_id)}/project/{seg(project)}/form"

    async def list_forms(self, cloud_id: str, project: str) -> list[dict[str, Any]]:
        body = await self._http.request(
            "GET", self._base(cloud_id, project), service=SERVICE, headers=_HEADERS
        )
        return list(body or [])

    async def get_form(self, cloud_id: str, project: str, form_id: str) -> dict[str, Any]:
        body: dict[str, Any] = await self._http.request(
            "GET",
            f"{self._base(cloud_id, project)}/{seg(form_id)}",
            service=SERVICE,
            headers=_HEADERS,
        )
        return body

    async def create_form(
        self, cloud_id: str, project: str, design: dict[str, Any], publish: dict[str, Any] | None
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"design": design}
        if publish:
            payload["publish"] = publish
        body: dict[str, Any] = await self._http.request(
            "POST",
            self._base(cloud_id, project),
            service=SERVICE,
            json=payload,
            headers=_HEADERS,
        )
        return body

    async def save_form(
        self,
        cloud_id: str,
        project: str,
        form_id: str,
        design: dict[str, Any],
        publish: dict[str, Any] | None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"design": design}
        if publish:
            payload["publish"] = publish
        body: dict[str, Any] = await self._http.request(
            "PUT",
            f"{self._base(cloud_id, project)}/{seg(form_id)}",
            service=SERVICE,
            json=payload,
            headers=_HEADERS,
        )
        return body
