"""Jira administration handlers: issue types, schemes, fields, screens, field configs,
priorities, statuses."""

from typing import Any

from app.agents.handlers.base import CheckResult, HandlerContext, HandlerResult, same_name
from app.agents.handlers.jira_common import (
    invalidate_fields,
    require_project,
    resolve_field_id,
)
from app.core.exceptions import (
    AtlassianApiError,
    OperationConflictError,
    OperationInputError,
    OperationUnsupportedError,
)
from app.schemas.agents import ResourceRef
from app.schemas.operations.jira_ops import (
    AddFieldToScreenParams,
    ConfigureIssueTypesParams,
    CreateCustomFieldParams,
    CreateFieldConfigurationParams,
    CreateIssueTypeParams,
    CreatePriorityParams,
    CreateScreenParams,
    CreateStatusesParams,
)

_CF = "com.atlassian.jira.plugin.system.customfieldtypes:"
FIELD_TYPES: dict[str, tuple[str, str]] = {
    "text": (f"{_CF}textfield", f"{_CF}textsearcher"),
    "textarea": (f"{_CF}textarea", f"{_CF}textsearcher"),
    "number": (f"{_CF}float", f"{_CF}exactnumber"),
    "date": (f"{_CF}datepicker", f"{_CF}daterange"),
    "datetime": (f"{_CF}datetime", f"{_CF}datetimerange"),
    "select": (f"{_CF}select", f"{_CF}multiselectsearcher"),
    "multiselect": (f"{_CF}multiselect", f"{_CF}multiselectsearcher"),
    "user": (f"{_CF}userpicker", f"{_CF}userpickergroupsearcher"),
    "labels": (f"{_CF}labels", f"{_CF}labelsearcher"),
    "url": (f"{_CF}url", f"{_CF}exacttextsearcher"),
}
SUBTASK_NAMES = {"sub-task", "subtask", "sub task"}


