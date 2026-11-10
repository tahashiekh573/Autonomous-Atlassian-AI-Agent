"""Jira project handlers."""

from typing import Any

from app.agents.handlers.base import CheckResult, HandlerContext, HandlerResult, same_name
from app.core.exceptions import OperationConflictError, OperationInputError
from app.schemas.agents import ResourceRef
from app.schemas.operations.jira_ops import (
    CreateProjectParams,
    ListProjectsParams,
    UpdateProjectParams,
)
from app.schemas.operations.spec import NoParams

SOFTWARE_TEMPLATES = {
    "scrum": "com.pyxis.greenhopper.jira:gh-simplified-scrum-classic",
    "kanban": "com.pyxis.greenhopper.jira:gh-simplified-kanban-classic",
    "basic": "com.pyxis.greenhopper.jira:gh-simplified-basic",
    "business": "com.atlassian.jira-core-project-templates:jira-core-simplified-project-management",
}


async def whoami(ctx: HandlerContext, _: NoParams) -> HandlerResult:
    me = await ctx.jira.get_myself()
    return HandlerResult(
        message=f"Connected as {me.display_name}.",
        outputs={"account_id": me.account_id, "display_name": me.display_name},
    )


async def list_projects(ctx: HandlerContext, p: ListProjectsParams) -> HandlerResult:
    projects = await ctx.jira.list_projects(max_items=p.max_results)
    return HandlerResult(
        message=f"{len(projects)} project(s).",
        outputs={
            "projects": [
                {"id": x.id, "key": x.key, "name": x.name, "type": x.project_type_key}
                for x in projects
            ]
        },
    )


async def check_project_key(
    ctx: HandlerContext, key: str, name: str
) -> tuple[dict[str, Any] | None, CheckResult]:
    existing = await ctx.jira.find_project(key)
    if existing is None:
        return None, CheckResult(notes=[f"Project key {key} is free."])
    if same_name(existing.get("name"), name):
        return existing, CheckResult(notes=[f"Project {key} already exists; it will be reused."])
    return existing, CheckResult(
        conflict=True,
        notes=[f"Project key {key} is already used by '{existing.get('name')}'."],
    )


async def check_create_project(ctx: HandlerContext, p: CreateProjectParams) -> CheckResult:
    return (await check_project_key(ctx, p.key, p.name))[1]


async def create_project_with(
    ctx: HandlerContext,
    *,
    key: str,
    name: str,
    project_type: str,
    template_key: str,
    description: str,
    lead_account_id: str | None,
    resource_type: str,
) -> HandlerResult:
    existing, check = await check_project_key(ctx, key, name)
    if check.conflict:
        raise OperationConflictError(check.notes[0])
    if existing is not None:
        return _project_result(ctx, existing, resource_type, reused=True)
    lead = lead_account_id or ctx.account_id
    if not lead:
        raise OperationInputError("A project lead account id is required.")
    created = await ctx.jira.create_project(
        {
            "key": key,
            "name": name,
            "projectTypeKey": project_type,
            "projectTemplateKey": template_key,
            "description": description,
            "leadAccountId": lead,
            "assigneeType": "PROJECT_LEAD",
        }
    )
    project = {"id": created.get("id"), "key": created.get("key", key), "name": name}
    return _project_result(ctx, project, resource_type, reused=False)


def _project_result(
    ctx: HandlerContext, project: dict[str, Any], resource_type: str, *, reused: bool
) -> HandlerResult:
    key = str(project["key"])
    url = f"{ctx.site_url}/browse/{key}"
    verb = "Reused existing" if reused else "Created"
    return HandlerResult(
        message=f"{verb} project {key} ({project.get('name')}).",
        outputs={"id": str(project.get("id")), "key": key, "url": url},
        resource=ResourceRef(
            type=resource_type,
            id=str(project.get("id")),
            key=key,
            title=str(project.get("name")),
            url=url,
        ),
        reused_existing=reused,
    )


async def create_project(ctx: HandlerContext, p: CreateProjectParams) -> HandlerResult:
    project_type = "business" if p.template == "business" else "software"
    return await create_project_with(
        ctx,
        key=p.key,
        name=p.name,
        project_type=project_type,
        template_key=p.template_key or SOFTWARE_TEMPLATES[p.template],
        description=p.description,
        lead_account_id=p.lead_account_id,
        resource_type="jira_project",
    )


async def update_project(ctx: HandlerContext, p: UpdateProjectParams) -> HandlerResult:
    payload: dict[str, Any] = {}
    if p.name is not None:
        payload["name"] = p.name
    if p.description is not None:
        payload["description"] = p.description
    if p.lead_account_id is not None:
        payload["leadAccountId"] = p.lead_account_id
    if not payload:
        raise OperationInputError("Nothing to update.")
    await ctx.jira.update_project(p.project_key, payload)
    return HandlerResult(
        message=f"Updated project {p.project_key} ({', '.join(payload)}).",
        outputs={"key": p.project_key},
    )
