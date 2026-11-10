"""Jira dashboards and gadgets."""

from typing import Any

from app.agents.handlers.base import HandlerContext, HandlerResult, same_name
from app.agents.handlers.jira_common import require_project
from app.schemas.agents import ResourceRef
from app.schemas.operations.jira_ops import CreateDashboardParams

GADGET_MODULES = {
    "filter_results": "com.atlassian.jira.gadgets:filter-results-gadget",
    "pie_chart": "com.atlassian.jira.gadgets:pie-chart-gadget",
    "created_vs_resolved": "com.atlassian.jira.gadgets:created-vs-resolved-issues-chart-gadget",
    "two_dimensional": "com.atlassian.jira.gadgets:two-dimensional-stats-gadget",
    "assigned_to_me": "com.atlassian.jira.gadgets:assigned-to-me-gadget",
    "average_age": "com.atlassian.jira.gadgets:average-age-chart-gadget",
    "resolution_time": "com.atlassian.jira.gadgets:resolution-time-gadget",
    "heat_map": "com.atlassian.jira.gadgets:heat-map-gadget",
    "activity_stream": "com.atlassian.streams.streams-jira-plugin:activitystream-gadget",
}


async def create_dashboard(ctx: HandlerContext, p: CreateDashboardParams) -> HandlerResult:
    for d in await ctx.jira.search_dashboards(p.name):
        if same_name(d.get("name"), p.name):
            return _result(ctx, d, 0, reused=True)
    share: list[dict[str, Any]] = []
    if p.share_with_project_key:
        project = await require_project(ctx, p.share_with_project_key)
        share = [{"type": "project", "project": {"id": str(project["id"])}}]
    dashboard = await ctx.jira.create_dashboard(
        {
            "name": p.name,
            "description": p.description,
            "sharePermissions": share,
            "editPermissions": [],
        }
    )
    dashboard_id = str(dashboard["id"])
    rows: dict[int, int] = {}
    for gadget in p.gadgets:
        row = rows.get(gadget.column, 0)
        rows[gadget.column] = row + 1
        payload: dict[str, Any] = {
            "moduleKey": GADGET_MODULES[gadget.type],
            "position": {"column": gadget.column, "row": row},
        }
        if gadget.title:
            payload["title"] = gadget.title
        await ctx.jira.add_gadget(dashboard_id, payload)
    return _result(ctx, dashboard, len(p.gadgets), reused=False)


def _result(ctx: HandlerContext, d: dict[str, Any], gadgets: int, *, reused: bool) -> HandlerResult:
    dashboard_id = str(d["id"])
    url = f"{ctx.site_url}/jira/dashboards/{dashboard_id}"
    note = (
        " Gadget data sources (filters) must be selected in each gadget's Configure menu; "
        "the public API cannot set legacy gadget preferences."
        if gadgets
        else ""
    )
    return HandlerResult(
        message=f"{'Reused' if reused else 'Created'} dashboard '{d.get('name')}' with "
        f"{gadgets} gadget(s).{note}",
        outputs={"id": dashboard_id, "url": url, "gadgets_added": gadgets},
        resource=ResourceRef(
            type="jira_dashboard", id=dashboard_id, title=str(d.get("name")), url=url
        ),
        reused_existing=reused,
    )