def _global_types(types: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [t for t in types if not t.get("scope")]


async def create_issue_type(ctx: HandlerContext, p: CreateIssueTypeParams) -> HandlerResult:
    for t in _global_types(await ctx.jira.list_issue_types()):
        if same_name(t.get("name"), p.name):
            return HandlerResult(
                message=f"Issue type '{p.name}' already exists.",
                outputs={"id": str(t["id"]), "name": t["name"]},
                reused_existing=True,
            )
    created = await ctx.jira.create_issue_type(
        p.name, p.description, -1 if p.level == "subtask" else 0
    )
    return HandlerResult(
        message=f"Created issue type '{p.name}'.",
        outputs={"id": str(created["id"]), "name": p.name},
        resource=ResourceRef(type="jira_issue_type", id=str(created["id"]), title=p.name),
    )


async def check_configure_issue_types(
    ctx: HandlerContext, p: ConfigureIssueTypesParams
) -> CheckResult:
    project = await ctx.jira.find_project(p.project_key)
    if project is None:
        return CheckResult(notes=[f"Project {p.project_key} must be created first."])
    if project.get("style") == "next-gen":
        return CheckResult(
            conflict=True,
            notes=[
                f"{p.project_key} is team-managed; issue type schemes apply only to "
                "company-managed projects."
            ],
        )
    existing = {
        str(t.get("name")).casefold() for t in _global_types(await ctx.jira.list_issue_types())
    }
    missing = [n for n in p.issue_types if n.casefold() not in existing]
    return CheckResult(
        notes=[f"Will create missing issue types: {', '.join(missing)}."] if missing else []
    )


async def configure_issue_types(ctx: HandlerContext, p: ConfigureIssueTypesParams) -> HandlerResult:
    project = await require_project(ctx, p.project_key)
    if project.get("style") == "next-gen":
        raise OperationUnsupportedError(
            f"{p.project_key} is team-managed: issue types are managed in Project settings → "
            "Issue types, not through issue type schemes."
        )
    types = _global_types(await ctx.jira.list_issue_types())
    ids: list[str] = []
    created: list[str] = []
    for name in p.issue_types:
        match = next((t for t in types if same_name(t.get("name"), name)), None)
        if match is None:
            level = -1 if name.casefold() in SUBTASK_NAMES else 0
            match = await ctx.jira.create_issue_type(name, f"{name} (created by AI agent)", level)
            created.append(name)
        ids.append(str(match["id"]))
    names = [n.casefold() for n in p.issue_types]
    wanted = (p.default_issue_type or "").casefold()
    default_id = ids[names.index(wanted)] if wanted in names else None
    project_id = str(project["id"])
    current = await ctx.jira.get_project_issue_type_scheme(project_id)
    if current and set(await ctx.jira.list_issue_type_scheme_items(str(current["id"]))) == set(ids):
        return HandlerResult(
            message=f"{p.project_key} already uses exactly these issue types.",
            outputs={"scheme_id": str(current["id"]), "issue_type_ids": ids},
            reused_existing=True,
        )
    scheme_id = await ctx.jira.create_issue_type_scheme(
        f"{p.project_key}: Issue Type Scheme ({ctx.idempotency_label})",
        f"Issue types for {p.project_key}",
        ids,
        default_id,
    )
    await ctx.jira.assign_issue_type_scheme(scheme_id, project_id)
    extra = f" Created new types: {', '.join(created)}." if created else ""
    return HandlerResult(
        message=f"Configured {p.project_key} with issue types {', '.join(p.issue_types)}.{extra}",
        outputs={"scheme_id": scheme_id, "issue_type_ids": ids, "project_id": project_id},
        resource=ResourceRef(
            type="jira_issue_type_scheme", id=scheme_id, title=f"{p.project_key} issue type scheme"
        ),
    )


async def create_custom_field(ctx: HandlerContext, p: CreateCustomFieldParams) -> HandlerResult:
    type_key, searcher = FIELD_TYPES[p.field_type]
    fields = await ctx.jira.list_fields()
    existing = next(
        (f for f in fields if f.get("custom") and same_name(f.get("name"), p.name)), None
    )
    if existing and (existing.get("schema") or {}).get("custom") not in (None, type_key):
        raise OperationConflictError(
            f"A custom field named '{p.name}' exists with a different type."
        )
    reused = existing is not None
    field = existing or await ctx.jira.create_custom_field(
        p.name, p.description, type_key, searcher
    )
    field_id = str(field["id"])
    invalidate_fields(ctx)
    added: list[str] = []
    if p.options and p.field_type in ("select", "multiselect"):
        contexts = await ctx.jira.list_field_contexts(field_id)
        if not contexts:
            raise OperationInputError(f"Field {field_id} has no context to hold options.")
        context_id = str(contexts[0]["id"])
        present = {
            str(o.get("value")).casefold()
            for o in await ctx.jira.list_field_options(field_id, context_id)
        }
        added = [o for o in p.options if o.casefold() not in present]
        if added:
            await ctx.jira.add_field_options(field_id, context_id, added)
    return HandlerResult(
        message=f"{'Reused' if reused else 'Created'} custom field '{p.name}' ({field_id})"
        + (f" with options {', '.join(added)}." if added else "."),
        outputs={"id": field_id, "name": p.name},
        resource=ResourceRef(type="jira_custom_field", id=field_id, title=p.name),
        reused_existing=reused and not added,
    )


async def _find_screen(ctx: HandlerContext, name_or_id: str) -> dict[str, Any] | None:
    for s in await ctx.jira.search_screens(name_or_id):
        if same_name(s.get("name"), name_or_id) or str(s.get("id")) == name_or_id:
            return s
    return None


async def _add_fields(
    ctx: HandlerContext, screen_id: str, field_refs: list[str], tab: str | None
) -> list[str]:
    tabs = await ctx.jira.get_screen_tabs(screen_id)
    target = next((t for t in tabs if tab and same_name(t.get("name"), tab)), None)
    if target is None:
        target = (
            tabs[0]
            if tabs and not tab
            else await ctx.jira.create_screen_tab(screen_id, tab or "Fields")
        )
    tab_id = str(target["id"])
    present = {str(f.get("id")) for f in await ctx.jira.get_tab_fields(screen_id, tab_id)}
    added: list[str] = []
    for ref in field_refs:
        field_id = await resolve_field_id(ctx, ref)
        if field_id not in present:
            await ctx.jira.add_field_to_tab(screen_id, tab_id, field_id)
            added.append(field_id)
    return added


async def create_screen(ctx: HandlerContext, p: CreateScreenParams) -> HandlerResult:
    screen = await _find_screen(ctx, p.name)
    reused = screen is not None
    screen = screen or await ctx.jira.create_screen(p.name, p.description)
    screen_id = str(screen["id"])
    added = await _add_fields(ctx, screen_id, p.fields, None) if p.fields else []
    return HandlerResult(
        message=f"{'Reused' if reused else 'Created'} screen '{p.name}', "
        f"added {len(added)} field(s).",
        outputs={"id": screen_id, "fields_added": added},
        resource=ResourceRef(type="jira_screen", id=screen_id, title=p.name),
        reused_existing=reused and not added,
    )


async def add_field_to_screen(ctx: HandlerContext, p: AddFieldToScreenParams) -> HandlerResult:
    screen = await _find_screen(ctx, p.screen)
    if screen is None:
        raise OperationInputError(f"Screen '{p.screen}' does not exist.")
    added = await _add_fields(ctx, str(screen["id"]), [p.field], p.tab)
    return HandlerResult(
        message=f"Field '{p.field}' {'added to' if added else 'already on'} "
        f"screen '{screen['name']}'.",
        outputs={"screen_id": str(screen["id"])},
        reused_existing=not added,
    )


async def create_field_configuration(
    ctx: HandlerContext, p: CreateFieldConfigurationParams
) -> HandlerResult:
    found = next(
        (
            c
            for c in await ctx.jira.search_field_configurations(p.name)
            if same_name(c.get("name"), p.name)
        ),
        None,
    )
    reused = found is not None
    config = found or await ctx.jira.create_field_configuration(p.name, p.description)
    config_id = str(config["id"])
    items: list[dict[str, Any]] = []
    for ref in p.required_fields:
        items.append({"id": await resolve_field_id(ctx, ref), "isRequired": True})
    for ref in p.hidden_fields:
        items.append({"id": await resolve_field_id(ctx, ref), "isHidden": True})
    if items:
        await ctx.jira.update_field_configuration_items(config_id, items)
    return HandlerResult(
        message=f"{'Updated' if reused else 'Created'} field configuration '{p.name}' "
        f"({len(p.required_fields)} required, {len(p.hidden_fields)} hidden).",
        outputs={"id": config_id},
        resource=ResourceRef(type="jira_field_configuration", id=config_id, title=p.name),
        reused_existing=reused and not items,
    )


PRIORITY_ICON_BASE = "/images/icons/priorities/"


def priority_icon(name: str) -> str:
    """Built-in icon (Jira requires iconUrl or avatarId) chosen from the priority's name."""
    n = name.casefold()
    for words, icon in (
        (("lowest", "p5", "trivial"), "lowest_new"),
        (("critical", "highest", "p1", "blocker", "urgent"), "highest_new"),
        (("high", "p2", "major"), "high_new"),
        (("low", "p4", "minor"), "low_new"),
    ):
        if any(w in n for w in words):
            return PRIORITY_ICON_BASE + icon
    return PRIORITY_ICON_BASE + "medium_new"


async def create_priority(ctx: HandlerContext, p: CreatePriorityParams) -> HandlerResult:
    found = next(
        (x for x in await ctx.jira.search_priorities(p.name) if same_name(x.get("name"), p.name)),
        None,
    )
    if found:
        return HandlerResult(
            message=f"Priority '{p.name}' already exists.",
            outputs={"id": str(found["id"])},
            reused_existing=True,
        )
    payload = {"name": p.name, "statusColor": p.color, "description": p.description}
    icon = priority_icon(p.name)
    try:
        created = await ctx.jira.create_priority({**payload, "iconUrl": f"{icon}.svg"})
    except AtlassianApiError as exc:
        if "icon" not in exc.message.casefold():
            raise
        created = await ctx.jira.create_priority({**payload, "iconUrl": f"{icon}.png"})
    return HandlerResult(
        message=f"Created priority '{p.name}'.",
        outputs={"id": str(created["id"])},
        resource=ResourceRef(type="jira_priority", id=str(created["id"]), title=p.name),
    )


async def find_global_status(ctx: HandlerContext, name: str) -> dict[str, Any] | None:
    for s in await ctx.jira.search_statuses(name):
        if (
            same_name(s.get("name"), name)
            and (s.get("scope") or {}).get("type", "GLOBAL") == "GLOBAL"
        ):
            return s
    return None


async def create_statuses(ctx: HandlerContext, p: CreateStatusesParams) -> HandlerResult:
    ids: dict[str, str] = {}
    to_create: list[dict[str, Any]] = []
    for s in p.statuses:
        found = await find_global_status(ctx, s.name)
        if found:
            ids[s.name] = str(found["id"])
        else:
            to_create.append({"name": s.name, "statusCategory": s.category, "description": ""})
    if to_create:
        for created in await ctx.jira.create_statuses({"type": "GLOBAL"}, to_create):
            ids[str(created["name"])] = str(created["id"])
    return HandlerResult(
        message=f"Statuses ready: {', '.join(ids)} ({len(to_create)} new).",
        outputs={"status_ids": ids},
        reused_existing=not to_create,
    )
