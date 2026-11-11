"""Jira Service Management handlers."""

from typing import Any

from app.agents.handlers.base import CheckResult, HandlerContext, HandlerResult, same_name
from app.agents.handlers.jira_common import project_issue_type_id, require_project
from app.agents.handlers.jira_projects import check_project_key, create_project_with
from app.clients.jsm.types import ServiceDesk
from app.core.exceptions import OperationInputError
from app.schemas.agents import ResourceRef
from app.schemas.operations.jsm_ops import (
    AddCustomersParams,
    AddParticipantsParams,
    CreateOrganizationParams,
    CreateRequestParams,
    CreateRequestTypeParams,
    CreateServiceProjectParams,
    ServiceDeskRef,
)
from app.schemas.operations.spec import NoParams

SERVICE_TEMPLATES = {
    "itsm": "com.atlassian.servicedesk:itil-v2-service-desk-project",
    "general": "com.atlassian.servicedesk:simplified-general-service-desk-it",
    "customer_service": "com.atlassian.servicedesk:simplified-external-service-desk",
    "hr": "com.atlassian.servicedesk:simplified-hr-service-desk",
    "facilities": "com.atlassian.servicedesk:simplified-facilities-service-desk",
}


async def resolve_service_desk(ctx: HandlerContext, ref: str) -> ServiceDesk:
    desks = await ctx.jsm.list_service_desks()
    for desk in desks:
        if desk.id == ref or desk.project_key.upper() == ref.upper():
            return desk
    raise OperationInputError(f"No service desk found for '{ref}'.")


async def list_service_desks(ctx: HandlerContext, _: NoParams) -> HandlerResult:
    desks = await ctx.jsm.list_service_desks()
    return HandlerResult(
        message=f"{len(desks)} service project(s).",
        outputs={"service_desks": [d.model_dump() for d in desks]},
    )


async def check_create_service_project(
    ctx: HandlerContext, p: CreateServiceProjectParams
) -> CheckResult:
    return (await check_project_key(ctx, p.key, p.name))[1]


async def create_service_project(
    ctx: HandlerContext, p: CreateServiceProjectParams
) -> HandlerResult:
    result = await create_project_with(
        ctx,
        key=p.key,
        name=p.name,
        project_type="service_desk",
        template_key=p.template_key or SERVICE_TEMPLATES[p.template],
        description=p.description,
        lead_account_id=p.lead_account_id,
        resource_type="jsm_service_project",
    )
    desk = await ctx.jsm.find_service_desk_by_project(p.key)
    if desk is None:
        raise OperationInputError(f"Project {p.key} exists but is not a service project.")
    portal = f"{ctx.site_url}/servicedesk/customer/portal/{desk.id}"
    result.outputs.update(
        service_desk_id=desk.id,
        portal_url=portal,
        url=f"{ctx.site_url}/jira/servicedesk/projects/{p.key}",
    )
    if result.resource:
        result.resource.url = result.outputs["url"]
    result.message += f" Service desk {desk.id}; portal {portal}."
    return result


async def create_request_type(ctx: HandlerContext, p: CreateRequestTypeParams) -> HandlerResult:
    desk = await resolve_service_desk(ctx, p.service_desk)
    for rt in await ctx.jsm.list_request_types(desk.id):
        if same_name(rt.get("name"), p.name):
            return HandlerResult(
                message=f"Request type '{p.name}' already exists.",
                outputs={"id": str(rt["id"]), "service_desk_id": desk.id},
                reused_existing=True,
            )
    project = await require_project(ctx, desk.project_key)
    issue_type_id = project_issue_type_id(project, p.issue_type)
    rt = await ctx.jsm.create_request_type(
        desk.id,
        {
            "issueTypeId": issue_type_id,
            "name": p.name,
            "description": p.description,
            "helpText": p.help_text,
        },
    )
    return HandlerResult(
        message=f"Created request type '{p.name}' in {desk.project_key}.",
        outputs={"id": str(rt["id"]), "service_desk_id": desk.id},
        resource=ResourceRef(type="jsm_request_type", id=str(rt["id"]), title=p.name),
    )


async def list_request_types(ctx: HandlerContext, p: ServiceDeskRef) -> HandlerResult:
    desk = await resolve_service_desk(ctx, p.service_desk)
    types = await ctx.jsm.list_request_types(desk.id)
    return HandlerResult(
        message=f"{len(types)} request type(s) in {desk.project_key}.",
        outputs={"request_types": [{"id": t["id"], "name": t.get("name")} for t in types]},
    )


async def list_queues(ctx: HandlerContext, p: ServiceDeskRef) -> HandlerResult:
    desk = await resolve_service_desk(ctx, p.service_desk)
    queues = await ctx.jsm.list_queues(desk.id)
    return HandlerResult(
        message=f"{len(queues)} queue(s) in {desk.project_key}.",
        outputs={
            "queues": [
                {
                    "id": q["id"],
                    "name": q.get("name"),
                    "jql": q.get("jql"),
                    "issue_count": q.get("issueCount"),
                }
                for q in queues
            ]
        },
    )


