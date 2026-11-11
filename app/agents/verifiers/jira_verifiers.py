"""Re-read Jira state after each Jira operation."""

from typing import Any

from app.agents.handlers.base import HandlerContext, same_name
from app.agents.handlers.jira_common import resolve_field_id
from app.agents.handlers.jira_config import find_global_status
from app.agents.handlers.jira_issues import link_exists
from app.agents.verifiers.base import Verifier, check, exists, out
from app.clients.jira.adf import adf_to_text
from app.core.exceptions import AtlassianNotFoundError
from app.schemas.agents import OperationOutcome, VerificationCheck

Checks = list[VerificationCheck]


async def project(ctx: HandlerContext, p: Any, o: OperationOutcome) -> Checks:
    key = getattr(p, "key", None) or p.project_key
    proj = await ctx.jira.get_project(key)
    checks = [exists("project", True, proj.get("key"))]
    if getattr(p, "name", None):
        checks.append(check("name", p.name, proj.get("name")))
    if getattr(p, "description", None):
        checks.append(
            check("description", p.description.strip(), str(proj.get("description") or "").strip())
        )
    return checks


async def issue_type(ctx: HandlerContext, p: Any, o: OperationOutcome) -> Checks:
    types = await ctx.jira.list_issue_types()
    return [exists("issue type", any(str(t["id"]) == out(o, "id") for t in types), p.name)]


async def issue_type_scheme(ctx: HandlerContext, p: Any, o: OperationOutcome) -> Checks:
    proj = await ctx.jira.get_project(p.project_key)
    scheme = await ctx.jira.get_project_issue_type_scheme(str(proj["id"]))
    scheme_id = str((scheme or {}).get("id"))
    items = set(await ctx.jira.list_issue_type_scheme_items(scheme_id)) if scheme else set()
    return [
        check("assigned scheme", out(o, "scheme_id"), scheme_id),
        check("issue types", sorted(o.outputs.get("issue_type_ids", [])), sorted(items)),
    ]


async def custom_field(ctx: HandlerContext, p: Any, o: OperationOutcome) -> Checks:
    # The full field list lags behind creation; the field search endpoint does not.
    field = await ctx.jira.find_field(out(o, "id"))
    checks = [exists("field", field is not None, out(o, "id"))]
    if p.options:
        contexts = await ctx.jira.list_field_contexts(out(o, "id"))
        values = (
            {
                str(x.get("value"))
                for x in await ctx.jira.list_field_options(out(o, "id"), str(contexts[0]["id"]))
            }
            if contexts
            else set()
        )
        checks.append(check("options", True, set(p.options) <= values, set(p.options) <= values))
    return checks


async def screen(ctx: HandlerContext, p: Any, o: OperationOutcome) -> Checks:
    screen_id = out(o, "id") or out(o, "screen_id")
    present: set[str] = set()
    for tab in await ctx.jira.get_screen_tabs(screen_id):
        present |= {str(f["id"]) for f in await ctx.jira.get_tab_fields(screen_id, str(tab["id"]))}
    wanted = set(o.outputs.get("fields_added") or [])
    return [
        exists("screen", True, screen_id),
        check("fields on screen", True, wanted <= present, wanted <= present),
    ]


async def field_configuration(ctx: HandlerContext, p: Any, o: OperationOutcome) -> Checks:
    items = {str(i["id"]): i for i in await ctx.jira.get_field_configuration_items(out(o, "id"))}
    checks = [exists("field configuration", True, out(o, "id"))]
    for ref, flag in [
        *((r, "isRequired") for r in p.required_fields),
        *((r, "isHidden") for r in p.hidden_fields),
    ]:
        item = items.get(await resolve_field_id(ctx, ref), {})
        checks.append(check(f"{ref} {flag}", True, bool(item.get(flag))))
    return checks


async def priority(ctx: HandlerContext, p: Any, o: OperationOutcome) -> Checks:
    found = [
        x for x in await ctx.jira.search_priorities(p.name) if same_name(x.get("name"), p.name)
    ]
    return [exists("priority", bool(found), p.name)]


