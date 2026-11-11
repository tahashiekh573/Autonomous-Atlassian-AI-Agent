"""Jira issue handlers: create/update/transition/link/delete/search."""

from typing import Any

from app.agents.handlers.base import (
    CheckResult,
    HandlerContext,
    HandlerResult,
    find_step_issue,
    same_name,
    step_marker,
)
from app.agents.handlers.jira_common import browse_url, require_project, resolve_field_id
from app.clients.jira.adf import to_adf
from app.core.exceptions import AtlassianNotFoundError, OperationInputError
from app.schemas.agents import ResourceRef
from app.schemas.operations.jira_ops import (
    CreateIssueParams,
    DeleteIssueParams,
    LinkIssuesParams,
    SearchIssuesParams,
    TransitionIssueParams,
    UpdateIssueParams,
)


async def _common_fields(
    ctx: HandlerContext, p: CreateIssueParams | UpdateIssueParams
) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    if p.summary is not None:
        fields["summary"] = p.summary
    if p.description:
        fields["description"] = to_adf(p.description)
    if p.parent_key:
        fields["parent"] = {"key": p.parent_key}
    if p.priority:
        fields["priority"] = {"name": p.priority}
    if p.due_date:
        fields["duedate"] = p.due_date
    if p.start_date:
        fields[await resolve_field_id(ctx, "Start date")] = p.start_date
    for name, value in p.fields.items():
        field_id = name if name.startswith("customfield_") else await resolve_field_id(ctx, name)
        fields[field_id] = value
    return fields


BACKLOG_IS_NOT_A_STATUS = (
    "'Backlog' is a board location, not a workflow status: issues outside a sprint are already "
    "in the backlog. Use jira.move_issues_to_backlog to take issues out of a sprint."
)


async def check_create_issue(ctx: HandlerContext, p: CreateIssueParams) -> CheckResult:
    project = await ctx.jira.find_project(p.project_key)
    if project is None:
        return CheckResult(notes=[f"Project {p.project_key} will need to exist first."])
    names = [str(t.get("name")) for t in project.get("issueTypes") or []]
    if not any(same_name(n, p.issue_type) for n in names):
        return CheckResult(
            notes=[
                f"Issue type '{p.issue_type}' not yet in {p.project_key} (has: {', '.join(names)})."
            ]
        )
    return CheckResult()


async def create_issue(ctx: HandlerContext, p: CreateIssueParams) -> HandlerResult:
    await require_project(ctx, p.project_key)
    existing = await find_step_issue(ctx, p.project_key, p.summary)
    if existing:
        key = str(existing["key"])
        return _issue_result(ctx, key, existing.get("id"), p.summary, reused=True)
    fields = await _common_fields(ctx, p)
    fields.update(
        {
            "project": {"key": p.project_key},
            "issuetype": {"name": p.issue_type},
            "labels": list(p.labels),
        }
    )
    if p.assignee_account_id:
        fields["assignee"] = {"accountId": p.assignee_account_id}
    created = await ctx.jira.create_issue(fields, properties=step_marker(ctx))
    return _issue_result(ctx, str(created["key"]), created.get("id"), p.summary, reused=False)


def _issue_result(
    ctx: HandlerContext, key: str, issue_id: Any, summary: str, *, reused: bool
) -> HandlerResult:
    url = browse_url(ctx, key)
    return HandlerResult(
        message=f"{'Reused' if reused else 'Created'} issue {key}: {summary}",
        outputs={"key": key, "id": str(issue_id), "url": url},
        resource=ResourceRef(type="jira_issue", id=str(issue_id), key=key, title=summary, url=url),
        reused_existing=reused,
    )


async def update_issue(ctx: HandlerContext, p: UpdateIssueParams) -> HandlerResult:
    fields = await _common_fields(ctx, p)
    if p.labels is not None:
        fields["labels"] = p.labels
    if not fields:
        raise OperationInputError("Nothing to update.")
    await ctx.jira.update_issue(p.issue_key, fields)
    return HandlerResult(
        message=f"Updated {p.issue_key} ({len(fields)} field(s)).",
        outputs={"key": p.issue_key, "url": browse_url(ctx, p.issue_key)},
    )


