"""JSM project configuration the public API lacks: queues and SLA goals.

Both use the endpoints Jira's own project settings call (verified live): queues via
``/rest/servicedesk/1/servicedesk/{key}/queues`` and SLA metrics via
``/rest/servicedesk/1/servicedesk/agent/{key}/sla/metrics``. Results are always read back.
"""

import copy
import re
from typing import Any

from app.agents.handlers.base import CheckResult, HandlerContext, HandlerResult, same_name
from app.agents.handlers.jsm_handlers import resolve_service_desk
from app.core.exceptions import OperationInputError
from app.schemas.agents import ResourceRef
from app.schemas.operations.jsm_ops import ConfigureSlaParams, CreateQueueParams

_UNIT_MS = {"d": 86_400_000, "h": 3_600_000, "m": 60_000, "s": 1_000}
_UNIT_WORDS = {"day": "d", "hour": "h", "hr": "h", "min": "m", "minute": "m", "sec": "s"}


def parse_duration(text: str) -> int:
    """'15m', '2h', '1h 30m', '1d', '15 minutes', '2 hours' -> milliseconds."""
    total = 0
    for amount, unit in re.findall(r"(\d+(?:\.\d+)?)\s*([a-zA-Z]+)", text):
        u = unit.casefold()
        key = next((v for w, v in _UNIT_WORDS.items() if u.startswith(w)), u[:1])
        if key not in _UNIT_MS:
            raise OperationInputError(f"Unknown time unit in '{text}'.")
        total += int(float(amount) * _UNIT_MS[key])
    if total <= 0:
        raise OperationInputError(f"'{text}' is not a duration (use e.g. 15m, 2h, 1d).")
    return total


def _strip_project(jql: str, key: str) -> str:
    """Jira prefixes the project itself; a repeated clause only clutters the queue JQL."""
    return re.sub(
        rf"^\s*project\s*(=|in)\s*\(?\s*\"?{re.escape(key)}\"?\s*\)?\s*(AND\s+)?",
        "",
        jql,
        flags=re.IGNORECASE,
    ).strip()


# --- queues ------------------------------------------------------------------------------------


async def check_create_queue(ctx: HandlerContext, p: CreateQueueParams) -> CheckResult:
    # Planning runs before earlier steps create the project; its JQL (project, SLA fields,
    # statuses) can only be validated once the project exists - create_queue does that.
    if await ctx.jira.find_project(p.project_key) is None:
        return CheckResult(notes=[f"Queue JQL is checked after {p.project_key} is created."])
    problems = await _queue_jql_problems(ctx, p.project_key, p.jql)
    if problems:
        return CheckResult(conflict=True, notes=[f"Invalid queue JQL: {problems}"])
    return CheckResult(notes=["Queue JQL validated by Jira."])


async def _queue_jql_problems(ctx: HandlerContext, project_key: str, jql: str) -> str:
    body = _strip_project(jql, project_key)
    if not body:
        return ""
    errors = (await ctx.jira.parse_jql([f"project = {project_key} AND ({body})"]))[0]
    return "; ".join(errors)


async def create_queue(ctx: HandlerContext, p: CreateQueueParams) -> HandlerResult:
    desk = await resolve_service_desk(ctx, p.project_key)
    url = f"{ctx.site_url}/jira/servicedesk/projects/{desk.project_key}/queues"
    existing = next(
        (q for q in await ctx.jsm.list_queues(desk.id) if same_name(q.get("name"), p.name)), None
    )
    if existing:
        return HandlerResult(
            message=f"Queue '{p.name}' already exists in {desk.project_key}.",
            outputs={"id": str(existing["id"]), "url": url},
            reused_existing=True,
        )
    problems = await _queue_jql_problems(ctx, desk.project_key, p.jql)
    if problems:
        raise OperationInputError(f"Invalid queue JQL: {problems}")
    jql = _strip_project(p.jql, desk.project_key) or "resolution = Unresolved"
    created = await ctx.jsm.create_queue(
        desk.project_key, {"name": p.name, "jql": jql, "columns": p.columns}
    )
    return HandlerResult(
        message=f"Created queue '{p.name}' in {desk.project_key} ({jql}).",
        outputs={"id": str(created.get("id")), "jql": jql, "url": url},
        resource=ResourceRef(type="jsm_queue", id=str(created.get("id")), title=p.name, url=url),
    )


# --- SLA ---------------------------------------------------------------------------------------


def _pick_metric(metrics: list[dict[str, Any]], wanted: str) -> dict[str, Any]:
    exact = next((m for m in metrics if same_name(m.get("name"), wanted)), None)
    if exact:
        return exact
    loose = [m for m in metrics if wanted.casefold() in str(m.get("name", "")).casefold()]
    if len(loose) == 1:
        return loose[0]
    raise OperationInputError(
        f"SLA metric '{wanted}' not found (have: {', '.join(str(m.get('name')) for m in metrics)})."
    )


