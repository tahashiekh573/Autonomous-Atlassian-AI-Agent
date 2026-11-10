"""Jira Automation rules (Automation REST API).

Component shapes mirror rules read back from a live site (GET /rest/v1/rule/{uuid}), which is
the only authoritative source for the per-component ``value`` formats.

If the API rejects the rule, the rule JSON is returned in the error details so an admin can
import it via Project settings → Automation → Import rules; the step is reported as failed,
never as completed.
"""

from typing import Any

from app.agents.handlers.base import HandlerContext, HandlerResult, same_name
from app.agents.handlers.jira_common import require_project
from app.core.exceptions import (
    AtlassianError,
    AtlassianUnsupportedError,
    OperationError,
    OperationInputError,
    OperationUnsupportedError,
)
from app.schemas.agents import ResourceRef
from app.schemas.operations.jira_ops import AutomationActionDef, CreateAutomationRuleParams

_TRIGGERS = {
    "issue_created": ("jira.issue.event.trigger:created", "jira:issue_created", "issue_created"),
    "issue_updated": ("jira.issue.event.trigger:updated", "jira:issue_updated", "issue_updated"),
    "issue_transitioned": (
        "jira.issue.event.trigger:transitioned",
        "jira:issue_updated",
        "issue_generic",
    ),
}


def _component(kind: str, type_: str, schema_version: int, value: Any) -> dict[str, Any]:
    return {
        "component": kind,
        "schemaVersion": schema_version,
        "type": type_,
        "value": value,
        "conditions": [],
        "children": [],
    }


def _action(a: AutomationActionDef) -> dict[str, Any]:
    if a.type == "assign":
        return _component(
            "ACTION",
            "jira.issue.assign",
            5,
            {
                "assignType": "SPECIFY_USER",
                "assignee": {"type": "ID", "value": a.value},
                "excludedUsers": [],
                "userList": [],
            },
        )
    if a.type == "transition":
        return _component(
            "ACTION",
            "jira.issue.transition",
            11,
            {
                "operations": [],
                "advancedFields": None,
                "sendNotifications": True,
                "destinationStatus": {"type": "NAME", "value": a.value},
                "transitionMatch": None,
            },
        )
    if a.type == "comment":
        return _component(
            "ACTION",
            "jira.issue.comment",
            1,
            {
                "comment": a.value,
                "publicComment": True,
                "addCommentOnce": False,
                "sendNotifications": True,
            },
        )
    if a.type == "set_priority":
        return _component(
            "ACTION",
            "jira.issue.edit",
            12,
            {
                "operations": [
                    {
                        "field": {"type": "ID", "value": "priority"},
                        "fieldType": "priority",
                        "type": "SET",
                        "value": {"type": "NAME", "value": a.value},
                    }
                ],
                "advancedFields": "",
                "sendNotifications": True,
            },
        )
    return _component(
        "ACTION",
        "jira.issue.outgoing.email",
        1,
        {
            "to": [{"type": "SMART", "value": a.email_to or "{{reporter.emailAddress}}"}],
            "subject": "{{issue.key}}: {{issue.summary}}",
            "body": a.value,
            "mimeType": "text/html",
        },
    )


def build_rule(
    p: CreateAutomationRuleParams, cloud_id: str, project_id: str, actor: str | None
) -> dict[str, Any]:
    ari = f"ari:cloud:jira:{cloud_id}:project/{project_id}"
    trigger_type, event_key, issue_event = _TRIGGERS[p.trigger]
    trigger_value: dict[str, Any] = {
        "eventKey": event_key,
        "issueEvent": issue_event,
        "eventFilters": [ari],
    }
    if p.trigger == "issue_transitioned" and p.trigger_to_status:
        trigger_value.update(
            fromStatus=[], toStatus=[{"type": "NAME", "value": p.trigger_to_status}]
        )
    components: list[dict[str, Any]] = []
    if p.jql_condition:
        components.append(_component("CONDITION", "jira.jql.condition", -1, p.jql_condition))
    components.extend(_action(a) for a in p.actions)
    rule: dict[str, Any] = {
        "name": p.name,
        "state": "ENABLED" if p.enabled else "DISABLED",
        "description": "Created by Atlassian AI Agent",
        "canOtherRuleTrigger": False,
        "notifyOnError": "FIRSTERROR",
        # Required: without it Jira answers 400 "request body could not be parsed".
        "writeAccessType": "OWNER_ONLY",
        "labels": [],
        "collaborators": [],
        "trigger": _component("TRIGGER", trigger_type, 1, trigger_value),
        "components": components,
        "ruleScopeARIs": [ari],
    }
    if actor:
        rule["authorAccountId"] = actor
        rule["actor"] = {"type": "ACCOUNT_ID", "actor": actor}
    return {"rule": rule}


async def create_automation_rule(
    ctx: HandlerContext, p: CreateAutomationRuleParams
) -> HandlerResult:
    for action in p.actions:
        if action.type == "assign" and "{{" in action.value:
            raise OperationInputError(
                "Automation 'assign' needs a literal Atlassian accountId, not a smart value "
                f"({action.value})."
            )
    project = await require_project(ctx, p.project_key)
    cloud_id = await ctx.jira.get_cloud_id()
    for existing in await ctx.jira.list_automation_rules(cloud_id):
        if same_name(existing.get("name"), p.name):
            return _result(ctx, p, str(existing.get("uuid")), cloud_id, reused=True)
    rule = build_rule(p, cloud_id, str(project["id"]), ctx.account_id)
    try:
        body = await ctx.jira.create_automation_rule(cloud_id, rule)
    except AtlassianUnsupportedError as exc:
        raise OperationUnsupportedError(
            f"{exc.message} Import the rule JSON from the run details via "
            "Project settings → Automation → Import rules.",
            details={"rule_json": rule, "upstream_code": exc.code},
        ) from exc
    except AtlassianError as exc:
        raise OperationError(
            f"Jira rejected the automation rule: {exc.message}. The generated rule JSON is in "
            "the run details.",
            details={"rule_json": rule, "upstream_code": exc.code},
        ) from exc
    rule_id = str(body.get("ruleUuid") or body.get("uuid") or body.get("id") or "")
    return _result(ctx, p, rule_id, cloud_id, reused=False)


def _result(
    ctx: HandlerContext, p: CreateAutomationRuleParams, rule_id: str, cloud_id: str, *, reused: bool
) -> HandlerResult:
    return HandlerResult(
        message=f"{'Reused existing' if reused else 'Created'} automation rule '{p.name}' "
        f"in {p.project_key}.",
        outputs={"rule_id": rule_id, "cloud_id": cloud_id},
        resource=ResourceRef(
            type="jira_automation_rule",
            id=rule_id,
            title=p.name,
            url=f"{ctx.site_url}/jira/settings/automation#/rule/{rule_id}",
        ),
        reused_existing=reused,
    )
