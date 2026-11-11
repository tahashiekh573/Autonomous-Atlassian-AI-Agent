"""Workflow schemes for projects with issues, and incremental workflow updates.

Endpoints and payload shapes follow the Jira Platform OpenAPI spec:
- POST /rest/api/3/workflowscheme/project/switch  (async task; status migrations per issue type)
- POST /rest/api/3/workflows (bulk get) and /workflows/update[/validation]
"""

import asyncio
import uuid
from typing import Any

from app.agents.handlers.base import HandlerContext, HandlerResult, free_name, same_name
from app.agents.handlers.jira_common import require_project, resolve_field_id
from app.agents.handlers.jira_config import find_global_status
from app.core.exceptions import OperationError, OperationInputError
from app.schemas.agents import ResourceRef
from app.schemas.operations.jira_ops import ConfigureWorkflowSchemeParams, UpdateWorkflowParams

TASK_POLL_SECONDS = 2.0
TASK_TIMEOUT_SECONDS = 180.0


# --- reading workflows ---------------------------------------------------------------------


async def workflow_status_info(ctx: HandlerContext, names: list[str]) -> dict[str, dict[str, Any]]:
    """name -> {"statuses": {status_id: category}, "initial": status_id, "order": [ids]}."""
    body = await ctx.jira.get_workflows_by_name(sorted(set(names)))
    by_ref = {str(s.get("statusReference") or s.get("id")): s for s in body.get("statuses") or []}
    info: dict[str, dict[str, Any]] = {}
    for wf in body.get("workflows") or []:
        order: list[str] = []
        statuses: dict[str, str] = {}
        for entry in wf.get("statuses") or []:
            status = by_ref.get(str(entry.get("statusReference")), {})
            status_id = str(status.get("id") or entry.get("statusReference"))
            statuses[status_id] = str(status.get("statusCategory") or "TODO")
            order.append(status_id)
        initial = next(
            (
                str(
                    by_ref.get(str(t.get("toStatusReference")), {}).get("id")
                    or t.get("toStatusReference")
                )
                for t in wf.get("transitions") or []
                if t.get("type") == "INITIAL"
            ),
            order[0] if order else "",
        )
        info[str(wf.get("name"))] = {"statuses": statuses, "initial": initial, "order": order}
    missing = set(names) - set(info)
    if missing:
        raise OperationInputError(f"Workflow(s) not found: {', '.join(sorted(missing))}.")
    return info


def migration_target(old_category: str, new: dict[str, Any]) -> str:
    """Pick the status in the new workflow that matches an old status's category."""
    if old_category == "TODO":
        return str(new["initial"])
    for status_id in new["order"]:
        if new["statuses"][status_id] == old_category:
            return str(status_id)
    return str(new["initial"])


# --- workflow scheme -------------------------------------------------------------------------


async def configure_workflow_scheme(
    ctx: HandlerContext, p: ConfigureWorkflowSchemeParams
) -> HandlerResult:
    project = await require_project(ctx, p.project_key)
    project_id = str(project["id"])
    types = {str(t["name"]).casefold(): str(t["id"]) for t in project.get("issueTypes") or []}
    wanted: dict[str, str] = {}
    for mapping in p.mappings:
        for name in mapping.issue_types:
            type_id = types.get(name.casefold())
            if type_id is None:
                raise OperationInputError(
                    f"Issue type '{name}' is not in {p.project_key} "
                    f"(available: {', '.join(str(t['name']) for t in project['issueTypes'])})."
                )
            wanted[type_id] = mapping.workflow_name

    current_ref = await ctx.jira.get_project_workflow_scheme(project_id)
    current = await ctx.jira.get_workflow_scheme(str(current_ref["id"])) if current_ref else {}
    old_mappings = {str(k): str(v) for k, v in (current.get("issueTypeMappings") or {}).items()}
    old_default = str(current.get("defaultWorkflow") or "jira")
    new_default = p.default_workflow or old_default
    new_mappings = {**old_mappings, **wanted}
    if current_ref and new_mappings == old_mappings and new_default == old_default:
        return HandlerResult(
            message=f"{p.project_key} already uses these workflows.",
            outputs={
                "scheme_id": str(current_ref["id"]),
                "previous_scheme_id": str(current_ref["id"]),
            },
            reused_existing=True,
        )

    base_name = f"{p.project_key}: {p.scheme_name or 'ITSM workflow scheme'}"
    existing = await ctx.jira.list_workflow_schemes()

    def same_setup(s: dict[str, Any]) -> bool:
        mappings = {str(k): str(v) for k, v in (s.get("issueTypeMappings") or {}).items()}
        return mappings == new_mappings and str(s.get("defaultWorkflow") or "jira") == new_default

    # Reuse a scheme with this name and identical mappings (e.g. a retried step); otherwise
    # create one under the first free plain name - no run tags in what users see.
    scheme = next(
        (
            s
            for s in existing
            if str(s.get("name") or "").casefold().startswith(base_name.casefold())
            and same_setup(s)
        ),
        None,
    ) or await ctx.jira.create_workflow_scheme(
        {
            "name": free_name(base_name, [str(s.get("name") or "") for s in existing]),
            "description": f"Workflows for {p.project_key}",
            "defaultWorkflow": new_default,
            "issueTypeMappings": new_mappings,
        }
    )
    scheme_id = str(scheme["id"])
    scheme_name = str(scheme.get("name") or base_name)

    previous = str(current_ref["id"]) if current_ref else None
    has_issues = await ctx.jira.approximate_count(f"project = {p.project_key}") > 0
    if not has_issues:
        await ctx.jira.assign_workflow_scheme(scheme_id, project_id)
        migrated = 0
    else:
        migrated = await _switch_with_migration(
            ctx,
            project_id,
            scheme_id,
            types.values(),
            old_mappings,
            old_default,
            new_mappings,
            new_default,
        )
    return HandlerResult(
        message=f"Applied workflow scheme '{scheme_name}' to {p.project_key} "
        f"({len(wanted)} issue type(s) remapped"
        + (f"; {migrated} status mapping(s) used to migrate existing issues" if has_issues else "")
        + f"). Previous scheme id {previous or 'none'} kept for rollback.",
        outputs={
            "scheme_id": scheme_id,
            "project_id": project_id,
            "previous_scheme_id": str(current_ref["id"]) if current_ref else None,
            "mappings": new_mappings,
        },
        resource=ResourceRef(type="jira_workflow_scheme", id=scheme_id, title=scheme_name),
    )


