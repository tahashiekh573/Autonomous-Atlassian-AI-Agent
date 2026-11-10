"""Re-read JSM, Confluence and cross-product state after each operation."""

from types import SimpleNamespace
from typing import Any

from app.agents.handlers.base import HandlerContext, same_name
from app.agents.handlers.storage_format import jira_issues_macro
from app.agents.verifiers.base import Verifier, check, exists, out
from app.agents.verifiers.jira_verifiers import issue, link
from app.schemas.agents import OperationOutcome, VerificationCheck

Checks = list[VerificationCheck]


async def service_project(ctx: HandlerContext, p: Any, o: OperationOutcome) -> Checks:
    proj = await ctx.jira.get_project(p.key)
    desk = await ctx.jsm.find_service_desk_by_project(p.key)
    return [
        check("project type", "service_desk", proj.get("projectTypeKey")),
        exists("service desk", desk is not None, desk.id if desk else None),
    ]


async def request_type(ctx: HandlerContext, p: Any, o: OperationOutcome) -> Checks:
    types = await ctx.jsm.list_request_types(out(o, "service_desk_id"))
    return [exists("request type", any(str(t["id"]) == out(o, "id") for t in types), p.name)]


async def organization(ctx: HandlerContext, p: Any, o: OperationOutcome) -> Checks:
    orgs = await ctx.jsm.list_organizations()
    checks = [exists("organization", any(str(x["id"]) == out(o, "id") for x in orgs), p.name)]
    if p.service_desk:
        desk = next(
            (
                d
                for d in await ctx.jsm.list_service_desks()
                if d.id == p.service_desk or same_name(d.project_key, p.service_desk)
            ),
            None,
        )
        desk_orgs = await ctx.jsm.list_organizations(desk.id) if desk else []
        checks.append(
            exists("added to service desk", any(str(x["id"]) == out(o, "id") for x in desk_orgs))
        )
    return checks


async def customers(ctx: HandlerContext, p: Any, o: OperationOutcome) -> Checks:
    present = {
        str(c.get("accountId")) for c in await ctx.jsm.list_customers(out(o, "service_desk_id"))
    }
    wanted = set(o.outputs.get("account_ids") or [])
    return [check("customers have access", True, wanted <= present, wanted <= present)]


async def request(ctx: HandlerContext, p: Any, o: OperationOutcome) -> Checks:
    req = await ctx.jsm.get_request(out(o, "key"))
    return [exists("request", True, req.get("issueKey"))]


async def participants(ctx: HandlerContext, p: Any, o: OperationOutcome) -> Checks:
    present = {str(x.get("accountId")) for x in await ctx.jsm.list_participants(p.issue_key)}
    return [
        check("participants", True, set(p.account_ids) <= present, set(p.account_ids) <= present)
    ]


async def space(ctx: HandlerContext, p: Any, o: OperationOutcome) -> Checks:
    key = getattr(p, "key", None) or p.space_key
    s = await ctx.confluence.get_space_by_key(key)
    checks = [exists("space", s is not None, key)]
    if s and getattr(p, "name", None):
        checks.append(check("name", p.name, s.get("name")))
    return checks


async def page(ctx: HandlerContext, p: Any, o: OperationOutcome) -> Checks:
    data = await ctx.confluence.get_page(out(o, "id"))
    checks = [check("status", "current", data.get("status"))]
    if getattr(p, "title", None):
        checks.append(check("title", p.title, data.get("title")))
    parent = o.outputs.get("parent_id")
    if parent and not o.reused_existing:
        checks.append(check("parent", str(parent), str(data.get("parentId"))))
    labels = list(getattr(p, "labels", []) or [])
    if labels:
        present = set(await ctx.confluence.get_labels(out(o, "id")))
        checks.append(check("labels", True, set(labels) <= present, set(labels) <= present))
    body = ((data.get("body") or {}).get("storage") or {}).get("value", "")
    checks.append(check("has content", True, bool(body.strip()), bool(body.strip())))
    return checks


async def labels(ctx: HandlerContext, p: Any, o: OperationOutcome) -> Checks:
    present = set(await ctx.confluence.get_labels(p.page_id))
    return [check("labels", True, set(p.labels) <= present, set(p.labels) <= present)]


async def space_permission(ctx: HandlerContext, p: Any, o: OperationOutcome) -> Checks:
    s = await ctx.confluence.get_space_by_key(p.space_key)
    perms = await ctx.confluence.list_space_permissions(str(s["id"])) if s else []
    found = any(str((x.get("principal") or {}).get("id")) == p.subject for x in perms)
    return [exists(f"permission for {p.subject}", found)]


async def page_deleted(ctx: HandlerContext, p: Any, o: OperationOutcome) -> Checks:
    return [check("page removed", True, not await ctx.confluence.page_exists(p.page_id))]


async def remote_link(ctx: HandlerContext, p: Any, o: OperationOutcome) -> Checks:
    links = await ctx.jira.get_remote_links(p.issue_key)
    url = out(o, "url")
    return [
        exists("remote link", any((x.get("object") or {}).get("url") == url for x in links), url)
    ]


async def dev_issue(ctx: HandlerContext, p: Any, o: OperationOutcome) -> Checks:
    key = out(o, "key")
    link_params = SimpleNamespace(incident_key=p.incident_key, issue_key=key, link_type=p.link_type)
    return [
        *(await issue(ctx, SimpleNamespace(issue_key=key), o)),
        *(await link(ctx, link_params, o)),
    ]


async def embedded_macro(ctx: HandlerContext, p: Any, o: OperationOutcome) -> Checks:
    data = await ctx.confluence.get_page(p.page_id)
    body = ((data.get("body") or {}).get("storage") or {}).get("value", "")
    macro = jira_issues_macro(p.jql, p.max_issues)
    return [exists("jira macro on page", macro in body)]


async def project_space_link(ctx: HandlerContext, p: Any, o: OperationOutcome) -> Checks:
    proj = await ctx.jira.get_project(p.project_key)
    url = out(o, "space_url")
    return [exists("space link in project description", url in str(proj.get("description") or ""))]


VERIFIERS: dict[str, Verifier] = {
    "jsm.create_service_project": service_project,
    "jsm.create_request_type": request_type,
    "jsm.create_organization": organization,
    "jsm.add_customers": customers,
    "jsm.create_request": request,
    "jsm.add_participants": participants,
    "confluence.create_space": space,
    "confluence.update_space": space,
    "confluence.create_page": page,
    "confluence.create_index_page": page,
    "confluence.update_page": page,
    "confluence.add_labels": labels,
    "confluence.set_space_permission": space_permission,
    "confluence.delete_page": page_deleted,
    "integration.link_issue_to_page": remote_link,
    "integration.link_incident_to_issue": link,
    "integration.create_dev_issue_from_incident": dev_issue,
    "integration.embed_issues_in_page": embedded_macro,
    "integration.link_project_to_space": project_space_link,
}
