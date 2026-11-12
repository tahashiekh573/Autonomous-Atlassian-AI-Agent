"""Jira Software operations: parameters and catalog entries."""

from typing import Any, Literal

from pydantic import Field

from app.schemas.operations.spec import (
    IsoDate,
    IssueKey,
    NoParams,
    OperationSpec,
    Params,
    ProjectKey,
    UnsupportedParams,
)

StatusCategory = Literal["TODO", "IN_PROGRESS", "DONE"]


class ListProjectsParams(Params):
    max_results: int = Field(default=200, ge=1, le=1000)


class CreateProjectParams(Params):
    key: ProjectKey
    name: str = Field(min_length=2, max_length=80)
    template: Literal["scrum", "kanban", "basic", "business"] = "scrum"
    template_key: str | None = Field(default=None, description="Raw Jira template key override")
    description: str = ""
    lead_account_id: str | None = Field(default=None, description="Defaults to the connected user")


class UpdateProjectParams(Params):
    project_key: ProjectKey
    name: str | None = None
    description: str | None = None
    lead_account_id: str | None = None


class CreateIssueTypeParams(Params):
    name: str = Field(min_length=1, max_length=60)
    description: str = ""
    level: Literal["standard", "subtask"] = "standard"


class ConfigureIssueTypesParams(Params):
    project_key: ProjectKey
    issue_types: list[str] = Field(min_length=1, description="Names, e.g. Epic, Story, Bug, Task")
    default_issue_type: str | None = None


class CreateCustomFieldParams(Params):
    name: str = Field(min_length=1, max_length=255)
    field_type: Literal[
        "text",
        "textarea",
        "number",
        "date",
        "datetime",
        "select",
        "multiselect",
        "user",
        "labels",
        "url",
    ]
    description: str = ""
    options: list[str] = Field(default_factory=list, description="For select/multiselect")


class CreateScreenParams(Params):
    name: str
    description: str = ""
    fields: list[str] = Field(default_factory=list, description="Field names or ids to add")


class AddFieldToScreenParams(Params):
    screen: str = Field(description="Screen name or id")
    field: str = Field(description="Field name or id")
    tab: str | None = Field(default=None, description="Tab name; defaults to the first tab")


class CreateFieldConfigurationParams(Params):
    name: str
    description: str = ""
    required_fields: list[str] = Field(default_factory=list)
    hidden_fields: list[str] = Field(default_factory=list)


class CreatePriorityParams(Params):
    name: str
    color: str = Field(default="#FF5630", pattern=r"^#[0-9A-Fa-f]{6}$")
    description: str = ""


class StatusDef(Params):
    name: str
    category: StatusCategory


class CreateStatusesParams(Params):
    statuses: list[StatusDef] = Field(min_length=1)


class TransitionDef(Params):
    name: str
    from_statuses: list[str] = Field(
        default_factory=list, description="Empty = global transition (from any status)"
    )
    to_status: str
    conditions: list[dict[str, Any]] = Field(
        default_factory=list, description="Raw Jira rule objects {ruleKey, parameters}"
    )
    validators: list[dict[str, Any]] = Field(default_factory=list)
    post_functions: list[dict[str, Any]] = Field(default_factory=list)


class CreateWorkflowParams(Params):
    name: str
    description: str = ""
    statuses: list[StatusDef] = Field(min_length=1)
    initial_status: str
    transitions: list[TransitionDef] = Field(default_factory=list)


class AssignWorkflowParams(Params):
    project_key: ProjectKey
    workflow_name: str
    issue_types: list[str] = Field(
        default_factory=list, description="Empty = default workflow for all issue types"
    )
    scheme_name: str | None = None


class WorkflowMappingDef(Params):
    workflow_name: str
    issue_types: list[str] = Field(min_length=1, description="Issue type names in the project")