async def _switch_with_migration(
    ctx: HandlerContext,
    project_id: str,
    scheme_id: str,
    type_ids: Any,
    old_mappings: dict[str, str],
    old_default: str,
    new_mappings: dict[str, str],
    new_default: str,
) -> int:
    old_of = {t: old_mappings.get(t, old_default) for t in type_ids}
    new_of = {t: new_mappings.get(t, new_default) for t in type_ids}
    changed = [t for t in type_ids if old_of[t] != new_of[t]]
    info = await workflow_status_info(
        ctx, [old_of[t] for t in changed] + [new_of[t] for t in changed]
    )
    overrides: list[dict[str, Any]] = []
    for type_id in changed:
        old, new = info[old_of[type_id]], info[new_of[type_id]]
        mappings = [
            {"oldStatusId": status_id, "newStatusId": migration_target(category, new)}
            for status_id, category in old["statuses"].items()
            if status_id not in new["statuses"]
        ]
        if mappings:
            overrides.append({"issueTypeId": type_id, "statusMappings": mappings})
    body = await ctx.jira.switch_workflow_scheme(
        {
            "projectId": project_id,
            "targetSchemeId": scheme_id,
            "mappingsByIssueTypeOverride": overrides,
        }
    )
    body = body or {}
    location = str(body.get("location") or body.get("self") or "")
    task_id = str(body.get("taskId") or body.get("id") or location.rstrip("/").rsplit("/", 1)[-1])
    if task_id:
        await _wait_for_task(ctx, task_id)
    else:  # no task reference: confirm by reading the project's scheme instead
        await _wait_for_scheme(ctx, project_id, scheme_id)
    return sum(len(o["statusMappings"]) for o in overrides)


async def _wait_for_scheme(ctx: HandlerContext, project_id: str, scheme_id: str) -> None:
    waited = 0.0
    while waited < TASK_TIMEOUT_SECONDS:
        current = await ctx.jira.get_project_workflow_scheme(project_id)
        if current and str(current.get("id")) == scheme_id:
            return
        await asyncio.sleep(TASK_POLL_SECONDS)
        waited += TASK_POLL_SECONDS
    raise OperationError("Workflow scheme switch did not finish in time.")


async def _wait_for_task(ctx: HandlerContext, task_id: str) -> None:
    waited = 0.0
    while waited < TASK_TIMEOUT_SECONDS:
        task = await ctx.jira.get_task(task_id)
        status = str(task.get("status", "")).upper()
        if status == "COMPLETE":
            return
        if status in {"FAILED", "CANCELLED", "DEAD"}:
            raise OperationError(
                f"Workflow scheme switch {status.lower()}: {task.get('message') or task}"
            )
        await asyncio.sleep(TASK_POLL_SECONDS)
        waited += TASK_POLL_SECONDS
    raise OperationError(
        f"Workflow scheme switch still running after {TASK_TIMEOUT_SECONDS:.0f}s (task {task_id})."
    )


# --- workflow update -------------------------------------------------------------------------


