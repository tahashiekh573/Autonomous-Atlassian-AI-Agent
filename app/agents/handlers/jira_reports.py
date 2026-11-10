"""Read-only Jira reports computed from live data."""

from collections import Counter
from typing import Any

from app.agents.handlers.base import HandlerContext, HandlerResult
from app.agents.handlers.jira_common import require_project
from app.core.exceptions import OperationInputError
from app.schemas.operations.jira_ops import GenerateReportParams

_FIELDS = ["status", "issuetype", "priority", "assignee"]


def _name(issue: dict[str, Any], field: str, attr: str = "name") -> str:
    value = issue["fields"].get(field) or {}
    return str(
        value.get(attr) or "Unassigned" if field == "assignee" else value.get(attr) or "None"
    )


def _counts(issues: list[dict[str, Any]], field: str, attr: str = "name") -> dict[str, int]:
    return dict(Counter(_name(i, field, attr) for i in issues).most_common())


async def generate_report(ctx: HandlerContext, p: GenerateReportParams) -> HandlerResult:
    await require_project(ctx, p.project_key)
    key = p.project_key
    data: dict[str, Any]
    if p.report == "project_summary":
        issues = await ctx.jira.search(f"project = {key}", fields=_FIELDS, max_results=1000)
        data = {
            "total": len(issues),
            "by_status": _counts(issues, "status"),
            "by_type": _counts(issues, "issuetype"),
            "by_priority": _counts(issues, "priority"),
        }
    elif p.report == "workload":
        issues = await ctx.jira.search(
            f"project = {key} AND resolution = Unresolved", fields=_FIELDS, max_results=1000
        )
        data = {
            "open_issues": len(issues),
            "by_assignee": _counts(issues, "assignee", "displayName"),
        }
    elif p.report == "issue_tracking":
        window = f"-{p.days}d"
        data = {
            "days": p.days,
            "created": await ctx.jira.approximate_count(f"project = {key} AND created >= {window}"),
            "resolved": await ctx.jira.approximate_count(
                f"project = {key} AND resolved >= {window}"
            ),
            "open": await ctx.jira.approximate_count(
                f"project = {key} AND resolution = Unresolved"
            ),
        }
    else:
        if not p.sprint_id:
            raise OperationInputError("sprint_id is required for a sprint report.")
        sprint = await ctx.jira.get_sprint(p.sprint_id)
        issues = await ctx.jira.get_sprint_issues(p.sprint_id, fields="status")
        done = sum(
            1
            for i in issues
            if ((i["fields"].get("status") or {}).get("statusCategory") or {}).get("key") == "done"
        )
        data = {
            "sprint": sprint.get("name"),
            "state": sprint.get("state"),
            "total": len(issues),
            "done": done,
            "not_done": len(issues) - done,
            "by_status": _counts(issues, "status"),
        }
    return HandlerResult(
        message=f"{p.report.replace('_', ' ').title()} report for {key}.",
        outputs={"report": p.report, "data": data},
    )