class ConfigureWorkflowSchemeParams(Params):
    project_key: ProjectKey
    mappings: list[WorkflowMappingDef] = Field(min_length=1)
    default_workflow: str | None = Field(
        default=None, description="Workflow for unmapped issue types (default: keep current)"
    )
    scheme_name: str | None = None


class ApprovalDef(Params):
    status: str = Field(description="Status that waits for approval, e.g. Approval Pending")
    approve_transition: str = Field(description="Transition name run when approved")
    reject_transition: str = Field(description="Transition name run when declined")
    approvers_field: str = Field(
        default="Approvers", description="Approvers / Approver groups field"
    )
    required_approvals: int = Field(default=1, ge=1, le=20)


class UpdateWorkflowParams(Params):
    workflow_name: str
    add_statuses: list[StatusDef] = Field(default_factory=list)
    add_transitions: list[TransitionDef] = Field(default_factory=list)
    approvals: list[ApprovalDef] = Field(
        default_factory=list, description="JSM approval steps on workflow statuses"
    )


class SetIssueTypeWorkflowParams(Params):
    """Team-managed projects: each issue type owns a workflow; replace statuses + transitions."""

    project_key: ProjectKey
    issue_type: str = Field(description="Existing issue type in the project")
    statuses: list[StatusDef] = Field(min_length=1, description="All statuses, in order")
    initial_status: str | None = Field(
        default=None, description="Status new issues start in (default: first status)"
    )
    transitions: list[TransitionDef] = Field(
        default_factory=list, description="Named transitions incl. reopen; from_statuses=[] = any"
    )
    allow_any_to_any: bool = Field(
        default=False, description="Also allow moving from any status to any status"
    )
    workflow_label: str | None = Field(
        default=None, description="Shown as the workflow description (names are fixed by Jira)"
    )


class CreateIssueParams(Params):
    project_key: ProjectKey
    issue_type: str = Field(description="e.g. Epic, Story, Task, Bug, Sub-task")
    summary: str = Field(min_length=1, max_length=255)
    description: str = ""
    parent_key: IssueKey | None = Field(default=None, description="Epic or parent issue")
    labels: list[str] = Field(default_factory=list)
    priority: str | None = None
    assignee_account_id: str | None = None
    start_date: IsoDate | None = None
    due_date: IsoDate | None = None
    fields: dict[str, Any] = Field(default_factory=dict, description="Extra fields by name or id")


class UpdateIssueParams(Params):
    issue_key: IssueKey
    summary: str | None = None
    description: str | None = None
    labels: list[str] | None = None
    priority: str | None = None
    parent_key: IssueKey | None = None
    start_date: IsoDate | None = None
    due_date: IsoDate | None = None
    fields: dict[str, Any] = Field(default_factory=dict)


class TransitionIssueParams(Params):
    issue_key: IssueKey
    to_status: str


class TransitionCheck(Params):
    from_status: str = Field(description="Status the transition starts from ('' = from any status)")
    to_status: str


class VerifyWorkflowTransitionsParams(Params):
    issue_key: IssueKey
    transitions: list[TransitionCheck] = Field(
        default_factory=list,
        description="Transitions to prove; empty = every transition in the issue's workflow",
    )


class LinkIssuesParams(Params):
    from_issue: IssueKey
    to_issue: IssueKey
    link_type: str = Field(
        default="Blocks", description="Link type name: Blocks, Relates, Duplicate, Cloners"
    )


class DeleteIssueParams(Params):
    issue_key: IssueKey


class SearchIssuesParams(Params):
    jql: str
    max_results: int = Field(default=50, ge=1, le=500)


class CreateFilterParams(Params):
    name: str
    jql: str
    description: str = ""
    share_with_project_key: ProjectKey | None = None


class CreateBoardParams(Params):
    name: str
    board_type: Literal["scrum", "kanban"]
    project_key: ProjectKey
    jql: str | None = Field(default=None, description="Defaults to all issues in the project")
    filter_id: str | None = None


