"""Jira filters, boards and sprints."""

from typing import Any

from app.agents.handlers.base import HandlerContext, HandlerResult, same_name
from app.agents.handlers.jira_common import require_project
from app.core.exceptions import OperationInputError
from app.schemas.agents import ResourceRef
from app.schemas.operations.jira_ops import (
    CreateBoardParams,
    CreateFilterParams,
    CreateSprintParams,
    MoveIssuesToBacklogParams,
    MoveIssuesToSprintParams,
    StartSprintParams,
)


def _sprint_date(day: str | None, end: bool = False) -> str | None:
    return f"{day}T{'17:00' if end else '09:00'}:00.000Z" if day else None


async def ensure_filter(
    ctx: HandlerContext, name: str, jql: str, description: str, share_project_key: str | None
) -> tuple[dict[str, Any], bool]:
    for f in await ctx.jira.search_filters(name):
        if same_name(f.get("name"), name):
            return f, True
    payload: dict[str, Any] = {"name": name, "jql": jql, "description": description}
    if share_project_key:
        project = await require_project(ctx, share_project_key)
        payload["sharePermissions"] = [{"type": "project", "project": {"id": str(project["id"])}}]
    return await ctx.jira.create_filter(payload), False


async def create_filter(ctx: HandlerContext, p: CreateFilterParams) -> HandlerResult:
    flt, reused = await ensure_filter(ctx, p.name, p.jql, p.description, p.share_with_project_key)
    filter_id = str(flt["id"])
    url = f"{ctx.site_url}/issues/?filter={filter_id}"
    return HandlerResult(
        message=f"{'Reused' if reused else 'Created'} filter '{p.name}'.",
        outputs={"id": filter_id, "url": url},
        resource=ResourceRef(type="jira_filter", id=filter_id, title=p.name, url=url),
        reused_existing=reused,
    )


async def create_board(ctx: HandlerContext, p: CreateBoardParams) -> HandlerResult:
    await require_project(ctx, p.project_key)
    for board in await ctx.jira.find_boards(p.project_key, p.name):
        if same_name(board.get("name"), p.name):
            return _board_result(ctx, board, None, reused=True)
    filter_id = p.filter_id
    if filter_id is None:
        jql = p.jql or f"project = {p.project_key} ORDER BY Rank ASC"
        flt, _ = await ensure_filter(
            ctx, f"Filter for {p.name}", jql, f"Board filter for {p.name}", p.project_key
        )
        filter_id = str(flt["id"])
    board = await ctx.jira.create_board(
        {
            "name": p.name,
            "type": p.board_type,
            "filterId": int(filter_id),
            "location": {"type": "project", "projectKeyOrId": p.project_key},
        }
    )
    return _board_result(ctx, board, filter_id, reused=False)


def _board_result(
    ctx: HandlerContext, board: dict[str, Any], filter_id: str | None, *, reused: bool
) -> HandlerResult:
    board_id = str(board["id"])
    url = f"{ctx.site_url}/secure/RapidBoard.jspa?rapidView={board_id}"
    return HandlerResult(
        message=f"{'Reused' if reused else 'Created'} {board.get('type', '')} board "
        f"'{board.get('name')}' ({board_id}).",
        outputs={"id": board_id, "filter_id": filter_id, "url": url},
        resource=ResourceRef(type="jira_board", id=board_id, title=str(board.get("name")), url=url),
        reused_existing=reused,
    )


async def create_sprint(ctx: HandlerContext, p: CreateSprintParams) -> HandlerResult:
    for sprint in await ctx.jira.list_sprints(p.board_id):
        if same_name(sprint.get("name"), p.name) and sprint.get("state") != "closed":
            return HandlerResult(
                message=f"Sprint '{p.name}' already exists.",
                outputs={"id": str(sprint["id"])},
                reused_existing=True,
            )
    payload: dict[str, Any] = {"name": p.name, "originBoardId": int(p.board_id), "goal": p.goal}
    if p.start_date:
        payload["startDate"] = _sprint_date(p.start_date)
    if p.end_date:
        payload["endDate"] = _sprint_date(p.end_date, end=True)
    sprint = await ctx.jira.create_sprint(payload)
    sprint_id = str(sprint["id"])
    return HandlerResult(
        message=f"Created sprint '{p.name}' ({sprint_id}).",
        outputs={"id": sprint_id},
        resource=ResourceRef(type="jira_sprint", id=sprint_id, title=p.name),
    )


async def start_sprint(ctx: HandlerContext, p: StartSprintParams) -> HandlerResult:
    sprint = await ctx.jira.get_sprint(p.sprint_id)
    if sprint.get("state") == "active":
        return HandlerResult(
            message=f"Sprint {p.sprint_id} is already active.",
            outputs={"id": p.sprint_id},
            reused_existing=True,
        )
    if sprint.get("state") == "closed":
        raise OperationInputError(f"Sprint {p.sprint_id} is closed and cannot be restarted.")
    await ctx.jira.update_sprint(
        p.sprint_id,
        {
            "state": "active",
            "startDate": _sprint_date(p.start_date),
            "endDate": _sprint_date(p.end_date, end=True),
        },
    )
    return HandlerResult(message=f"Started sprint {p.sprint_id}.", outputs={"id": p.sprint_id})


async def move_issues_to_sprint(ctx: HandlerContext, p: MoveIssuesToSprintParams) -> HandlerResult:
    await ctx.jira.move_issues_to_sprint(p.sprint_id, p.issue_keys)
    return HandlerResult(
        message=f"Moved {len(p.issue_keys)} issue(s) to sprint {p.sprint_id}.",
        outputs={"sprint_id": p.sprint_id, "issue_keys": p.issue_keys},
    )


async def move_issues_to_backlog(
    ctx: HandlerContext, p: MoveIssuesToBacklogParams
) -> HandlerResult:
    in_sprint = []
    for key in p.issue_keys:
        sprint = (await ctx.jira.get_agile_issue(key))["fields"].get("sprint")
        if sprint:
            in_sprint.append(key)
    if not in_sprint:
        return HandlerResult(
            message=f"All {len(p.issue_keys)} issue(s) are already in the backlog.",
            outputs={"issue_keys": p.issue_keys},
            reused_existing=True,
        )
    await ctx.jira.move_issues_to_backlog(in_sprint)
    return HandlerResult(
        message=f"Moved {len(in_sprint)} issue(s) from their sprint to the backlog.",
        outputs={"issue_keys": p.issue_keys},
    )
