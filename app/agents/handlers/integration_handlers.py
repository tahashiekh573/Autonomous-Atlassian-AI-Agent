"""Cross-product handlers that maintain traceability between Jira, JSM and Confluence."""

from typing import Any

from app.agents.handlers.base import HandlerContext, HandlerResult, find_step_issue, step_marker
from app.agents.handlers.confluence_handlers import page_url, require_space
from app.agents.handlers.jira_common import browse_url, require_project
from app.agents.handlers.jira_issues import link_issues_with
from app.agents.handlers.storage_format import jira_issues_macro
from app.clients.jira.adf import to_adf
from app.schemas.agents import ResourceRef
from app.schemas.operations.integration_ops import (
    CreateDevIssueFromIncidentParams,
    EmbedIssuesInPageParams,
    LinkIncidentToIssueParams,
    LinkIssueToPageParams,
    LinkProjectToSpaceParams,
)


async def link_issue_to_page(ctx: HandlerContext, p: LinkIssueToPageParams) -> HandlerResult:
    page = await ctx.confluence.get_page(p.page_id, with_body=False)
    url = page_url(ctx, page)
    await ctx.jira.add_remote_link(
        p.issue_key, url=url, title=str(page.get("title")), global_id=f"confluence-page-{p.page_id}"
    )
    return HandlerResult(
        message=f"Linked {p.issue_key} to page '{page.get('title')}'.",
        outputs={"issue_key": p.issue_key, "page_id": p.page_id, "url": url},
        resource=ResourceRef(
            type="jira_remote_link", key=p.issue_key, title=str(page.get("title")), url=url
        ),
    )


async def link_incident_to_issue(
    ctx: HandlerContext, p: LinkIncidentToIssueParams
) -> HandlerResult:
    return await link_issues_with(ctx, p.incident_key, p.issue_key, p.link_type)


async def create_dev_issue_from_incident(
    ctx: HandlerContext, p: CreateDevIssueFromIncidentParams
) -> HandlerResult:
    incident = await ctx.jira.get_issue(p.incident_key, fields="summary,description,priority")
    fields = incident["fields"]
    summary = f"[{p.incident_key}] {fields.get('summary')}"[:255]
    existing = await find_step_issue(ctx, p.target_project_key, summary)
    if existing:
        key = str(existing["key"])
        reused = True
    else:
        await require_project(ctx, p.target_project_key)
        new_fields: dict[str, Any] = {
            "project": {"key": p.target_project_key},
            "issuetype": {"name": p.issue_type},
            "summary": summary,
            "description": fields.get("description")
            or to_adf(f"Raised from incident {p.incident_key}."),
            "labels": ["from-incident"],
        }
        if fields.get("priority"):
            new_fields["priority"] = {"name": fields["priority"]["name"]}
        key = str((await ctx.jira.create_issue(new_fields, properties=step_marker(ctx)))["key"])
        reused = False
    await link_issues_with(ctx, p.incident_key, key, p.link_type)
    url = browse_url(ctx, key)
    return HandlerResult(
        message=f"{'Reused' if reused else 'Created'} {key} from incident "
        f"{p.incident_key} and linked them.",
        outputs={"key": key, "url": url, "incident_key": p.incident_key},
        resource=ResourceRef(type="jira_issue", key=key, title=str(fields.get("summary")), url=url),
        reused_existing=reused,
    )


async def _append_macro(
    ctx: HandlerContext, page_id: str, jql: str, heading: str, max_issues: int
) -> bool:
    page = await ctx.confluence.get_page(page_id)
    body = ((page.get("body") or {}).get("storage") or {}).get("value", "")
    macro = jira_issues_macro(jql, max_issues)
    if macro in body:
        return False
    version = int((page.get("version") or {}).get("number", 1)) + 1
    await ctx.confluence.update_page(
        page_id,
        str(page["title"]),
        f"{body}<h2>{heading}</h2>{macro}",
        version,
        "Linked Jira issues",
    )
    return True


async def embed_issues_in_page(ctx: HandlerContext, p: EmbedIssuesInPageParams) -> HandlerResult:
    changed = await _append_macro(ctx, p.page_id, p.jql, p.heading, p.max_issues)
    return HandlerResult(
        message=f"{'Embedded' if changed else 'Page already embeds'} Jira issues ({p.jql}) "
        f"on page {p.page_id}.",
        outputs={"page_id": p.page_id, "jql": p.jql},
        reused_existing=not changed,
    )


async def link_project_to_space(ctx: HandlerContext, p: LinkProjectToSpaceParams) -> HandlerResult:
    project = await require_project(ctx, p.project_key)
    space = await require_space(ctx, p.space_key)
    space_url = f"{ctx.site_url}/wiki/spaces/{p.space_key}"
    description = str(project.get("description") or "")
    changed = False
    if space_url not in description:
        await ctx.jira.update_project(
            p.project_key, {"description": f"{description}\n\nDocumentation: {space_url}".strip()}
        )
        changed = True
    if space.get("homepageId"):
        changed |= await _append_macro(
            ctx,
            str(space["homepageId"]),
            f"project = {p.project_key} ORDER BY created DESC",
            f"{p.project_key} issues",
            20,
        )
    return HandlerResult(
        message=f"Linked project {p.project_key} with space {p.space_key}.",
        outputs={"project_key": p.project_key, "space_key": p.space_key, "space_url": space_url},
        reused_existing=not changed,
    )