async def update_workflow(ctx: HandlerContext, p: UpdateWorkflowParams) -> HandlerResult:
    body = await ctx.jira.get_workflows_by_name([p.workflow_name])
    workflow = next(
        (w for w in body.get("workflows") or [] if same_name(w.get("name"), p.workflow_name)), None
    )
    if workflow is None:
        raise OperationInputError(f"Workflow '{p.workflow_name}' not found.")
    all_statuses = {
        str(s.get("statusReference") or s.get("id")): s for s in body.get("statuses") or []
    }
    in_workflow = [str(s["statusReference"]) for s in workflow.get("statuses") or []]
    by_name = {str(all_statuses[r]["name"]).casefold(): r for r in in_workflow if r in all_statuses}

    status_entries = [
        {
            k: all_statuses[r][k]
            for k in ("id", "name", "statusCategory", "statusReference", "description")
            if k in all_statuses[r]
        }
        for r in in_workflow
        if r in all_statuses
    ]
    new_status_refs: list[str] = []
    for s in p.add_statuses:
        if s.name.casefold() in by_name:
            continue
        existing = await find_global_status(ctx, s.name)
        ref = str(existing["id"]) if existing else str(uuid.uuid4())
        entry: dict[str, Any] = {
            "name": s.name,
            "statusCategory": s.category,
            "statusReference": ref,
        }
        if existing:
            entry["id"] = str(existing["id"])
        status_entries.append(entry)
        by_name[s.name.casefold()] = ref
        new_status_refs.append(ref)

    transitions = list(workflow.get("transitions") or [])
    existing_names = {str(t.get("name")).casefold() for t in transitions}
    next_id = (
        max((int(t["id"]) for t in transitions if str(t.get("id", "")).isdigit()), default=1) + 10
    )
    added: list[str] = []
    for t in p.add_transitions:
        if t.name.casefold() in existing_names:
            continue
        refs = [by_name.get(n.casefold()) for n in [t.to_status, *t.from_statuses]]
        if None in refs:
            raise OperationInputError(
                f"Transition '{t.name}' uses a status that is not in the workflow "
                f"(have: {', '.join(sorted(by_name))})."
            )
        transitions.append(
            {
                "id": str(next_id),
                "name": t.name,
                "description": "",
                "type": "DIRECTED" if t.from_statuses else "GLOBAL",
                "toStatusReference": by_name[t.to_status.casefold()],
                "links": [{"fromStatusReference": by_name[f.casefold()]} for f in t.from_statuses],
                "actions": t.post_functions,
                "validators": t.validators,
                "triggers": [],
                "properties": {},
                **(
                    {"conditions": {"operation": "ALL", "conditions": t.conditions}}
                    if t.conditions
                    else {}
                ),
            }
        )
        next_id += 10
        added.append(t.name)
    approvals_set = await _apply_approvals(ctx, p, workflow, transitions, by_name)
    if not added and not new_status_refs and not approvals_set:
        return HandlerResult(
            message=f"'{p.workflow_name}' already has these transitions.",
            outputs={"id": str(workflow["id"])},
            reused_existing=True,
        )

    payload = {
        "statuses": status_entries,
        "workflows": [
            {
                "id": workflow["id"],
                "version": workflow["version"],
                "description": workflow.get("description") or "",
                "statuses": [
                    *workflow["statuses"],
                    *({"statusReference": r, "properties": {}} for r in new_status_refs),
                ],
                "transitions": transitions,
            }
        ],
    }
    errors = [
        str(e.get("message") or e)
        for e in await ctx.jira.validate_workflow_update(payload)
        if str(e.get("level", "ERROR")).upper() == "ERROR"
    ]
    if errors:
        raise OperationInputError(f"Jira rejected the workflow update: {'; '.join(errors)}")
    await ctx.jira.update_workflows(payload)
    return HandlerResult(
        message=f"Updated workflow '{p.workflow_name}': added "
        f"{len(new_status_refs)} status(es), transitions {', '.join(added) or '-'}"
        + (f", approval steps on {', '.join(approvals_set)}" if approvals_set else "")
        + ".",
        outputs={"id": str(workflow["id"]), "added_transitions": added},
        resource=ResourceRef(type="jira_workflow", id=str(workflow["id"]), title=p.workflow_name),
    )


async def _apply_approvals(
    ctx: HandlerContext,
    p: UpdateWorkflowParams,
    workflow: dict[str, Any],
    transitions: list[dict[str, Any]],
    by_name: dict[str, str],
) -> list[str]:
    """Set `approvalConfiguration` on workflow statuses (documented WorkflowReferenceStatus)."""
    applied: list[str] = []
    transition_ids = {str(t.get("name")).casefold(): str(t.get("id")) for t in transitions}
    for approval in p.approvals:
        ref = by_name.get(approval.status.casefold())
        if ref is None:
            raise OperationInputError(f"Status '{approval.status}' is not in '{p.workflow_name}'.")
        missing = [
            n
            for n in (approval.approve_transition, approval.reject_transition)
            if n.casefold() not in transition_ids
        ]
        if missing:
            raise OperationInputError(f"Transition(s) not in workflow: {', '.join(missing)}.")
        field_id = await resolve_field_id(ctx, approval.approvers_field)
        config = {
            "active": "true",
            "conditionType": "number",
            "conditionValue": str(approval.required_approvals),
            "exclude": [],
            "fieldId": field_id,
            "transitionApproved": transition_ids[approval.approve_transition.casefold()],
            "transitionRejected": transition_ids[approval.reject_transition.casefold()],
        }
        for entry in workflow["statuses"]:
            if (
                str(entry.get("statusReference")) == ref
                and entry.get("approvalConfiguration") != config
            ):
                entry["approvalConfiguration"] = config
                applied.append(approval.status)
    return applied
