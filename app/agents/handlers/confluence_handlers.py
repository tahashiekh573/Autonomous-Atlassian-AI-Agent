"""Confluence handlers: spaces, pages, labels, permissions."""

import html
from typing import Any

from app.agents.handlers.base import CheckResult, HandlerContext, HandlerResult, same_name
from app.agents.handlers.storage_format import (
    children_macro,
    is_well_formed,
    normalise_entities,
    text_to_storage,
)
from app.core.exceptions import OperationConflictError, OperationInputError
from app.schemas.agents import ResourceRef
from app.schemas.operations.confluence_ops import (
    AddLabelsParams,
    CreateIndexPageParams,
    CreatePageParams,
    CreateSpaceParams,
    DeletePageParams,
    SetSpacePermissionParams,
    UpdatePageParams,
    UpdateSpaceParams,
)
from app.schemas.operations.spec import NoParams

PERMISSION_OPERATIONS = {
    "read": ("read", "space"),
    "create_page": ("create", "page"),
    "create_blogpost": ("create", "blogpost"),
    "comment": ("create", "comment"),
    "administer": ("administer", "space"),
}


def page_url(ctx: HandlerContext, page: dict[str, Any]) -> str:
    webui = (page.get("_links") or {}).get("webui")
    return f"{ctx.site_url}/wiki{webui}" if webui else f"{ctx.site_url}/wiki/pages/{page.get('id')}"


async def require_space(ctx: HandlerContext, key: str) -> dict[str, Any]:
    space = await ctx.confluence.get_space_by_key(key)
    if space is None:
        raise OperationInputError(f"Confluence space '{key}' does not exist.")
    return space


async def list_spaces(ctx: HandlerContext, _: NoParams) -> HandlerResult:
    spaces = await ctx.confluence.list_spaces(max_items=250)
    return HandlerResult(
        message=f"{len(spaces)} space(s).", outputs={"spaces": [s.model_dump() for s in spaces]}
    )


async def check_create_space(ctx: HandlerContext, p: CreateSpaceParams) -> CheckResult:
    space = await ctx.confluence.get_space_by_key(p.key)
    if space is None:
        return CheckResult(notes=[f"Space key {p.key} is free."])
    if same_name(space.get("name"), p.name):
        return CheckResult(notes=[f"Space {p.key} already exists; it will be reused."])
    return CheckResult(
        conflict=True, notes=[f"Space key {p.key} is used by '{space.get('name')}'."]
    )


async def create_space(ctx: HandlerContext, p: CreateSpaceParams) -> HandlerResult:
    space = await ctx.confluence.get_space_by_key(p.key)
    reused = space is not None
    if space and not same_name(space.get("name"), p.name):
        raise OperationConflictError(f"Space key {p.key} is used by '{space.get('name')}'.")
    if space is None:
        await ctx.confluence.create_space(p.key, p.name, p.description)
        space = await require_space(ctx, p.key)
    url = f"{ctx.site_url}/wiki/spaces/{p.key}"
    return HandlerResult(
        message=f"{'Reused' if reused else 'Created'} space {p.key} ({p.name}).",
        outputs={
            "id": str(space["id"]),
            "key": p.key,
            "homepage_id": str(space.get("homepageId") or ""),
            "url": url,
        },
        resource=ResourceRef(
            type="confluence_space", id=str(space["id"]), key=p.key, title=p.name, url=url
        ),
        reused_existing=reused,
    )


async def update_space(ctx: HandlerContext, p: UpdateSpaceParams) -> HandlerResult:
    payload: dict[str, Any] = {}
    if p.name is not None:
        payload["name"] = p.name
    if p.description is not None:
        payload["description"] = {"plain": {"value": p.description, "representation": "plain"}}
    if not payload:
        raise OperationInputError("Nothing to update.")
    await ctx.confluence.update_space(p.space_key, payload)
    return HandlerResult(message=f"Updated space {p.space_key}.", outputs={"key": p.space_key})


async def _body(ctx: HandlerContext, kind: str, title: str, brief: str, existing: str = "") -> str:
    if ctx.content_writer is None:
        return text_to_storage(brief or title)
    body = await ctx.content_writer.write(
        page_kind=kind, title=title, brief=brief, existing=existing
    )
    body = normalise_entities(body)
    return body if is_well_formed(body) else text_to_storage(brief or title)


def _checked(body: str) -> str:
    body = normalise_entities(body)
    if not is_well_formed(body):
        raise OperationInputError("body_storage is not well-formed Confluence storage XHTML.")
    return body


async def _parent_id(
    ctx: HandlerContext, space: dict[str, Any], page_id: str | None, title: str | None
) -> str | None:
    if page_id:
        return page_id
    if title:
        parent = await ctx.confluence.find_page(str(space["id"]), title)
        if parent is None:
            raise OperationInputError(
                f"Parent page '{title}' not found in space {space.get('key')}."
            )
        return str(parent["id"])
    homepage = space.get("homepageId")
    return str(homepage) if homepage else None


