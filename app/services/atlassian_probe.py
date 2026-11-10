"""Read-only checks that discover which Atlassian products a site exposes to the caller.

This is infrastructure, not an AI task, so it calls clients directly from the service layer.
Every check is a GET; nothing in the connected instance is modified.
"""

from dataclasses import dataclass

from app.clients.atlassian.factory import AtlassianClients
from app.core.exceptions import AtlassianAuthError, AtlassianError, AtlassianNotFoundError
from app.schemas.connection import AccountInfo, ProductStatus

JIRA_PERMISSION_KEYS = ("ADMINISTER", "BROWSE_PROJECTS", "CREATE_ISSUES")


@dataclass
class ProbeResult:
    account: AccountInfo | None
    is_jira_admin: bool | None
    products: list[ProductStatus]


class AtlassianProbe:
    async def run(self, clients: AtlassianClients) -> ProbeResult:
        account, is_admin, jira = await self._probe_jira(clients)
        if jira.error_code == AtlassianAuthError.code:
            # Authentication failed for the whole site; other products would fail the same way.
            skipped = [
                ProductStatus(
                    product=p,
                    available=False,
                    detail="Skipped: credentials were rejected by Jira.",
                    error_code=jira.error_code,
                )
                for p in ("jsm", "confluence")
            ]
            return ProbeResult(account=None, is_jira_admin=None, products=[jira, *skipped])
        jsm = await self._probe_jsm(clients)
        confluence = await self._probe_confluence(clients)
        return ProbeResult(
            account=account, is_jira_admin=is_admin, products=[jira, jsm, confluence]
        )

    async def _probe_jira(
        self, clients: AtlassianClients
    ) -> tuple[AccountInfo | None, bool | None, ProductStatus]:
        try:
            me = await clients.jira.get_myself()
            info = await clients.jira.get_server_info()
            perms = await clients.jira.get_my_permissions(JIRA_PERMISSION_KEYS)
        except AtlassianError as exc:
            return None, None, _unavailable("jira", exc)
        account = AccountInfo(
            account_id=me.account_id, display_name=me.display_name, email_address=me.email_address
        )
        status = ProductStatus(
            product="jira",
            available=True,
            detail=f"Authenticated as {me.display_name}.",
            metadata={
                "deployment_type": info.deployment_type,
                "version": info.version,
                "permissions": perms,
            },
        )
        return account, perms.get("ADMINISTER", False), status

    async def _probe_jsm(self, clients: AtlassianClients) -> ProductStatus:
        try:
            info = await clients.jsm.get_info()
            desks = await clients.jsm.list_service_desks(max_items=50)
        except AtlassianNotFoundError as exc:
            return _unavailable("jsm", exc, "Jira Service Management is not enabled on this site.")
        except AtlassianError as exc:
            return _unavailable("jsm", exc)
        return ProductStatus(
            product="jsm",
            available=True,
            detail=f"JSM {info.version or ''} reachable; {len(desks)} service desk(s) visible.",
            metadata={
                "version": info.version,
                "service_desks": [{"id": d.id, "project_key": d.project_key} for d in desks],
            },
        )

    async def _probe_confluence(self, clients: AtlassianClients) -> ProductStatus:
        try:
            spaces = await clients.confluence.list_spaces(max_items=25)
        except AtlassianNotFoundError as exc:
            return _unavailable("confluence", exc, "Confluence is not enabled on this site.")
        except AtlassianError as exc:
            return _unavailable("confluence", exc)
        return ProductStatus(
            product="confluence",
            available=True,
            detail=f"Confluence reachable; {len(spaces)} space(s) visible (first page).",
            metadata={"spaces": [{"id": s.id, "key": s.key} for s in spaces]},
        )


def _unavailable(product: str, exc: AtlassianError, detail: str | None = None) -> ProductStatus:
    return ProductStatus.model_validate(
        {
            "product": product,
            "available": False,
            "detail": detail or exc.message,
            "error_code": exc.code,
            "metadata": {"upstream_status": exc.upstream_status},
        }
    )