async def transition_issue(ctx: HandlerContext, p: TransitionIssueParams) -> HandlerResult:
    issue = await ctx.jira.get_issue(p.issue_key, fields="status")
    if same_name(issue["fields"]["status"]["name"], p.to_status):
        return HandlerResult(
            message=f"{p.issue_key} is already in {p.to_status}.",
            outputs={"key": p.issue_key},
            reused_existing=True,
        )
    if same_name(p.to_status, "backlog"):
        raise OperationInputError(BACKLOG_IS_NOT_A_STATUS)
    transitions = await ctx.jira.get_transitions(p.issue_key)
    match = next(
        (
            t
            for t in transitions
            if same_name(t.get("to", {}).get("name"), p.to_status)
            or same_name(t.get("name"), p.to_status)
        ),
        None,
    )
    if match is None:
        names = ", ".join(str(t.get("to", {}).get("name")) for t in transitions)
        raise OperationInputError(
            f"No transition from current status to '{p.to_status}' (reachable: {names})."
        )
    await ctx.jira.transition_issue(p.issue_key, str(match["id"]))
    return HandlerResult(
        message=f"Moved {p.issue_key} to {p.to_status}.", outputs={"key": p.issue_key}
    )


async def resolve_link_type(ctx: HandlerContext, name: str) -> str:
    types = await ctx.jira.list_link_types()
    for t in types:
        if name.casefold() in {str(t.get(k, "")).casefold() for k in ("name", "inward", "outward")}:
            return str(t["name"])
    available = ", ".join(str(t.get("name")) for t in types)
    raise OperationInputError(f"Issue link type '{name}' does not exist (available: {available}).")


async def link_exists(ctx: HandlerContext, source: str, target: str, link_type: str) -> bool:
    issue = await ctx.jira.get_issue(source, fields="issuelinks")
    for link in issue["fields"].get("issuelinks") or []:
        other = (link.get("outwardIssue") or link.get("inwardIssue") or {}).get("key")
        if other == target and same_name(link.get("type", {}).get("name"), link_type):
            return True
    return False


async def link_issues_with(
    ctx: HandlerContext, source: str, target: str, link_type: str
) -> HandlerResult:
    type_name = await resolve_link_type(ctx, link_type)
    if await link_exists(ctx, source, target, type_name):
        return HandlerResult(
            message=f"{source} and {target} are already linked ({type_name}).",
            outputs={"from": source, "to": target, "link_type": type_name},
            reused_existing=True,
        )
    await ctx.jira.link_issues(type_name, source, target)
    return HandlerResult(
        message=f"Linked {source} → {target} ({type_name}).",
        outputs={"from": source, "to": target, "link_type": type_name},
        resource=ResourceRef(type="jira_issue_link", key=f"{source}->{target}", title=type_name),
    )


async def link_issues(ctx: HandlerContext, p: LinkIssuesParams) -> HandlerResult:
    return await link_issues_with(ctx, p.from_issue, p.to_issue, p.link_type)


async def check_delete_issue(ctx: HandlerContext, p: DeleteIssueParams) -> CheckResult:
    try:
        issue = await ctx.jira.get_issue(p.issue_key, fields="summary,subtasks")
    except AtlassianNotFoundError:
        return CheckResult(notes=[f"{p.issue_key} does not exist."], conflict=True)
    subtasks = len(issue["fields"].get("subtasks") or [])
    note = f"Will permanently delete {p.issue_key} '{issue['fields'].get('summary')}'"
    return CheckResult(notes=[note + (f" and {subtasks} sub-task(s)." if subtasks else ".")])


async def delete_issue(ctx: HandlerContext, p: DeleteIssueParams) -> HandlerResult:
    await ctx.jira.delete_issue(p.issue_key)
    return HandlerResult(message=f"Deleted {p.issue_key}.", outputs={"key": p.issue_key})


async def search_issues(ctx: HandlerContext, p: SearchIssuesParams) -> HandlerResult:
    issues = await ctx.jira.search(
        p.jql,
        fields=["summary", "status", "assignee", "priority", "issuetype"],
        max_results=p.max_results,
    )
    rows = [
        {
            "key": i["key"],
            "summary": i["fields"].get("summary"),
            "status": (i["fields"].get("status") or {}).get("name"),
            "type": (i["fields"].get("issuetype") or {}).get("name"),
            "assignee": (i["fields"].get("assignee") or {}).get("displayName"),
        }
        for i in issues
    ]
    return HandlerResult(message=f"{len(rows)} issue(s) match.", outputs={"issues": rows})
