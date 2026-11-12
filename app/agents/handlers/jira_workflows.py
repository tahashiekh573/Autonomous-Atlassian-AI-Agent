"""Jira workflow handlers (bulk workflow create API, validated before creation)."""

import uuid
from typing import Any

from app.agents.handlers.base import (
    CheckResult,
    HandlerContext,
    HandlerResult,
    free_name,
    same_name,
)
from app.agents.handlers.jira_common import require_project
from app.agents.handlers.jira_config import find_global_status
from app.core.exceptions import OperationInputError
from app.schemas.agents import ResourceRef
from app.schemas.operations.jira_ops import AssignWorkflowParams, CreateWorkflowParams


async def _find_workflow(ctx: HandlerContext, name: str) -> dict[str, Any] | None:
    for wf in await ctx.jira.search_workflows(name):
        if same_name(wf.get("name"), name):
            return wf
    return None


async def build_workflow_payload(ctx: HandlerContext, p: CreateWorkflowParams) -> dict[str, Any]:
    names = {s.name.casefold() for s in p.statuses}
    referenced = (
        {p.initial_status.casefold()}
        | {t.to_status.casefold() for t in p.transitions}
        | {f.casefold() for t in p.transitions for f in t.from_statuses}
    )
    unknown = referenced - names
    if unknown:
        raise OperationInputError(
            f"Transitions reference undeclared statuses: {', '.join(sorted(unknown))}."
        )

    refs: dict[str, str] = {}
    statuses: list[dict[str, Any]] = []
    for s in p.statuses:
        ref = str(uuid.uuid4())
        refs[s.name.casefold()] = ref
        entry: dict[str, Any] = {
            "name": s.name,
            "statusCategory": s.category,
            "statusReference": ref,
        }
        existing = await find_global_status(ctx, s.name)
        if existing:
            entry["id"] = str(existing["id"])
        statuses.append(entry)

    transitions: list[dict[str, Any]] = [
        {
            "id": "1",
            "name": "Create",
            "type": "INITIAL",
            "toStatusReference": refs[p.initial_status.casefold()],
            "links": [],
        }
    ]
    for index, t in enumerate(p.transitions, start=1):
        transition: dict[str, Any] = {
            "id": str(index * 10 + 1),
            "name": t.name,
            "type": "DIRECTED" if t.from_statuses else "GLOBAL",
            "toStatusReference": refs[t.to_status.casefold()],
            "links": [{"fromStatusReference": refs[f.casefold()]} for f in t.from_statuses],
        }
        if t.conditions:
            transition["conditions"] = {"operation": "ALL", "conditions": t.conditions}
        if t.validators:
            transition["validators"] = t.validators
        if t.post_functions:
            transition["actions"] = t.post_functions
        transitions.append(transition)

    return {
        "scope": {"type": "GLOBAL"},
        "statuses": statuses,
        "workflows": [
            {
                "name": p.name,
                "description": p.description,
                "statuses": [
                    {"statusReference": s["statusReference"], "properties": {}} for s in statuses
                ],
                "transitions": transitions,
            }
        ],
    }


def _blocking(errors: list[dict[str, Any]]) -> list[str]:
    return [
        str(e.get("message") or e)
        for e in errors
        if str(e.get("level", "ERROR")).upper() == "ERROR"
    ]


async def check_create_workflow(ctx: HandlerContext, p: CreateWorkflowParams) -> CheckResult:
    if await _find_workflow(ctx, p.name):
        return CheckResult(notes=[f"Workflow '{p.name}' already exists; it will be reused."])
    try:
        payload = await build_workflow_payload(ctx, p)
    except OperationInputError as exc:
        return CheckResult(conflict=True, notes=[exc.message])
    errors = _blocking(await ctx.jira.validate_workflow_create(payload))
    if errors:
        return CheckResult(
            conflict=True, notes=[f"Jira rejected the workflow: {'; '.join(errors)}"]
        )
    return CheckResult(notes=["Jira validated the workflow definition."])