def _pick_calendar(calendars: list[dict[str, Any]], wanted: str | None) -> int | None:
    """Calendar id for a name or a description such as 'business hours' / '24/7'."""
    if not wanted:
        return None
    w = wanted.casefold()
    by_name = next((c for c in calendars if same_name(c.get("name"), wanted)), None)
    if by_name:
        return int(by_name["id"])
    if any(k in w for k in ("24/7", "24x7", "always", "default")):
        return next((int(c["id"]) for c in calendars if c.get("default")), -1)
    business = [c for c in calendars if not c.get("default") and int(c.get("id", -1)) != -1]
    contains = [c for c in business if w in str(c.get("name", "")).casefold()]
    pool = contains or business
    choice = pool[0] if pool else None
    return int(choice["id"]) if choice else None


def _status_condition(kind: str, status_id: str, name: str) -> dict[str, Any]:
    return {
        "pluginKey": "com.atlassian.servicedesk",
        "factoryKey": "status-sla-condition-factory",
        "conditionId": status_id,
        "type": kind,
        "name": f"{'Entered Status' if kind == 'Stop' else 'Status'}: {name}",
        "missing": False,
    }


async def check_configure_sla(ctx: HandlerContext, p: ConfigureSlaParams) -> CheckResult:
    for g in p.goals:
        parse_duration(g.duration)
    errors = await ctx.jira.parse_jql([g.jql for g in p.goals if g.jql.strip()])
    bad = [f"{g.jql}: {'; '.join(e)}" for g, e in zip(p.goals, errors, strict=False) if e]
    if bad:
        return CheckResult(conflict=True, notes=[f"Invalid SLA goal JQL: {' | '.join(bad)}"])
    return CheckResult(notes=[f"{len(p.goals)} SLA goal(s) validated."])


async def configure_sla(ctx: HandlerContext, p: ConfigureSlaParams) -> HandlerResult:
    data = await ctx.jsm.get_sla_metrics(p.project_key)
    metric = copy.deepcopy(_pick_metric(data.get("timeMetrics") or [], p.metric))
    calendars = data.get("calendarRefs") or []
    config = metric.setdefault("config", {})
    old_goals = config.get("goals") or []
    default = next((g for g in old_goals if g.get("defaultGoal")), None)
    calendar_id = _pick_calendar(calendars, p.calendar)
    if calendar_id is None:
        calendar_id = int((default or {}).get("calendarId", -1))
    config["goals"] = [
        {
            "jqlQuery": g.jql,
            "duration": parse_duration(g.duration),
            "calendarId": calendar_id,
            "defaultGoal": False,
            "timeMetricId": 0,
            "subGoals": [],
        }
        for g in p.goals
    ] + ([{**default, "calendarId": calendar_id}] if default else [])

    statuses = await ctx.jira.project_statuses(p.project_key)
    definition = config.setdefault("definition", {})
    missing: list[str] = []
    for kind, names in (("Pause", p.pause_statuses), ("Stop", p.stop_statuses)):
        bucket = definition.setdefault(kind.lower(), [])
        have = {str(c.get("conditionId")) for c in bucket}
        for name in names:
            sid = statuses.get(name.casefold())
            if sid is None:
                missing.append(name)
            elif sid not in have:
                bucket.append(_status_condition(kind, sid, name))
    await ctx.jsm.update_sla_metric(p.project_key, str(metric["id"]), metric)

    cal_name = next((c.get("name") for c in calendars if int(c.get("id", 0)) == calendar_id), None)
    note = f"; statuses not in project skipped: {', '.join(missing)}" if missing else ""
    return HandlerResult(
        message=f"Set {len(p.goals)} goal(s) on SLA '{metric.get('name')}' in {p.project_key} "
        f"(calendar: {cal_name or calendar_id}){note}.",
        outputs={
            "metric_id": str(metric["id"]),
            "calendar": cal_name,
            "url": f"{ctx.site_url}/jira/servicedesk/projects/{p.project_key}/settings/sla",
        },
        resource=ResourceRef(
            type="jsm_sla",
            id=str(metric["id"]),
            title=str(metric.get("name")),
            url=f"{ctx.site_url}/jira/servicedesk/projects/{p.project_key}/settings/sla",
        ),
    )


async def read_sla_goals(ctx: HandlerContext, p: ConfigureSlaParams) -> list[tuple[str, int]]:
    data = await ctx.jsm.get_sla_metrics(p.project_key)
    metric = _pick_metric(data.get("timeMetrics") or [], p.metric)
    return [
        (str(g.get("jqlQuery") or ""), int(g.get("duration") or 0))
        for g in (metric.get("config") or {}).get("goals") or []
        if not g.get("defaultGoal")
    ]