class CreateSprintParams(Params):
    board_id: str
    name: str
    goal: str = ""
    start_date: IsoDate | None = None
    end_date: IsoDate | None = None


class StartSprintParams(Params):
    sprint_id: str
    start_date: IsoDate
    end_date: IsoDate


class MoveIssuesToSprintParams(Params):
    sprint_id: str
    issue_keys: list[IssueKey] = Field(min_length=1, max_length=50)


class MoveIssuesToBacklogParams(Params):
    issue_keys: list[IssueKey] = Field(min_length=1, max_length=50)


class GadgetDef(Params):
    type: Literal[
        "filter_results",
        "pie_chart",
        "created_vs_resolved",
        "two_dimensional",
        "assigned_to_me",
        "average_age",
        "resolution_time",
        "heat_map",
        "activity_stream",
        "work_item_statistics",
        "workload_pie",
        "time_to_first_response",
        "time_in_status",
        "recently_created",
        "time_since",
        "issues_in_progress",
        "sprint_burndown",
        "sprint_health",
        "sprint_days_remaining",
        "issues_calendar",
        "service_project_report",
        "filter_counts",
    ]
    title: str | None = None
    column: int = Field(default=0, ge=0, le=3)
    jql: str | None = Field(
        default=None,
        description="Data for this gadget (a saved filter is created); default: the project",
    )
    stat_type: str | None = Field(
        default=None,
        description="Grouping for pie/statistics gadgets: priorities, statuses, assignees, "
        "issuetype, reporter, components, labels",
    )
    days: int = Field(default=30, ge=1, le=365, description="Period for chart gadgets")


class CreateDashboardParams(Params):
    name: str
    description: str = ""
    share_with_project_key: ProjectKey | None = None
    project_key: ProjectKey | None = Field(
        default=None, description="Default data source for every gadget"
    )
    gadgets: list[GadgetDef] = Field(default_factory=list)


class GenerateReportParams(Params):
    report: Literal["project_summary", "workload", "issue_tracking", "sprint"]
    project_key: ProjectKey
    sprint_id: str | None = None
    days: int = Field(default=30, ge=1, le=365)


class AutomationActionDef(Params):
    type: Literal[
        "assign", "transition", "comment", "set_priority", "send_email", "email_issue_list"
    ]
    value: str = Field(
        description="assign: accountId | transition: status | comment/send_email: text with smart "
        "values | set_priority: priority name | email_issue_list: JQL of issues to list"
    )
    email_to: list[str] = Field(
        default_factory=lambda: ["assignee"],
        description="Email recipients: assignee, reporter, watchers or email addresses",
    )
    email_subject: str | None = None


class CreateAutomationRuleParams(Params):
    name: str
    project_key: ProjectKey
    trigger: Literal[
        "issue_created", "issue_transitioned", "issue_updated", "issue_commented", "scheduled"
    ]
    trigger_to_status: str | None = None
    schedule_cron: str | None = Field(
        default=None,
        description='scheduled: Quartz cron, e.g. "0 0 8 ? * MON-FRI" (08:00 weekdays)',
    )
    scheduled_jql: str | None = Field(
        default=None,
        description="scheduled: issues the actions run on (each matching issue); omit for "
        "issue-independent actions like email_issue_list",
    )
    jql_condition: str | None = Field(default=None, description="e.g. priority = High")
    actions: list[AutomationActionDef] = Field(min_length=1)
    enabled: bool = True


