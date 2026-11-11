"""Jira issues, search, transitions and links."""

from typing import Any

from app.clients.atlassian.http_client import AtlassianHttpClient
from app.clients.atlassian.paths import seg
from app.clients.jira.adf import to_adf

SERVICE = "jira"


class JiraIssuesMixin:
    _http: AtlassianHttpClient

    async def create_issue(self, fields: dict[str, Any]) -> dict[str, Any]:
        body: dict[str, Any] = await self._http.request(
            "POST", "/rest/api/3/issue", service=SERVICE, json={"fields": fields}
        )
        return body

    async def get_issue(self, key: str, fields: str = "*navigable") -> dict[str, Any]:
        body: dict[str, Any] = await self._http.request(
            "GET", f"/rest/api/3/issue/{seg(key)}", service=SERVICE, params={"fields": fields}
        )
        return body

    async def update_issue(self, key: str, fields: dict[str, Any]) -> None:
        await self._http.request(
            "PUT", f"/rest/api/3/issue/{seg(key)}", service=SERVICE, json={"fields": fields}
        )

    async def delete_issue(self, key: str) -> None:
        await self._http.request("DELETE", f"/rest/api/3/issue/{seg(key)}", service=SERVICE)

    async def add_comment(self, key: str, text: str) -> None:
        await self._http.request(
            "POST",
            f"/rest/api/3/issue/{seg(key)}/comment",
            service=SERVICE,
            json={"body": to_adf(text)},
        )

    async def get_transitions(self, key: str) -> list[dict[str, Any]]:
        body = await self._http.request(
            "GET", f"/rest/api/3/issue/{seg(key)}/transitions", service=SERVICE
        )
        return list(body.get("transitions") or [])

    async def transition_issue(self, key: str, transition_id: str) -> None:
        await self._http.request(
            "POST",
            f"/rest/api/3/issue/{seg(key)}/transitions",
            service=SERVICE,
            json={"transition": {"id": transition_id}},
        )

    async def search(
        self, jql: str, *, fields: list[str] | None = None, max_results: int = 100
    ) -> list[dict[str, Any]]:
        """Enhanced JQL search (POST /search/jql) with nextPageToken pagination."""
        issues: list[dict[str, Any]] = []
        token: str | None = None
        while len(issues) < max_results:
            payload: dict[str, Any] = {
                "jql": jql,
                "fields": fields or ["summary", "status"],
                "maxResults": min(100, max_results - len(issues)),
            }
            if token:
                payload["nextPageToken"] = token
            body = await self._http.request(
                "POST", "/rest/api/3/search/jql", service=SERVICE, json=payload, idempotent=True
            )
            issues.extend(body.get("issues") or [])
            token = body.get("nextPageToken")
            if not token or body.get("isLast") is True:
                break
        return issues[:max_results]

    async def parse_jql(self, queries: list[str]) -> list[list[str]]:
        """Strict JQL validation: one list of error messages per query (empty = valid)."""
        body = await self._http.request(
            "POST",
            "/rest/api/3/jql/parse",
            service=SERVICE,
            params={"validation": "strict"},
            json={"queries": queries},
            idempotent=True,
        )
        return [list(q.get("errors") or []) for q in (body or {}).get("queries") or []]

    async def approximate_count(self, jql: str) -> int:
        body = await self._http.request(
            "POST",
            "/rest/api/3/search/approximate-count",
            service=SERVICE,
            json={"jql": jql},
            idempotent=True,
        )
        return int(body.get("count") or 0)

    async def list_link_types(self) -> list[dict[str, Any]]:
        body = await self._http.request("GET", "/rest/api/3/issueLinkType", service=SERVICE)
        return list(body.get("issueLinkTypes") or [])

    async def link_issues(self, link_type: str, source_key: str, target_key: str) -> None:
        """Create "<source> <outward description> <target>", e.g. "A blocks B".

        Jira's payload naming is inverted: the issue that receives the *outward* description
        (the "blocks" side) is sent as ``inwardIssue``. The Verification Agent re-reads the link
        and reports the stored direction.
        """
        await self._http.request(
            "POST",
            "/rest/api/3/issueLink",
            service=SERVICE,
            json={
                "type": {"name": link_type},
                "inwardIssue": {"key": source_key},
                "outwardIssue": {"key": target_key},
            },
        )

    async def add_remote_link(
        self, key: str, *, url: str, title: str, global_id: str
    ) -> dict[str, Any]:
        """Create or update (same globalId) a remote link. Idempotent by design."""
        body: dict[str, Any] = await self._http.request(
            "POST",
            f"/rest/api/3/issue/{seg(key)}/remotelink",
            service=SERVICE,
            json={"globalId": global_id, "object": {"url": url, "title": title}},
            idempotent=True,
        )
        return body

    async def get_remote_links(self, key: str) -> list[dict[str, Any]]:
        body: list[dict[str, Any]] = await self._http.request(
            "GET", f"/rest/api/3/issue/{seg(key)}/remotelink", service=SERVICE
        )
        return body
