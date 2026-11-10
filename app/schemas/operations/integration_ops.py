"""Cross-product operations (Jira ↔ JSM ↔ Confluence)."""

from pydantic import Field

from app.schemas.operations.spec import IssueKey, OperationSpec, Params, ProjectKey, SpaceKey


class LinkIssueToPageParams(Params):
    issue_key: IssueKey
    page_id: str


class LinkIncidentToIssueParams(Params):
    incident_key: IssueKey
    issue_key: IssueKey
    link_type: str = "Relates"


class CreateDevIssueFromIncidentParams(Params):
    incident_key: IssueKey
    target_project_key: ProjectKey
    issue_type: str = "Bug"
    link_type: str = "Relates"


class EmbedIssuesInPageParams(Params):
    page_id: str
    jql: str
    heading: str = "Related Jira issues"
    max_issues: int = Field(default=20, ge=1, le=200)


class LinkProjectToSpaceParams(Params):
    project_key: ProjectKey
    space_key: SpaceKey


SPECS: list[OperationSpec] = [
    OperationSpec(
        "integration.link_issue_to_page",
        "integration",
        "create",
        "Link a Jira/JSM issue to a Confluence page (remote link on the issue).",
        LinkIssueToPageParams,
        requires_products=("jira", "confluence"),
    ),
    OperationSpec(
        "integration.link_incident_to_issue",
        "integration",
        "create",
        "Link a JSM incident with a development issue for traceability.",
        LinkIncidentToIssueParams,
        requires_products=("jira",),
    ),
    OperationSpec(
        "integration.create_dev_issue_from_incident",
        "integration",
        "create",
        "Create a development issue from a JSM incident and link them.",
        CreateDevIssueFromIncidentParams,
        requires_products=("jira",),
    ),
    OperationSpec(
        "integration.embed_issues_in_page",
        "integration",
        "modify",
        "Append a live Jira issues (JQL) macro to a Confluence page.",
        EmbedIssuesInPageParams,
        requires_products=("jira", "confluence"),
    ),
    OperationSpec(
        "integration.link_project_to_space",
        "integration",
        "modify",
        "Reference a Confluence space from a Jira project's description and add a "
        "project issues macro to the space home page.",
        LinkProjectToSpaceParams,
        requires_products=("jira", "confluence"),
        needs_jira_admin=True,
    ),
]
