"""Team-managed workflow builder: renames own statuses within a category, never removes any."""

from app.agents.handlers.jira_team_workflows import _build
from app.schemas.operations.jira_ops import SetIssueTypeWorkflowParams


def _fixture() -> tuple[dict, dict]:
    statuses = [
        {"id": "1", "name": "To Do", "statusCategory": "TODO", "statusReference": "1"},
        {"id": "2", "name": "In progress", "statusCategory": "IN_PROGRESS", "statusReference": "2"},
        {"id": "3", "name": "Done", "statusCategory": "DONE", "statusReference": "3"},
        {"id": "4", "name": "Pending", "statusCategory": "IN_PROGRESS", "statusReference": "4"},
    ]
    workflow = {
        "id": "wf-1",
        "version": {"versionNumber": 1, "id": "v"},
        "statuses": [{"statusReference": r} for r in ("1", "2", "3", "4")],
        "transitions": [],
    }
    return workflow, {"statuses": statuses, "workflows": [workflow]}


def test_renames_by_category_and_keeps_shared_and_extra_statuses() -> None:
    workflow, body = _fixture()
    p = SetIssueTypeWorkflowParams.model_validate(
        {
            "project_key": "ACSD",
            "issue_type": "Support",
            "statuses": [
                {"name": "Open", "category": "TODO"},
                {"name": "In Progress", "category": "IN_PROGRESS"},
                {"name": "Resolved", "category": "DONE"},
                {"name": "Closed", "category": "DONE"},
            ],
            "transitions": [
                {"name": "Start", "from_statuses": ["Open"], "to_status": "In Progress"},
                {"name": "Resolve", "from_statuses": ["In Progress"], "to_status": "Resolved"},
                {"name": "Reopen", "from_statuses": ["Resolved", "Closed"], "to_status": "Open"},
            ],
        }
    )
    payload, renamed, leftover = _build(p, workflow, body, shared={"1"})

    # "To Do" is shared with another issue type, so it is kept and "Open" is new; same-category
    # own statuses are renamed in place; "Done" never becomes an in-progress status.
    # "In progress" matches "In Progress" by name and is reused as-is.
    assert renamed == [("Done", "Resolved")]
    assert leftover == ["To Do", "Pending"]
    names = {s["name"] for s in payload["statuses"]}
    assert {"Open", "In progress", "Resolved", "Closed", "To Do", "Pending"} == names
    wf = payload["workflows"][0]
    assert "statusMappings" not in wf  # nothing is removed, so no migration is requested
    kinds = {t["name"]: t["type"] for t in wf["transitions"]}
    assert kinds["Create"] == "INITIAL" and kinds["Reopen"] == "DIRECTED"
    assert "Move to Open" in kinds  # a way out of the kept old status
