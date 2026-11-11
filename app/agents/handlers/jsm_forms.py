"""JSM Forms: build a form design and publish it on the portal for request types."""

import uuid
from typing import Any

from app.agents.handlers.base import HandlerContext, HandlerResult, same_name
from app.agents.handlers.jira_common import resolve_field_id
from app.agents.handlers.jsm_handlers import resolve_service_desk
from app.core.exceptions import OperationInputError
from app.schemas.agents import ResourceRef
from app.schemas.operations.jsm_ops import CreateFormParams, FormQuestion

# Question type codes as stored by Jira Forms (seen in forms read back from a live site).
QUESTION_CODES: dict[str, str] = {
    "short_text": "ts",
    "long_text": "tl",
    "rich_text": "rt",
    "email": "te",
    "number": "no",
    "date": "da",
    "dropdown": "cd",
    "single_choice": "cs",
    "multi_choice": "cm",
    "attachment": "at",
}
CHOICE_TYPES = {"dropdown", "single_choice", "multi_choice"}


async def _question(ctx: HandlerContext, q: FormQuestion) -> dict[str, Any]:
    if q.type in CHOICE_TYPES and not q.choices:
        raise OperationInputError(f"Form question '{q.label}' ({q.type}) needs choices.")
    question: dict[str, Any] = {
        "label": q.label,
        "type": QUESTION_CODES[q.type],
        "description": q.description,
        "questionKey": "",
        "validation": {"rq": q.required},
        "choices": [
            {"id": str(i), "label": label, "other": False}
            for i, label in enumerate(q.choices, start=1)
        ]
        if q.type in CHOICE_TYPES
        else [],
    }
    if q.jira_field:
        question["jiraField"] = await resolve_field_id(ctx, q.jira_field)
    return question


def _layout(question_ids: list[str]) -> list[dict[str, Any]]:
    return [
        {
            "version": 1,
            "type": "doc",
            "content": [
                {
                    "type": "extension",
                    "attrs": {
                        "extensionKey": "question",
                        "extensionType": "com.thinktilt.proforma",
                        "parameters": {"id": int(qid)},
                        "text": "",
                        "layout": "default",
                        "localId": str(uuid.uuid4()),
                    },
                }
                for qid in question_ids
            ],
        }
    ]


async def build_form_design(ctx: HandlerContext, p: CreateFormParams) -> dict[str, Any]:
    questions = {str(i): await _question(ctx, q) for i, q in enumerate(p.questions, start=1)}
    return {
        "settings": {
            "name": p.name,
            "submit": {"lock": False, "pdf": False},
            "language": "en",
            "primaryLocale": "en-US",
            "translatedLocale": "en-US",
        },
        "questions": questions,
        "layout": _layout(list(questions)),
        "conditions": {},
        "sections": {},
    }


async def create_form(ctx: HandlerContext, p: CreateFormParams) -> HandlerResult:
    desk = await resolve_service_desk(ctx, p.service_desk)
    cloud_id = await ctx.jira.get_cloud_id()
    request_type_ids: list[int] = []
    if p.request_types:
        available = await ctx.jsm.list_request_types(desk.id)
        for ref in p.request_types:
            match = next(
                (rt for rt in available if str(rt["id"]) == ref or same_name(rt.get("name"), ref)),
                None,
            )
            if match is None:
                names = ", ".join(str(rt.get("name")) for rt in available)
                raise OperationInputError(
                    f"Request type '{ref}' not found in {desk.project_key} (available: {names})."
                )
            request_type_ids.append(int(match["id"]))
    for existing in await ctx.forms.list_forms(cloud_id, desk.project_key):
        if same_name(existing.get("name"), p.name):
            return _result(
                ctx,
                desk.project_key,
                str(existing["id"]),
                p,
                request_type_ids,
                cloud_id,
                reused=True,
            )
    publish = (
        {
            "portal": {
                "portalRequestTypeIds": request_type_ids,
                "submitOnCreate": True,
                "validateOnCreate": True,
            }
        }
        if request_type_ids
        else None
    )
    body = await ctx.forms.create_form(
        cloud_id, desk.project_key, await build_form_design(ctx, p), publish
    )
    form_id = str(body.get("id") or (body.get("formTemplate") or {}).get("id") or "")
    return _result(ctx, desk.project_key, form_id, p, request_type_ids, cloud_id, reused=False)


def _result(
    ctx: HandlerContext,
    project_key: str,
    form_id: str,
    p: CreateFormParams,
    request_type_ids: list[int],
    cloud_id: str,
    *,
    reused: bool,
) -> HandlerResult:
    url = f"{ctx.site_url}/jira/servicedesk/projects/{project_key}/settings/forms"
    shown = f", shown on {len(request_type_ids)} request type(s)" if request_type_ids else ""
    return HandlerResult(
        message=f"{'Reused existing' if reused else 'Created'} form '{p.name}' in {project_key} "
        f"with {len(p.questions)} question(s){shown}.",
        outputs={
            "id": form_id,
            "project_key": project_key,
            "cloud_id": cloud_id,
            "request_type_ids": request_type_ids,
            "url": url,
        },
        resource=ResourceRef(type="jsm_form", id=form_id, title=p.name, url=url),
        reused_existing=reused,
    )
