"""Jira Service Management operations: parameters and catalog entries."""

from typing import Literal

from pydantic import Field

from app.schemas.operations.spec import (
    IssueKey,
    NoParams,
    OperationSpec,
    Params,
    ProjectKey,
    UnsupportedParams,
)

_JSM = ("jira", "jsm")


class CreateServiceProjectParams(Params):
    key: ProjectKey
    name: str = Field(min_length=2, max_length=80)
    template: Literal["itsm", "general", "customer_service", "hr", "facilities"] = "itsm"
    template_key: str | None = None
    description: str = ""
    lead_account_id: str | None = None


class ServiceDeskRef(Params):
    service_desk: str = Field(description="Service project key (e.g. ITSD) or service desk id")


class CreateRequestTypeParams(ServiceDeskRef):
    name: str
    issue_type: str = Field(description="e.g. Incident, Service request, Change, Problem")
    description: str = ""
    help_text: str = ""


class CreateOrganizationParams(Params):
    name: str
    service_desk: str | None = Field(default=None, description="Also add it to this desk")


class AddCustomersParams(ServiceDeskRef):
    emails: list[str] = Field(min_length=1, max_length=50)
    organization: str | None = Field(default=None, description="Organization name or id")


class CreateRequestParams(ServiceDeskRef):
    request_type: str = Field(description="Request type name or id")
    summary: str
    description: str = ""
    raise_on_behalf_of: str | None = Field(default=None, description="Customer email/accountId")


class AddParticipantsParams(Params):
    issue_key: IssueKey
    account_ids: list[str] = Field(min_length=1)


class SlaReportParams(Params):
    project_key: ProjectKey
    sla_names: list[str] = Field(
        default_factory=lambda: ["Time to first response", "Time to resolution"]
    )
    jql_filter: str | None = Field(default=None, description="Extra JQL, e.g. issuetype=Incident")


class RequestReportParams(Params):
    project_key: ProjectKey
    group_by: Literal["status", "priority", "assignee", "issuetype"] = "status"
    jql_filter: str | None = None
    days: int = Field(default=30, ge=1, le=365)


FormQuestionType = Literal[
    "short_text",
    "long_text",
    "rich_text",
    "email",
    "number",
    "date",
    "dropdown",
    "single_choice",
    "multi_choice",
    "attachment",
]


class FormQuestion(Params):
    label: str = Field(min_length=1, max_length=255)
    type: FormQuestionType = "short_text"
    description: str = ""
    required: bool = False
    choices: list[str] = Field(default_factory=list, description="For dropdown/choice types")
    jira_field: str | None = Field(
        default=None, description="Optional Jira field name or id to store the answer in"
    )


class CreateFormParams(ServiceDeskRef):
    name: str = Field(min_length=1, max_length=255)
    questions: list[FormQuestion] = Field(min_length=1, max_length=60)
    request_types: list[str] = Field(
        default_factory=list,
        description="Request type names or ids that show this form on the portal",
    )


def _unsupported(name: str, description: str, limitation: str, alternative: str) -> OperationSpec:
    return OperationSpec(
        name,
        "jsm",
        "modify",
        description,
        UnsupportedParams,
        requires_products=_JSM,
        supported=False,
        limitation=limitation,
        alternative=alternative,
    )


SPECS: list[OperationSpec] = [
    OperationSpec(
        "jsm.list_service_desks",
        "jsm",
        "read",
        "List service projects.",
        NoParams,
        requires_products=_JSM,
    ),
    OperationSpec(
        "jsm.create_service_project",
        "jsm",
        "create",
        "Create a JSM service project from a template (ITSM template includes "
        "incident, service request, problem and change workflows, queues and SLAs).",
        CreateServiceProjectParams,
        requires_products=_JSM,
        needs_jira_admin=True,
    ),
    OperationSpec(
        "jsm.create_request_type",
        "jsm",
        "create",
        "Create a portal request type backed by an issue type.",
        CreateRequestTypeParams,
        requires_products=_JSM,
    ),
    OperationSpec(
        "jsm.list_request_types",
        "jsm",
        "read",
        "List request types.",
        ServiceDeskRef,
        requires_products=_JSM,
    ),
    OperationSpec(
        "jsm.list_queues",
        "jsm",
        "read",
        "List queues with issue counts.",
        ServiceDeskRef,
        requires_products=_JSM,
    ),
    OperationSpec(
        "jsm.create_organization",
        "jsm",
        "create",
        "Create a customer organization (optionally add to a service desk).",
        CreateOrganizationParams,
        requires_products=_JSM,
    ),
    OperationSpec(
        "jsm.add_customers",
        "jsm",
        "security",
        "Grant portal access to customers (creates customer accounts when needed).",
        AddCustomersParams,
        requires_products=_JSM,
    ),
    OperationSpec(
        "jsm.create_request",
        "jsm",
        "create",
        "Raise a customer request / incident.",
        CreateRequestParams,
        requires_products=_JSM,
    ),
    OperationSpec(
        "jsm.add_participants",
        "jsm",
        "modify",
        "Add request participants.",
        AddParticipantsParams,
        requires_products=_JSM,
    ),
    OperationSpec(
        "jsm.sla_report",
        "jsm",
        "read",
        "Count breached / running / met SLAs per SLA metric.",
        SlaReportParams,
        requires_products=_JSM,
    ),
    OperationSpec(
        "jsm.request_report",
        "jsm",
        "read",
        "Request/incident volume grouped by status, priority, assignee or type.",
        RequestReportParams,
        requires_products=_JSM,
    ),
    _unsupported(
        "jsm.configure_sla",
        "Create or edit SLA metrics, goals, start/pause/stop conditions.",
        "JSM has no public API for SLA configuration.",
        "Project settings → SLAs. The ITSM template already ships 'Time to first "
        "response' and 'Time to resolution'; use jsm.sla_report to verify they run.",
    ),
    _unsupported(
        "jsm.configure_sla_calendar",
        "Create SLA calendars / working hours.",
        "No public API for SLA calendars.",
        "Project settings → SLAs → Calendars.",
    ),
    _unsupported(
        "jsm.create_queue",
        "Create or edit queues.",
        "Queues are read-only in the public API.",
        "Queues → Manage queues; jsm.list_queues verifies the result.",
    ),
    OperationSpec(
        "jsm.create_form",
        "jsm",
        "create",
        "Create a JSM form (questions: text, email, number, date, dropdown, single/multi "
        "choice, attachment; required flags; optional Jira field mapping) and show it on the "
        "portal for the given request types. Use this to build request forms.",
        CreateFormParams,
        requires_products=_JSM,
    ),
    _unsupported(
        "jsm.configure_request_form",
        "Configure the built-in request type field layout, visibility or conditional fields.",
        "The built-in request type field layout is not writable via the public API.",
        "Use jsm.create_form to build a form for the request type instead, or Project settings "
        "→ Request types → Request form.",
    ),
    _unsupported(
        "jsm.configure_approvals",
        "Configure approval steps in workflows.",
        "Approval configuration is not exposed via the public API.",
        "Workflow editor → status → Add approval.",
    ),
    _unsupported(
        "jsm.configure_portal",
        "Configure help center, portal groups or branding.",
        "Help center / portal configuration has no public API.",
        "Project settings → Portal settings / Request types → Portal groups.",
    ),
    _unsupported(
        "jsm.link_knowledge_base",
        "Connect a Confluence space as the knowledge base.",
        "Linking a knowledge base space is UI-only.",
        "Project settings → Knowledge base → Link space (the agent can create the "
        "space and articles with Confluence operations first).",
    ),
]
