"""Team-managed (next-gen) projects: every issue type owns a project-scoped workflow.

Company-managed tools (workflow schemes, issue type schemes) do not apply there; instead the issue
type's own workflow is rewritten through the bulk workflow API (scope PROJECT).

Jira's status migration for team-managed workflows rejects status removal through the API, so
statuses are never removed: an old status this issue type alone uses is *renamed* into a wanted
status (same category preferred) - issues in it simply carry the new name - and only genuinely
extra statuses are added. Old statuses that cannot be reused stay in the workflow and are reported.
"""

import re
import uuid
from typing import Any

from app.agents.handlers.base import CheckResult, HandlerContext, HandlerResult
from app.agents.handlers.jira_common import project_issue_type_id, require_project
from app.agents.handlers.jira_workflow_schemes import _wait_for_task
from app.core.exceptions import OperationInputError
from app.schemas.agents import ResourceRef
from app.schemas.operations.jira_ops import SetIssueTypeWorkflowParams

HELPER_PREFIX = "Move to "


async def _load(
    ctx: HandlerContext, p: SetIssueTypeWorkflowParams
) -> tuple[dict[str, Any], str, dict[str, Any], dict[str, Any]]:
    """(project, issue type id, workflow, bulk-get body)."""
    project = await require_project(ctx, p.project_key)
    if project.get("style") != "next-gen":
        raise OperationInputError(
            f"{p.project_key} is company-managed: use jira.create_workflow and "
            "jira.configure_workflow_scheme instead."
        )
    type_id = project_issue_type_id(project, p.issue_type)
    body = await ctx.jira.get_issue_type_workflow(str(project["id"]), type_id)
    workflows = body.get("workflows") or []
    if not workflows:
        raise OperationInputError(f"No workflow found for '{p.issue_type}' in {p.project_key}.")
    return project, type_id, workflows[0], body


