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
from app.core.exceptions import AtlassianError, AtlassianNotFoundError, OperationInputError
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
    if match is not None:
        await ctx.jira.transition_issue(p.issue_key, str(match["id"]))
        return HandlerResult(
            message=f"Moved {p.issue_key} to {p.to_status}.", outputs={"key": p.issue_key}
        )
    # Not one step away (e.g. Triage -> Resolved): walk the workflow's shortest path.
    path = await _status_path(ctx, p.issue_key, p.to_status)
    if not path:
        names = ", ".join(str(t.get("to", {}).get("name")) for t in transitions)
        statuses = await _workflow_statuses(ctx, p.issue_key)
        listing = ", ".join(f"{n} [{c}]" for n, c in statuses)
        if statuses and not any(same_name(n, p.to_status) for n, _ in statuses):
            raise OperationInputError(
                f"Status '{p.to_status}' does not exist in this issue's workflow "
                f"(statuses: {listing})."
            )
        raise OperationInputError(
            f"No path in the workflow from the current status to '{p.to_status}' "
            f"(next statuses: {names})."
        )
    visited: list[str] = []
    for status_id, status_name in path:
        options = await ctx.jira.get_transitions(p.issue_key)
        step = next((t for t in options if str((t.get("to") or {}).get("id")) == status_id), None)
        if step is None:
            raise OperationInputError(
                f"{p.issue_key} stopped in {visited[-1] if visited else 'its current status'}: "
                f"the transition to '{status_name}' needs fields or conditions the API cannot "
                "satisfy."
            )
        await ctx.jira.transition_issue(p.issue_key, str(step["id"]))
        visited.append(status_name)
    return HandlerResult(
        message=f"Moved {p.issue_key} to {p.to_status} via {' → '.join(visited)}.",
        outputs={"key": p.issue_key, "path": visited},
    )


async def _workflow_statuses(ctx: HandlerContext, issue_key: str) -> list[tuple[str, str]]:
    """(name, category) of every status in the issue's workflow (empty if unavailable)."""
    fields = (await ctx.jira.get_issue(issue_key, fields="project,issuetype"))["fields"]
    try:
        body = await ctx.jira.get_issue_type_workflow(
            str(fields["project"]["id"]), str(fields["issuetype"]["id"])
        )
    except AtlassianError:
        return []
    workflows = body.get("workflows") or []
    if not workflows:
        return []
    by_ref = {str(s.get("statusReference") or s.get("id")): s for s in body.get("statuses") or []}
    return [
        (str(by_ref[r].get("name")), str(by_ref[r].get("statusCategory") or ""))
        for r in (str(s.get("statusReference")) for s in workflows[0].get("statuses") or [])
        if r in by_ref
    ]


async def _status_path(ctx: HandlerContext, issue_key: str, target: str) -> list[tuple[str, str]]:
    """Shortest list of (status id, name) hops to `target` in the issue's own workflow."""
    fields = (await ctx.jira.get_issue(issue_key, fields="status,project,issuetype"))["fields"]
    try:
        body = await ctx.jira.get_issue_type_workflow(
            str(fields["project"]["id"]), str(fields["issuetype"]["id"])
        )
    except AtlassianError:
        return []
    workflows = body.get("workflows") or []
    if not workflows:
        return []
    ref_to = {
        str(s.get("statusReference") or s.get("id")): (str(s.get("id")), str(s.get("name")))
        for s in body.get("statuses") or []
    }
    edges: dict[str, set[str]] = {}
    anywhere: set[str] = set()
    for t in workflows[0].get("transitions") or []:
        to = ref_to.get(str(t.get("toStatusReference")), ("", ""))[0]
        if t.get("type") == "GLOBAL":
            anywhere.add(to)
        for link in t.get("links") or []:
            frm = ref_to.get(str(link.get("fromStatusReference")), ("", ""))[0]
            edges.setdefault(frm, set()).add(to)
    names = dict(ref_to.values())
    start = str(fields["status"]["id"])
    goal = next((sid for sid, n in names.items() if same_name(n, target)), None)
    if goal is None:
        return []
    previous: dict[str, str] = {start: start}
    queue = [start]
    while queue:
        current = queue.pop(0)
        if current == goal:
            break
        for nxt in sorted(edges.get(current, set()) | anywhere):
            if nxt and nxt not in previous:
                previous[nxt] = current
                queue.append(nxt)
    if goal not in previous:
        return []
    path: list[tuple[str, str]] = []
    node = goal
    while node != start:
        path.append((node, names.get(node, node)))
        node = previous[node]
    return list(reversed(path))[:8]


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