async def _find_org(ctx: HandlerContext, name_or_id: str) -> dict[str, Any] | None:
    for org in await ctx.jsm.list_organizations():
        if str(org.get("id")) == name_or_id or same_name(org.get("name"), name_or_id):
            return org
    return None


async def create_organization(ctx: HandlerContext, p: CreateOrganizationParams) -> HandlerResult:
    org = await _find_org(ctx, p.name)
    reused = org is not None
    org = org or await ctx.jsm.create_organization(p.name)
    org_id = str(org["id"])
    if p.service_desk:
        desk = await resolve_service_desk(ctx, p.service_desk)
        await ctx.jsm.add_organization_to_service_desk(desk.id, org_id)
    return HandlerResult(
        message=f"{'Reused' if reused else 'Created'} organization '{p.name}'"
        + (f" and added it to {p.service_desk}." if p.service_desk else "."),
        outputs={"id": org_id},
        resource=ResourceRef(type="jsm_organization", id=org_id, title=p.name),
        reused_existing=reused and not p.service_desk,
    )


async def _account_for_email(ctx: HandlerContext, email: str) -> tuple[str, bool]:
    users = [u for u in await ctx.jira.find_users(email) if u.get("accountId")]
    exact = [u for u in users if same_name(u.get("emailAddress"), email)]
    # Emails are often hidden by profile privacy; a single hit for an exact-email query is safe.
    match = exact[0] if exact else (users[0] if len(users) == 1 else None)
    if match is not None:
        return str(match["accountId"]), False
    created = await ctx.jsm.create_customer(email, email.split("@")[0])
    return str(created["accountId"]), True


async def add_customers(ctx: HandlerContext, p: AddCustomersParams) -> HandlerResult:
    desk = await resolve_service_desk(ctx, p.service_desk)
    ids: list[str] = []
    created = 0
    for email in p.emails:
        account_id, is_new = await _account_for_email(ctx, email)
        ids.append(account_id)
        created += int(is_new)
    await ctx.jsm.add_customers(desk.id, ids)
    if p.organization:
        org = await _find_org(ctx, p.organization)
        if org is None:
            raise OperationInputError(f"Organization '{p.organization}' does not exist.")
        await ctx.jsm.add_users_to_organization(str(org["id"]), ids)
    return HandlerResult(
        message=f"Granted {len(ids)} customer(s) access to {desk.project_key} "
        f"({created} new account(s)).",
        outputs={"account_ids": ids, "service_desk_id": desk.id},
    )


async def create_request(ctx: HandlerContext, p: CreateRequestParams) -> HandlerResult:
    label = ctx.idempotency_label
    desk = await resolve_service_desk(ctx, p.service_desk)
    existing = await ctx.jira.search(f'labels = "{label}"', fields=["summary"], max_results=1)
    if existing:
        key = str(existing[0]["key"])
        return HandlerResult(
            message=f"Request {key} already raised.", outputs={"key": key}, reused_existing=True
        )
    request_type_id = p.request_type
    if not request_type_id.isdigit():
        match = next(
            (
                rt
                for rt in await ctx.jsm.list_request_types(desk.id)
                if same_name(rt.get("name"), p.request_type)
            ),
            None,
        )
        if match is None:
            raise OperationInputError(
                f"Request type '{p.request_type}' not found in {desk.project_key}."
            )
        request_type_id = str(match["id"])
    payload: dict[str, Any] = {
        "serviceDeskId": desk.id,
        "requestTypeId": request_type_id,
        "requestFieldValues": {"summary": p.summary},
    }
    # Request types created via the API often only have Summary on their portal form; sending a
    # field the form lacks makes Jira reject the whole request.
    accepted = await ctx.jsm.get_request_type_fields(desk.id, request_type_id)
    description_as_comment = bool(p.description) and "description" not in accepted
    if p.description and "description" in accepted:
        payload["requestFieldValues"]["description"] = p.description
    if p.raise_on_behalf_of:
        payload["raiseOnBehalfOf"] = p.raise_on_behalf_of
    created = await ctx.jsm.create_request(payload)
    key = str(created["issueKey"])
    await ctx.jira.update_issue(key, {"labels": [label]})  # makes retries idempotent
    if description_as_comment:
        await ctx.jira.add_comment(key, p.description)
    url = f"{ctx.site_url}/browse/{key}"
    return HandlerResult(
        message=f"Raised request {key}: {p.summary}",
        outputs={"key": key, "id": str(created.get("issueId")), "url": url},
        resource=ResourceRef(
            type="jsm_request", id=str(created.get("issueId")), key=key, title=p.summary, url=url
        ),
    )


async def add_participants(ctx: HandlerContext, p: AddParticipantsParams) -> HandlerResult:
    await ctx.jsm.add_participants(p.issue_key, p.account_ids)
    return HandlerResult(
        message=f"Added {len(p.account_ids)} participant(s) to {p.issue_key}.",
        outputs={"key": p.issue_key},
    )