def _status_index(
    workflow: dict[str, Any], body: dict[str, Any]
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """(statuses by reference, references used by this workflow, in workflow order)."""
    by_ref = {str(s.get("statusReference") or s.get("id")): s for s in body.get("statuses") or []}
    in_workflow = [str(s.get("statusReference")) for s in workflow.get("statuses") or []]
    return by_ref, in_workflow


def _current_shape(workflow: dict[str, Any], body: dict[str, Any]) -> tuple[set[str], set[str]]:
    by_ref, in_workflow = _status_index(workflow, body)
    names = {str(by_ref.get(r, {}).get("name", "")).casefold() for r in in_workflow}
    transitions = {
        str(t.get("name")).casefold()
        for t in workflow.get("transitions") or []
        if t.get("type") != "INITIAL"
    }
    return names, transitions


def _wanted_shape(p: SetIssueTypeWorkflowParams) -> tuple[set[str], set[str]]:
    return {s.name.casefold() for s in p.statuses}, {t.name.casefold() for t in p.transitions}


async def _shared_refs(
    ctx: HandlerContext, project: dict[str, Any], type_id: str, workflow_id: str
) -> set[str]:
    """Status references also used by the project's other issue-type workflows."""
    shared: set[str] = set()
    seen = {workflow_id}
    for t in project.get("issueTypes") or []:
        if str(t.get("id")) == type_id:
            continue
        body = await ctx.jira.get_issue_type_workflow(str(project["id"]), str(t["id"]))
        for wf in body.get("workflows") or []:
            if str(wf.get("id")) in seen:
                continue
            seen.add(str(wf.get("id")))
            shared.update(str(s.get("statusReference")) for s in wf.get("statuses") or [])
    return shared


_FILLER = {"a", "an", "the", "in", "to", "for", "of", "on", "under", "by", "is"}


def _words(name: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", name.casefold()) if w not in _FILLER}


def _transition(
    tid: int, name: str, to_ref: str, from_refs: list[str], **extra: Any
) -> dict[str, Any]:
    return {
        "id": str(tid),
        "name": name,
        "description": "",
        "type": "DIRECTED" if from_refs else "GLOBAL",
        "toStatusReference": to_ref,
        "links": [{"fromStatusReference": r} for r in from_refs],
        "actions": extra.get("actions") or [],
        "validators": extra.get("validators") or [],
        "triggers": [],
        "properties": {},
        **({"conditions": extra["conditions"]} if extra.get("conditions") else {}),
    }


def _build(
    p: SetIssueTypeWorkflowParams,
    workflow: dict[str, Any],
    body: dict[str, Any],
    shared: set[str],
) -> tuple[dict[str, Any], list[tuple[str, str]], list[str]]:
    """(update payload, [(old name, new name) renamed], [old status names left in place])."""
    by_ref, in_workflow = _status_index(workflow, body)
    own = {str(by_ref[r]["name"]).casefold(): r for r in in_workflow if r in by_ref}
    project_named = {str(s.get("name")).casefold(): s for s in body.get("statuses") or []}
    wanted = {s.name.casefold() for s in p.statuses}
    # old statuses free to be renamed: used only here and not wanted under their own name
    free = [
        r
        for r in in_workflow
        if r in by_ref and r not in shared and str(by_ref[r]["name"]).casefold() not in wanted
    ]

    entries: list[dict[str, Any]] = []
    refs: dict[str, str] = {}
    renamed: list[tuple[str, str]] = []
    for s in p.statuses:
        key = s.name.casefold()
        old = by_ref.get(own[key]) if key in own else None
        if old is None and key in project_named:  # the project already has this status
            old = project_named[key]
        if old is not None:
            ref = str(old.get("statusReference") or old["id"])
            entries.append(
                {
                    "id": str(old["id"]),
                    "name": old["name"],
                    "statusCategory": old.get("statusCategory") or s.category,
                    "statusReference": ref,
                }
            )
        else:
            # prefer a similarly named status ("Under review" -> "In Review"), then one of the
            # same category; never an unrelated one (e.g. Done must not become In Progress)
            similar = [r for r in free if _words(str(by_ref[r]["name"])) & _words(s.name)]
            same = [r for r in free if by_ref[r].get("statusCategory") == s.category]
            candidates = similar or same
            pick: str | None = candidates[0] if candidates else None
            if pick is not None:  # rename an old status in place - its issues follow
                free.remove(pick)
                ref = pick
                renamed.append((str(by_ref[pick]["name"]), s.name))
                entries.append(
                    {
                        "id": str(by_ref[pick]["id"]),
                        "name": s.name,
                        "statusCategory": s.category,
                        "statusReference": ref,
                    }
                )
            else:
                ref = str(uuid.uuid4())
                entries.append(
                    {"name": s.name, "statusCategory": s.category, "statusReference": ref}
                )
        refs[key] = ref

    leftover = [r for r in in_workflow if r in by_ref and r not in refs.values()]
    for r in leftover:  # statuses can't be removed via the API: keep them as they are
        entries.append(
            {
                "id": str(by_ref[r]["id"]),
                "name": by_ref[r]["name"],
                "statusCategory": by_ref[r].get("statusCategory") or "TODO",
                "statusReference": r,
            }
        )

    def ref_of(name: str) -> str:
        ref = refs.get(name.casefold())
        if ref is None:
            raise OperationInputError(
                f"Status '{name}' is not one of the workflow statuses "
                f"({', '.join(s.name for s in p.statuses)})."
            )
        return ref

    initial = ref_of(p.initial_status or p.statuses[0].name)
    transitions = [{**_transition(1, "Create", initial, []), "type": "INITIAL"}]
    tid = 11
    for t in p.transitions:
        conditions = {"operation": "ALL", "conditions": t.conditions} if t.conditions else None
        transitions.append(
            _transition(
                tid,
                t.name,
                ref_of(t.to_status),
                [ref_of(f) for f in t.from_statuses],
                actions=t.post_functions,
                validators=t.validators,
                conditions=conditions,
            )
        )
        tid += 10
    global_to = {tr["toStatusReference"] for tr in transitions if tr["type"] == "GLOBAL"}
    # any-to-any when asked; and if old statuses remain, a way out of them into the new flow
    extra = [s.name for s in p.statuses] if (p.allow_any_to_any or leftover) else []
    for name in extra:
        ref = ref_of(name)
        if ref in global_to:
            continue
        label = name if p.allow_any_to_any else f"{HELPER_PREFIX}{name}"
        transitions.append(_transition(tid, label, ref, []))
        global_to.add(ref)
        tid += 10

    layout = {
        str(s.get("statusReference")): s.get("layout")
        for s in workflow.get("statuses") or []
        if s.get("layout")
    }
    order = [*refs.values(), *leftover]
    payload = {
        "statuses": entries,
        "workflows": [
            {
                "id": workflow["id"],
                "version": workflow["version"],
                "description": p.workflow_label or workflow.get("description") or "",
                "statuses": [
                    {
                        "statusReference": ref,
                        "properties": {},
                        "layout": layout.get(ref) or {"x": 180.0 + 220.0 * i, "y": 110.0},
                    }
                    for i, ref in enumerate(order)
                ],
                "transitions": transitions,
            }
        ],
    }
    return payload, renamed, [str(by_ref[r]["name"]) for r in leftover]


async def check_set_issue_type_workflow(
    ctx: HandlerContext, p: SetIssueTypeWorkflowParams
) -> CheckResult:
    project = await ctx.jira.find_project(p.project_key)
    if project is None:
        return CheckResult(notes=[f"Project {p.project_key} must exist first."])
    if project.get("style") != "next-gen":
        return CheckResult(
            conflict=True,
            notes=[f"{p.project_key} is company-managed; use workflow schemes instead."],
        )
    names = [str(t.get("name")) for t in project.get("issueTypes") or []]
    if not any(n.casefold() == p.issue_type.casefold() for n in names):
        return CheckResult(
            conflict=True,
            notes=[
                f"Issue type '{p.issue_type}' is not in {p.project_key} (has: {', '.join(names)})."
            ],
        )
    return CheckResult(notes=[f"Will set the workflow of '{p.issue_type}' in {p.project_key}."])


async def set_issue_type_workflow(
    ctx: HandlerContext, p: SetIssueTypeWorkflowParams
) -> HandlerResult:
    project, type_id, workflow, body = await _load(ctx, p)
    wf_id = str(workflow["id"])
    have_statuses, have_transitions = _current_shape(workflow, body)
    want_statuses, want_transitions = _wanted_shape(p)
    if want_statuses <= have_statuses and want_transitions <= have_transitions:
        return HandlerResult(
            message=f"'{p.issue_type}' in {p.project_key} already uses this workflow.",
            outputs={"workflow_id": wf_id, "issue_type_id": type_id},
            reused_existing=True,
        )

    shared = await _shared_refs(ctx, project, type_id, wf_id)
    payload, renamed, leftover = _build(p, workflow, body, shared)
    errors = [
        str(e.get("message") or e)
        for e in await ctx.jira.validate_workflow_update(payload)
        if str(e.get("level", "ERROR")).upper() == "ERROR"
    ]
    if errors:
        raise OperationInputError(f"Jira rejected the workflow: {'; '.join(errors)}")
    result = await ctx.jira.update_workflows(payload)
    task_id = (result or {}).get("taskId")
    if task_id:
        await _wait_for_task(ctx, str(task_id))

    notes: list[str] = []
    if renamed:
        notes.append("renamed " + ", ".join(f"{a} → {b}" for a, b in renamed))
    if leftover:
        notes.append(
            f"kept old status(es) {', '.join(leftover)} (Jira does not allow removing statuses "
            "through the API; remove them in the workflow editor if unused)"
        )
    return HandlerResult(
        message=f"Set the workflow of '{p.issue_type}' in {p.project_key}: "
        f"{', '.join(s.name for s in p.statuses)} with {len(p.transitions)} named transitions"
        + (f"; {'; '.join(notes)}" if notes else "")
        + ".",
        outputs={
            "workflow_id": wf_id,
            "issue_type_id": type_id,
            "project_id": str(project["id"]),
            "statuses": [s.name for s in p.statuses],
            "renamed": [f"{a} -> {b}" for a, b in renamed],
            "kept_old_statuses": leftover,
        },
        resource=ResourceRef(
            type="jira_workflow",
            id=wf_id,
            title=p.workflow_label or f"{p.project_key} {p.issue_type} workflow",
        ),
    )


async def live_shape(
    ctx: HandlerContext, p: SetIssueTypeWorkflowParams
) -> tuple[set[str], set[str]]:
    """Status and transition names (casefolded) the issue type's workflow has right now."""
    _, _, workflow, body = await _load(ctx, p)
    return _current_shape(workflow, body)