async def _same_definition(ctx: HandlerContext, name: str, p: CreateWorkflowParams) -> bool:
    """True when the existing workflow has exactly the requested statuses and transitions."""
    body = await ctx.jira.get_workflows_by_name([name])
    wf = next((w for w in body.get("workflows") or [] if same_name(w.get("name"), name)), None)
    if wf is None:
        return False
    by_ref = {str(s.get("statusReference") or s.get("id")): s for s in body.get("statuses") or []}
    statuses = {
        str(by_ref.get(str(s.get("statusReference")), {}).get("name", "")).casefold()
        for s in wf.get("statuses") or []
    }
    transitions = {str(t.get("name")).casefold() for t in wf.get("transitions") or []}
    return (
        statuses == {s.name.casefold() for s in p.statuses}
        and {t.name.casefold() for t in p.transitions} <= transitions
    )


async def create_workflow(ctx: HandlerContext, p: CreateWorkflowParams) -> HandlerResult:
    requested = p.name
    existing = await _find_workflow(ctx, p.name)
    if existing:
        if await _same_definition(ctx, p.name, p):
            return HandlerResult(
                message=f"Workflow '{p.name}' already exists with these statuses and transitions.",
                outputs={"name": p.name},
                reused_existing=True,
            )
        # Another workflow owns the name but has different statuses: never hand that one out
        # as "done" - create the requested definition under the next free name.
        taken = [str(w.get("name")) for w in await ctx.jira.search_workflows(p.name)]
        p = p.model_copy(update={"name": free_name(p.name, taken)})
        ctx.alias_workflow(requested, p.name)
    payload = await build_workflow_payload(ctx, p)
    errors = _blocking(await ctx.jira.validate_workflow_create(payload))
    if errors:
        raise OperationInputError(f"Jira rejected the workflow: {'; '.join(errors)}")
    body = await ctx.jira.create_workflows(payload)
    created = (body.get("workflows") or [{}])[0]
    workflow_id = str(created.get("id") or "")
    return HandlerResult(
        message=f"Created workflow '{p.name}' with {len(p.statuses)} statuses and "
        f"{len(p.transitions)} transitions"
        + (
            f" ('{requested}' already existed with different statuses)"
            if p.name != requested
            else ""
        )
        + ".",
        outputs={"id": workflow_id, "name": p.name},
        resource=ResourceRef(type="jira_workflow", id=workflow_id, title=p.name),
    )


async def assign_workflow(ctx: HandlerContext, p: AssignWorkflowParams) -> HandlerResult:
    project = await require_project(ctx, p.project_key)
    project_id = str(project["id"])
    p = p.model_copy(update={"workflow_name": ctx.workflow_name(p.workflow_name)})
    scheme_name = p.scheme_name or f"{p.project_key}: {p.workflow_name} scheme"
    mappings: dict[str, str] = {}
    for name in p.issue_types:
        match = next(
            (t for t in project.get("issueTypes") or [] if same_name(t.get("name"), name)), None
        )
        if match is None:
            raise OperationInputError(f"Issue type '{name}' is not in project {p.project_key}.")
        mappings[str(match["id"])] = p.workflow_name
    scheme = next(
        (
            s
            for s in await ctx.jira.list_workflow_schemes()
            if same_name(s.get("name"), scheme_name)
        ),
        None,
    )
    if scheme is None:
        payload: dict[str, Any] = {
            "name": scheme_name,
            "description": f"Workflows for {p.project_key}",
        }
        if mappings:
            payload["issueTypeMappings"] = mappings
        else:
            payload["defaultWorkflow"] = p.workflow_name
        scheme = await ctx.jira.create_workflow_scheme(payload)
    scheme_id = str(scheme["id"])
    current = await ctx.jira.get_project_workflow_scheme(project_id)
    if current and str(current.get("id")) == scheme_id:
        return HandlerResult(
            message=f"{p.project_key} already uses '{scheme_name}'.",
            outputs={"scheme_id": scheme_id},
            reused_existing=True,
        )
    await ctx.jira.assign_workflow_scheme(scheme_id, project_id)
    return HandlerResult(
        message=f"Assigned workflow scheme '{scheme_name}' ({p.workflow_name}) to {p.project_key}.",
        outputs={"scheme_id": scheme_id, "project_id": project_id},
        resource=ResourceRef(type="jira_workflow_scheme", id=scheme_id, title=scheme_name),
    )
