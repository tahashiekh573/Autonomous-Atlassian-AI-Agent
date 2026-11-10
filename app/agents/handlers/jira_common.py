"""Lookups shared by Jira-family handlers (cached per run)."""

from typing import Any

from app.agents.handlers.base import HandlerContext, same_name
from app.core.exceptions import OperationInputError


async def fields_by_name(ctx: HandlerContext) -> dict[str, dict[str, Any]]:
    if "jira_fields" not in ctx.cache:
        fields = await ctx.jira.list_fields()
        index: dict[str, dict[str, Any]] = {}
        for f in fields:
            index[str(f["id"]).casefold()] = f
            index.setdefault(str(f.get("name", "")).casefold(), f)
        ctx.cache["jira_fields"] = index
    result: dict[str, dict[str, Any]] = ctx.cache["jira_fields"]
    return result


async def resolve_field_id(ctx: HandlerContext, name_or_id: str) -> str:
    field = (await fields_by_name(ctx)).get(name_or_id.strip().casefold())
    if field is None:
        raise OperationInputError(f"Jira field '{name_or_id}' does not exist.")
    return str(field["id"])


def invalidate_fields(ctx: HandlerContext) -> None:
    ctx.cache.pop("jira_fields", None)


async def require_project(ctx: HandlerContext, key: str) -> dict[str, Any]:
    project = await ctx.jira.find_project(key)
    if project is None:
        raise OperationInputError(f"Jira project '{key}' does not exist.")
    return project


def project_issue_type_id(project: dict[str, Any], name: str) -> str:
    types = project.get("issueTypes") or []
    for t in types:
        if same_name(t.get("name"), name):
            return str(t["id"])
    for t in types:  # JSM types are often "[System] Incident"
        if name.casefold() in str(t.get("name", "")).casefold():
            return str(t["id"])
    available = ", ".join(str(t.get("name")) for t in types)
    raise OperationInputError(
        f"Issue type '{name}' is not available in project {project.get('key')} "
        f"(available: {available})."
    )


def browse_url(ctx: HandlerContext, key: str) -> str:
    return f"{ctx.site_url}/browse/{key}"
