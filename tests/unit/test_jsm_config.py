"""Queues, SLA goals and automation safety rules (pure logic; live behaviour is tested E2E)."""

import pytest

from app.agents.handlers.jsm_config import _pick_calendar, _strip_project, parse_duration
from app.core.exceptions import OperationInputError
from app.schemas.operations.rules import automation_problem

CALENDARS = [
    {"id": 18, "name": "Sample 9-5 Calendar", "default": False},
    {"id": -1, "name": "24/7 Calendar (Default)", "default": True},
]


@pytest.mark.parametrize(
    ("text", "ms"),
    [
        ("15m", 900_000),
        ("2h", 7_200_000),
        ("1h 30m", 5_400_000),
        ("1d", 86_400_000),
        ("15 minutes", 900_000),
        ("4 hours", 14_400_000),
    ],
)
def test_parse_duration(text: str, ms: int) -> None:
    assert parse_duration(text) == ms


def test_parse_duration_rejects_nonsense() -> None:
    with pytest.raises(OperationInputError):
        parse_duration("soon")


def test_queue_jql_drops_the_project_clause_jira_adds_itself() -> None:
    assert _strip_project("project = EITSD AND assignee is EMPTY", "EITSD") == "assignee is EMPTY"
    assert _strip_project('project = "EITSD" AND priority = High', "EITSD") == "priority = High"
    assert _strip_project("priority = High", "EITSD") == "priority = High"


def test_calendar_choice() -> None:
    assert _pick_calendar(CALENDARS, "Mon-Fri 9 AM-6 PM business hours") == 18
    assert _pick_calendar(CALENDARS, "24/7") == -1
    assert _pick_calendar(CALENDARS, "Sample 9-5 Calendar") == 18
    assert _pick_calendar(CALENDARS, None) is None


def test_auto_assign_on_new_tickets_is_allowed_but_unconditional_close_is_not() -> None:
    assign_new = {"trigger": "issue_created", "actions": [{"type": "assign", "value": "x"}]}
    close_on_update = {
        "trigger": "issue_updated",
        "actions": [{"type": "transition", "value": "Closed"}],
    }
    scheduled_no_jql = {"trigger": "scheduled", "actions": [{"type": "comment", "value": "x"}]}
    assert automation_problem(assign_new) is None
    assert automation_problem(close_on_update)
    assert "scheduled_jql" in (automation_problem(scheduled_no_jql) or "")


def test_metricless_sla_jql_is_rewritten_over_project_metrics() -> None:
    from app.agents.handlers.jsm_config import fix_sla_jql

    names = ["Time to first response", "Time to resolution"]
    both = '("Time to first response" = breached() OR "Time to resolution" = breached())'
    assert fix_sla_jql("resolution = Unresolved AND slaFunction(breached())", names) == (
        f"resolution = Unresolved AND {both}"
    )
    assert fix_sla_jql("SLA = breached()", names) == both
    assert fix_sla_jql("resolution = Unresolved AND breached()", names).endswith(both)
    kept = '"Time to resolution" = breached() AND priority = High'
    assert fix_sla_jql(kept, names) == kept
