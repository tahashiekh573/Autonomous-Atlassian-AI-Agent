"""Jira dashboards and gadgets.

Gadgets are resolved against the site's own gadget directory (GET /dashboard/gadgets):
legacy gadgets must be added by ``uri``, newer dashboard items by ``moduleKey``, and sites
differ in what is installed. Hard-coding module keys made Jira answer 400 "The module key of
this gadget is not present in the directory".
"""

from typing import Any

from app.agents.handlers.base import HandlerContext, HandlerResult, same_name
from app.agents.handlers.jira_common import require_project
from app.core.exceptions import AtlassianError
from app.schemas.agents import ResourceRef
from app.schemas.operations.jira_ops import CreateDashboardParams, GadgetDef

# Our gadget type → a fragment that identifies it in the directory's uri / moduleKey.
GADGET_IDS: dict[str, str] = {
    "filter_results": ":filter-results-gadget",
    "pie_chart": ":pie-chart-gadget",
    "created_vs_resolved": ":created-vs-resolved-issues-chart-gadget",
    "two_dimensional": ":two-dimensional-stats-gadget",
    "assigned_to_me": ":assigned-to-me-gadget",
    "average_age": ":average-age-chart-gadget",
    "resolution_time": ":resolution-time-gadget",
    "heat_map": ":heat-map-gadget",
    "activity_stream": ":activitystream-gadget",
    "work_item_statistics": ":stats-gadget",
    "workload_pie": ":workloadpie-gadget",
    "time_to_first_response": ":firstresponse-gadget",
    "time_in_status": ":timeinstatus-gadget",
    "recently_created": ":recently-created-chart-gadget",
    "time_since": ":time-since-chart-gadget",
    "issues_in_progress": ":in-progress-gadget",
    "sprint_burndown": ":greenhopper-gadget-sprint-burndown",
    "sprint_health": ":greenhopper-gadget-sprint-health",
    "sprint_days_remaining": ":greenhopper-gadget-sprint-days-remaining",
    "issues_calendar": ":issuescalendar-gadget",
    "service_project_report": ":custom-report-dashboard-item",
    "filter_counts": ":filter-count-dashboard-item",
}


def gadget_reference(directory: list[dict[str, Any]], gadget_type: str) -> dict[str, str] | None:
    """Payload fragment ({"uri": ...} or {"moduleKey": ...}) for a gadget, if installed."""
    fragment = GADGET_IDS[gadget_type]
    for entry in directory:
        uri, module_key = entry.get("uri"), entry.get("moduleKey")
        if uri and fragment in str(uri):
            return {"uri": str(uri)}
        if module_key and str(module_key).endswith(fragment):
            return {"moduleKey": str(module_key)}
    return None


async def create_dashboard(ctx: HandlerContext, p: CreateDashboardParams) -> HandlerResult:
    for d in await ctx.jira.search_dashboards(p.name):
        if same_name(d.get("name"), p.name):
            return _result(ctx, d, [], [], reused=True)
    directory = await ctx.jira.list_available_gadgets() if p.gadgets else []
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
    added: list[str] = []
    skipped: list[str] = []
    configured: list[str] = []
    rows: dict[int, int] = {}
    for gadget in p.gadgets:
        reference = gadget_reference(directory, gadget.type)
        if reference is None:
            skipped.append(f"{gadget.type} (not installed on this site)")
            continue
        row = rows.get(gadget.column, 0)
        payload: dict[str, Any] = {**reference, "position": {"column": gadget.column, "row": row}}
        if gadget.title:
            payload["title"] = gadget.title
        try:
            created = await ctx.jira.add_gadget(dashboard_id, payload)
        except AtlassianError as exc:
            skipped.append(f"{gadget.type} ({exc.message})")
            continue
        rows[gadget.column] = row + 1
        added.append(gadget.type)
        if "uri" in reference and await _configure(
            ctx, p, gadget, dashboard_id, str(created["id"])
        ):
            configured.append(gadget.type)
    return _result(ctx, dashboard, added, skipped, reused=False, configured=configured)


async def _source(ctx: HandlerContext, p: CreateDashboardParams, gadget: GadgetDef) -> str | None:
    """'filter-<id>' for a gadget-specific JQL (saved filter reused by name), else the project."""
    project_key = p.project_key or p.share_with_project_key
    if gadget.jql:
        name = f"{p.name}: {gadget.title or gadget.type}"[:255]
        found = next(
            (f for f in await ctx.jira.search_filters(name) if same_name(f.get("name"), name)),
            None,
        )
        if found is None:
            jql = gadget.jql
            if project_key and "project" not in jql.casefold():
                jql = f"project = {project_key} AND ({jql})"
            share: list[dict[str, Any]] = []
            if project_key:
                project = await require_project(ctx, project_key)
                share = [{"type": "project", "project": {"id": str(project["id"])}}]
            found = await ctx.jira.create_filter(
                {"name": name, "jql": jql, "sharePermissions": share}
            )
        return f"filter-{found['id']}"
    if project_key:
        return f"project-{(await require_project(ctx, project_key))['id']}"
    return None


async def _configure(
    ctx: HandlerContext,
    p: CreateDashboardParams,
    gadget: GadgetDef,
    dashboard_id: str,
    gadget_id: str,
) -> bool:
    """Point a legacy gadget at its data and mark it configured (else it shows 'Configure')."""
    source = await _source(ctx, p, gadget)
    if source is None:
        return False
    try:
        fields = await ctx.jira.get_gadget_prefs(dashboard_id, gadget_id)
        wanted = {
            "projectOrFilterId": source,
            "filterId": source,
            "statType": gadget.stat_type or "priorities",
            "xstattype": gadget.stat_type or "statuses",
            "ystattype": "priorities",
            "daysprevious": str(gadget.days),
            "periodName": "daily",
            "num": "10",
            "isConfigured": "true",
        }
        prefs = {k: v for k, v in wanted.items() if k in fields}
        if not prefs:
            return False
        await ctx.jira.set_gadget_prefs(dashboard_id, gadget_id, prefs)
        after = await ctx.jira.get_gadget_prefs(dashboard_id, gadget_id)
        return after.get("isConfigured") == "true"
    except AtlassianError:
        return False


def _result(
    ctx: HandlerContext,
    d: dict[str, Any],
    added: list[str],
    skipped: list[str],
    *,
    reused: bool,
    configured: list[str] | None = None,
) -> HandlerResult:
    configured = configured or []
    dashboard_id = str(d["id"])
    url = f"{ctx.site_url}/jira/dashboards/{dashboard_id}"
    message = f"{'Reused' if reused else 'Created'} dashboard '{d.get('name')}'"
    if added:
        message += f" with {len(added)} gadget(s) ({', '.join(added)})"
        unconfigured = [g for g in added if g not in configured]
        if configured:
            message += f"; {len(configured)} configured with their data"
        if unconfigured:
            message += f"; set the data source in Configure for: {', '.join(unconfigured)}"
    if skipped:
        message += f". Gadgets not added: {'; '.join(skipped)}"
    return HandlerResult(
        message=message + ".",
        outputs={
            "id": dashboard_id,
            "url": url,
            "gadgets_added": len(added),
            "gadgets_configured": len(configured),
            "gadgets_skipped": skipped,
        },
        resource=ResourceRef(
            type="jira_dashboard", id=dashboard_id, title=str(d.get("name")), url=url
        ),
        reused_existing=reused,
    )