async def statuses(ctx: HandlerContext, p: Any, o: OperationOutcome) -> Checks:
    return [
        exists(f"status {s.name}", await find_global_status(ctx, s.name) is not None, s.name)
        for s in p.statuses
    ]


async def workflow(ctx: HandlerContext, p: Any, o: OperationOutcome) -> Checks:
    found = [w for w in await ctx.jira.search_workflows(p.name) if same_name(w.get("name"), p.name)]
    return [exists("workflow", bool(found), p.name)]


async def workflow_scheme(ctx: HandlerContext, p: Any, o: OperationOutcome) -> Checks:
    proj = await ctx.jira.get_project(p.project_key)
    scheme = await ctx.jira.get_project_workflow_scheme(str(proj["id"]))
    return [check("assigned workflow scheme", out(o, "scheme_id"), str((scheme or {}).get("id")))]


async def configured_scheme(ctx: HandlerContext, p: Any, o: OperationOutcome) -> Checks:
    scheme = await ctx.jira.get_project_workflow_scheme(
        out(o, "project_id") or str((await ctx.jira.get_project(p.project_key))["id"])
    )
    checks = [check("project workflow scheme", out(o, "scheme_id"), str((scheme or {}).get("id")))]
    if scheme:
        full = await ctx.jira.get_workflow_scheme(str(scheme["id"]))
        mapped = {str(v) for v in (full.get("issueTypeMappings") or {}).values()}
        for m in p.mappings:
            checks.append(exists(f"{m.workflow_name} mapped", m.workflow_name in mapped))
    return checks


async def updated_workflow(ctx: HandlerContext, p: Any, o: OperationOutcome) -> Checks:
    body = await ctx.jira.get_workflows_by_name([p.workflow_name])
    wf = (body.get("workflows") or [{}])[0]
    names = {str(t.get("name")).casefold() for t in wf.get("transitions") or []}
    checks = [exists(f"transition {t.name}", t.name.casefold() in names) for t in p.add_transitions]
    refs = {
        str(s.get("name")).casefold(): str(s.get("statusReference") or s.get("id"))
        for s in body.get("statuses") or []
    }
    for a in p.approvals:
        ref = refs.get(a.status.casefold())
        status: dict[str, Any] = next(
            (s for s in wf.get("statuses") or [] if str(s.get("statusReference")) == ref), {}
        )
        active = (status.get("approvalConfiguration") or {}).get("active") == "true"
        checks.append(exists(f"approval on {a.status}", active))
    return checks


async def issue(ctx: HandlerContext, p: Any, o: OperationOutcome) -> Checks:
    key = out(o, "key") or p.issue_key
    data = (
        await ctx.jira.get_issue(key, fields="summary,issuetype,parent,labels,description,duedate")
    )["fields"]
    checks = [exists("issue", True, key)]
    if getattr(p, "summary", None):
        checks.append(check("summary", p.summary, data.get("summary")))
    if getattr(p, "issue_type", None):
        checks.append(check("issue type", p.issue_type, (data.get("issuetype") or {}).get("name")))
    if getattr(p, "parent_key", None):
        checks.append(check("parent", p.parent_key, (data.get("parent") or {}).get("key")))
    if getattr(p, "due_date", None):
        checks.append(check("due date", p.due_date, data.get("duedate")))
    if getattr(p, "description", None):
        text = adf_to_text(data.get("description"))
        checks.append(check("description", True, bool(text.strip()), bool(text.strip())))
    return checks


async def transition(ctx: HandlerContext, p: Any, o: OperationOutcome) -> Checks:
    status = (await ctx.jira.get_issue(p.issue_key, fields="status"))["fields"]["status"]["name"]
    return [check("status", p.to_status, status)]


async def link(ctx: HandlerContext, p: Any, o: OperationOutcome) -> Checks:
    source = getattr(p, "from_issue", None) or p.incident_key
    target = getattr(p, "to_issue", None) or p.issue_key
    found = await link_exists(ctx, source, target, str(o.outputs.get("link_type") or p.link_type))
    return [exists(f"link {source} ↔ {target}", found, o.outputs.get("link_type"))]