async def _create_page(
    ctx: HandlerContext,
    space_key: str,
    title: str,
    body_fn: Any,
    parent_page_id: str | None,
    parent_title: str | None,
    labels: list[str],
    resource_type: str,
) -> HandlerResult:
    space = await require_space(ctx, space_key)
    existing = await ctx.confluence.find_page(str(space["id"]), title)
    if existing:
        return _page_result(ctx, existing, space_key, resource_type, reused=True)
    parent_id = await _parent_id(ctx, space, parent_page_id, parent_title)
    page = await ctx.confluence.create_page(str(space["id"]), title, await body_fn(), parent_id)
    if labels:
        await ctx.confluence.add_labels(str(page["id"]), labels)
    result = _page_result(ctx, page, space_key, resource_type, reused=False)
    result.outputs["parent_id"] = parent_id
    return result


def _page_result(
    ctx: HandlerContext, page: dict[str, Any], space_key: str, rtype: str, *, reused: bool
) -> HandlerResult:
    page_id = str(page["id"])
    url = page_url(ctx, page)
    return HandlerResult(
        message=f"{'Reused' if reused else 'Created'} page '{page.get('title')}' in {space_key}.",
        outputs={"id": page_id, "title": page.get("title"), "url": url, "space_key": space_key},
        resource=ResourceRef(type=rtype, id=page_id, title=str(page.get("title")), url=url),
        reused_existing=reused,
    )


async def create_page(ctx: HandlerContext, p: CreatePageParams) -> HandlerResult:
    async def body() -> str:
        if p.body_storage:
            return _checked(p.body_storage)
        return await _body(ctx, p.page_kind, p.title, p.brief)

    return await _create_page(
        ctx,
        p.space_key,
        p.title,
        body,
        p.parent_page_id,
        p.parent_title,
        p.labels,
        "confluence_page",
    )


async def create_index_page(ctx: HandlerContext, p: CreateIndexPageParams) -> HandlerResult:
    async def body() -> str:
        intro = f"<p>{html.escape(p.introduction)}</p>" if p.introduction else ""
        return f"{intro}<h2>Contents</h2>{children_macro()}"

    return await _create_page(
        ctx, p.space_key, p.title, body, p.parent_page_id, None, ["index"], "confluence_page"
    )


async def update_page(ctx: HandlerContext, p: UpdatePageParams) -> HandlerResult:
    page = await ctx.confluence.get_page(p.page_id)
    current = ((page.get("body") or {}).get("storage") or {}).get("value", "")
    title = p.title or str(page["title"])
    if p.body_storage:
        new_body = _checked(p.body_storage)
    elif p.brief:
        new_body = await _body(ctx, "general", title, p.brief, existing=current)
    else:
        new_body = current
    if p.append_storage:
        new_body += _checked(p.append_storage)
    version = int((page.get("version") or {}).get("number", 1)) + 1
    if new_body != current or title != page["title"]:
        await ctx.confluence.update_page(p.page_id, title, new_body, version, p.version_message)
    if p.labels:
        await ctx.confluence.add_labels(p.page_id, p.labels)
    return HandlerResult(
        message=f"Updated page '{title}' (version {version}).",
        outputs={"id": p.page_id, "version": version, "url": page_url(ctx, page)},
    )


async def add_labels(ctx: HandlerContext, p: AddLabelsParams) -> HandlerResult:
    await ctx.confluence.add_labels(p.page_id, p.labels)
    return HandlerResult(
        message=f"Labelled page {p.page_id}: {', '.join(p.labels)}.", outputs={"id": p.page_id}
    )


async def set_space_permission(ctx: HandlerContext, p: SetSpacePermissionParams) -> HandlerResult:
    key, target = PERMISSION_OPERATIONS[p.operation]
    await ctx.confluence.add_space_permission(
        p.space_key,
        {
            "subject": {"type": p.subject_type, "identifier": p.subject},
            "operation": {"key": key, "target": target},
        },
    )
    return HandlerResult(
        message=f"Granted {p.subject_type} {p.subject} '{p.operation}' on space {p.space_key}.",
        outputs={"space_key": p.space_key},
    )


async def check_delete_page(ctx: HandlerContext, p: DeletePageParams) -> CheckResult:
    if not await ctx.confluence.page_exists(p.page_id):
        return CheckResult(conflict=True, notes=[f"Page {p.page_id} does not exist."])
    children = await ctx.confluence.list_children(p.page_id)
    note = f"Page {p.page_id} will move to the trash"
    return CheckResult(
        notes=[note + (f"; it has {len(children)} child page(s)." if children else ".")]
    )


async def delete_page(ctx: HandlerContext, p: DeletePageParams) -> HandlerResult:
    await ctx.confluence.delete_page(p.page_id)
    return HandlerResult(message=f"Moved page {p.page_id} to the trash.", outputs={"id": p.page_id})
