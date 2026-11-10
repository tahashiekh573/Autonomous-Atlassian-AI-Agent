"""Read-only JSM reports built on JQL (SLA functions and aggregations)."""

from collections import Counter
from typing import Any

from app.agents.handlers.base import HandlerContext, HandlerResult
from app.agents.handlers.jira_common import require_project
from app.schemas.operations.jsm_ops import RequestReportParams, SlaReportParams

_SLA_STATES = ("breached", "running", "paused", "completed")


def _jql_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


async def sla_report(ctx: HandlerContext, p: SlaReportParams) -> HandlerResult:
    await require_project(ctx, p.project_key)
    base = f"project = {p.project_key}" + (f" AND ({p.jql_filter})" if p.jql_filter else "")
    data: dict[str, Any] = {}
    for sla in p.sla_names:
        field = _jql_string(sla)
        counts: dict[str, Any] = {
            state: await ctx.jira.approximate_count(f"{base} AND {field} = {state}()")
            for state in _SLA_STATES
        }
        total = counts["completed"] + counts["breached"]
        counts["met_rate_percent"] = (
            round(100 * (1 - counts["breached"] / total), 1) if total else None
        )
        data[sla] = counts
    return HandlerResult(
        message=f"SLA report for {p.project_key} (approximate counts).",
        outputs={"report": "sla", "data": data},
    )


async def request_report(ctx: HandlerContext, p: RequestReportParams) -> HandlerResult:
    await require_project(ctx, p.project_key)
    jql = f"project = {p.project_key} AND created >= -{p.days}d"
    if p.jql_filter:
        jql += f" AND ({p.jql_filter})"
    issues = await ctx.jira.search(jql, fields=[p.group_by, "resolutiondate"], max_results=1000)
    attr = "displayName" if p.group_by == "assignee" else "name"
    counts = Counter(str((i["fields"].get(p.group_by) or {}).get(attr) or "None") for i in issues)
    resolved = sum(1 for i in issues if i["fields"].get("resolutiondate"))
    return HandlerResult(
        message=f"{len(issues)} request(s) in the last {p.days} days.",
        outputs={
            "report": "requests",
            "data": {
                "total": len(issues),
                "resolved": resolved,
                f"by_{p.group_by}": dict(counts.most_common()),
            },
        },
    )