async def deleted_issue(ctx: HandlerContext, p: Any, o: OperationOutcome) -> Checks:
    try:
        await ctx.jira.get_issue(p.issue_key, fields="summary")
    except AtlassianNotFoundError:
        return [check("issue deleted", True, True)]
    return [check("issue deleted", True, False)]


async def filter_(ctx: HandlerContext, p: Any, o: OperationOutcome) -> Checks:
    flt = await ctx.jira.get_filter(out(o, "id"))
    return [check("name", p.name, flt.get("name"))]


async def board(ctx: HandlerContext, p: Any, o: OperationOutcome) -> Checks:
    b = await ctx.jira.get_board(out(o, "id"))
    return [check("name", p.name, b.get("name")), check("type", p.board_type, b.get("type"))]


async def sprint(ctx: HandlerContext, p: Any, o: OperationOutcome) -> Checks:
    s = await ctx.jira.get_sprint(out(o, "id"))
    return [check("name", p.name, s.get("name"))]


async def sprint_started(ctx: HandlerContext, p: Any, o: OperationOutcome) -> Checks:
    return [check("state", "active", (await ctx.jira.get_sprint(p.sprint_id)).get("state"))]


async def sprint_issues(ctx: HandlerContext, p: Any, o: OperationOutcome) -> Checks:
    keys = {i["key"] for i in await ctx.jira.get_sprint_issues(p.sprint_id)}
    return [check("issues in sprint", True, set(p.issue_keys) <= keys, set(p.issue_keys) <= keys)]


async def in_backlog(ctx: HandlerContext, p: Any, o: OperationOutcome) -> Checks:
    checks = []
    for key in p.issue_keys:
        sprint = (await ctx.jira.get_agile_issue(key))["fields"].get("sprint")
        checks.append(check(f"{key} in backlog", None, (sprint or {}).get("name"), sprint is None))
    return checks


async def dashboard(ctx: HandlerContext, p: Any, o: OperationOutcome) -> Checks:
    d = await ctx.jira.get_dashboard(out(o, "id"))
    checks = [check("name", p.name, d.get("name"))]
    expected = int(o.outputs.get("gadgets_added") or 0)
    if expected and not o.reused_existing:
        count = len(await ctx.jira.get_gadgets(out(o, "id")))
        checks.append(check("gadgets", expected, count, count >= expected))
    return checks


async def automation(ctx: HandlerContext, p: Any, o: OperationOutcome) -> Checks:
    if not out(o, "rule_id"):
        return [exists("rule id returned", False)]
    rule = await ctx.jira.get_automation_rule(out(o, "cloud_id"), out(o, "rule_id"))
    name = (rule.get("rule") or rule).get("name")
    return [check("rule name", p.name, name)]


VERIFIERS: dict[str, Verifier] = {
    "jira.create_project": project,
    "jira.update_project": project,
    "jira.create_issue_type": issue_type,
    "jira.configure_issue_types": issue_type_scheme,
    "jira.create_custom_field": custom_field,
    "jira.create_screen": screen,
    "jira.add_field_to_screen": screen,
    "jira.create_field_configuration": field_configuration,
    "jira.create_priority": priority,
    "jira.create_statuses": statuses,
    "jira.create_workflow": workflow,
    "jira.assign_workflow": workflow_scheme,
    "jira.configure_workflow_scheme": configured_scheme,
    "jira.update_workflow": updated_workflow,
    "jira.create_issue": issue,
    "jira.update_issue": issue,
    "jira.transition_issue": transition,
    "jira.link_issues": link,
    "jira.delete_issue": deleted_issue,
    "jira.create_filter": filter_,
    "jira.create_board": board,
    "jira.create_sprint": sprint,
    "jira.start_sprint": sprint_started,
    "jira.move_issues_to_sprint": sprint_issues,
    "jira.move_issues_to_backlog": in_backlog,
    "jira.create_dashboard": dashboard,
    "jira.create_automation_rule": automation,
}