SPECS: list[OperationSpec] = [
    OperationSpec("jira.list_projects", "jira", "read", "List Jira projects.", ListProjectsParams),
    OperationSpec(
        "jira.create_project",
        "jira",
        "create",
        "Create a company-managed Jira Software or business project.",
        CreateProjectParams,
        needs_jira_admin=True,
    ),
    OperationSpec(
        "jira.update_project",
        "jira",
        "modify",
        "Update project name/description/lead.",
        UpdateProjectParams,
        needs_jira_admin=True,
    ),
    OperationSpec(
        "jira.create_issue_type",
        "jira",
        "create",
        "Create a global issue type.",
        CreateIssueTypeParams,
        needs_jira_admin=True,
    ),
    OperationSpec(
        "jira.configure_issue_types",
        "jira",
        "modify",
        "Give a company-managed project exactly these issue types (creates missing "
        "types, builds an issue type scheme and assigns it).",
        ConfigureIssueTypesParams,
        needs_jira_admin=True,
    ),
    OperationSpec(
        "jira.create_custom_field",
        "jira",
        "create",
        "Create a custom field (with options for select types).",
        CreateCustomFieldParams,
        needs_jira_admin=True,
    ),
    OperationSpec(
        "jira.create_screen",
        "jira",
        "create",
        "Create a screen with fields.",
        CreateScreenParams,
        needs_jira_admin=True,
    ),
    OperationSpec(
        "jira.add_field_to_screen",
        "jira",
        "modify",
        "Add a field to a screen tab.",
        AddFieldToScreenParams,
        needs_jira_admin=True,
    ),
    OperationSpec(
        "jira.create_field_configuration",
        "jira",
        "create",
        "Create a field configuration with required/hidden fields.",
        CreateFieldConfigurationParams,
        needs_jira_admin=True,
    ),
    OperationSpec(
        "jira.create_priority",
        "jira",
        "create",
        "Create an issue priority.",
        CreatePriorityParams,
        needs_jira_admin=True,
    ),
    OperationSpec(
        "jira.create_statuses",
        "jira",
        "create",
        "Create global statuses.",
        CreateStatusesParams,
        needs_jira_admin=True,
    ),
    OperationSpec(
        "jira.create_workflow",
        "jira",
        "create",
        "Create a workflow with statuses and transitions (validated before creation).",
        CreateWorkflowParams,
        needs_jira_admin=True,
    ),
    OperationSpec(
        "jira.assign_workflow",
        "jira",
        "modify",
        "Create a workflow scheme using a workflow and assign it to a project that "
        "has no issues yet.",
        AssignWorkflowParams,
        needs_jira_admin=True,
    ),
    OperationSpec(
        "jira.configure_workflow_scheme",
        "jira",
        "modify",
        "Give a project ONE workflow scheme that maps several issue types to workflows at once "
        "(keeps other mappings). Works on projects that already have issues: statuses are "
        "migrated automatically. Prefer this over several jira.assign_workflow steps.",
        ConfigureWorkflowSchemeParams,
        needs_jira_admin=True,
    ),
    OperationSpec(
        "jira.update_workflow",
        "jira",
        "modify",
        "Add statuses, transitions (e.g. reopen, rollback, failed) and JSM approval steps "
        "(approvers field, required approvals, approve/decline transitions) to a workflow.",
        UpdateWorkflowParams,
        needs_jira_admin=True,
    ),
    OperationSpec(
        "jira.set_issue_type_workflow",
        "jira",
        "modify",
        "TEAM-MANAGED projects (Jira or JSM): set the workflow of one existing issue type - its "
        "statuses, initial status and named transitions (reopen etc.). Statuses are never "
        "removed (Jira does not allow it via the API): an old status of the same category used "
        "only by this issue type is renamed (its issues keep their place); other old statuses stay "
        "in the workflow and are reported. Use instead of create_workflow / "
        "configure_workflow_scheme / configure_issue_types, which only work for company-managed "
        "projects.",
        SetIssueTypeWorkflowParams,
    ),
    OperationSpec(
        "jira.create_issue",
        "jira",
        "create",
        "Create an Epic, Story, Task, Bug or Sub-task (parent_key links to the epic or "
        "parent; supports start/due dates for timelines).",
        CreateIssueParams,
    ),
    OperationSpec("jira.update_issue", "jira", "modify", "Update issue fields.", UpdateIssueParams),
    OperationSpec(
        "jira.transition_issue",
        "jira",
        "modify",
        "Move an issue to a status.",
        TransitionIssueParams,
    ),
    OperationSpec(
        "jira.verify_workflow_transitions",
        "jira",
        "modify",
        "Prove a workflow works: walk a test issue through every transition (or the listed "
        "ones) in an order that never gets stuck in a final status, and confirm each move in "
        "the issue history. Use this instead of several jira.transition_issue steps.",
        VerifyWorkflowTransitionsParams,
    ),
    OperationSpec(
        "jira.link_issues",
        "jira",
        "create",
        "Link issues, e.g. from_issue blocks to_issue (dependencies).",
        LinkIssuesParams,
    ),
    OperationSpec(
        "jira.delete_issue",
        "jira",
        "destructive",
        "Permanently delete an issue.",
        DeleteIssueParams,
    ),
    OperationSpec("jira.search_issues", "jira", "read", "Run a JQL search.", SearchIssuesParams),
    OperationSpec(
        "jira.create_filter", "jira", "create", "Create a saved JQL filter.", CreateFilterParams
    ),
    OperationSpec(
        "jira.create_board",
        "jira",
        "create",
        "Create a Scrum or Kanban board (creates its filter when none is given).",
        CreateBoardParams,
    ),
    OperationSpec(
        "jira.create_sprint",
        "jira",
        "create",
        "Create a sprint on a Scrum board.",
        CreateSprintParams,
    ),
    OperationSpec(
        "jira.start_sprint", "jira", "modify", "Start a future sprint.", StartSprintParams
    ),
    OperationSpec(
        "jira.move_issues_to_sprint",
        "jira",
        "modify",
        "Move issues into a sprint.",
        MoveIssuesToSprintParams,
    ),
    OperationSpec(
        "jira.move_issues_to_backlog",
        "jira",
        "modify",
        "Take issues out of their sprint and put them back in the backlog. New issues are "
        "already in the backlog; Backlog is a board location, not a workflow status.",
        MoveIssuesToBacklogParams,
    ),
    OperationSpec(
        "jira.create_dashboard",
        "jira",
        "create",
        "Create a dashboard and add gadgets.",
        CreateDashboardParams,
    ),
    OperationSpec(
        "jira.generate_report",
        "jira",
        "read",
        "Compute a project summary, workload, issue-tracking or sprint report.",
        GenerateReportParams,
    ),
    OperationSpec(
        "jira.create_automation_rule",
        "jira",
        "create",
        "Create an automation rule (trigger, JQL condition, actions, smart values).",
        CreateAutomationRuleParams,
        needs_jira_admin=True,
        limitation="Depends on the Automation REST API being enabled for the site.",
    ),
    OperationSpec(
        "jira.configure_board_columns",
        "jira",
        "modify",
        "Change board column/status mapping.",
        UnsupportedParams,
        supported=False,
        limitation="Jira's public API exposes board configuration read-only.",
        alternative="Board settings → Columns; the agent can verify the mapping "
        "afterwards by reading the board configuration.",
    ),
    OperationSpec(
        "jira.configure_swimlanes",
        "jira",
        "modify",
        "Configure board swimlanes or quick filters.",
        UnsupportedParams,
        supported=False,
        limitation="No public API for swimlanes or quick filters.",
        alternative="Board settings → Swimlanes / Quick filters. Saved filters "
        "(jira.create_filter) can provide the JQL.",
    ),
    OperationSpec(
        "jira.configure_dashboard_layout",
        "jira",
        "modify",
        "Change dashboard column layout or gadget data sources.",
        UnsupportedParams,
        supported=False,
        limitation="Dashboard layout and legacy gadget preferences are not settable "
        "via the public API.",
        alternative="Open the dashboard → Edit layout / gadget menu → Configure.",
    ),
    OperationSpec("jira.whoami", "jira", "read", "Show the connected Atlassian account.", NoParams),
]
