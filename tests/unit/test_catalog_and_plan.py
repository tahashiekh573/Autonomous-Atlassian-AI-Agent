import pytest

from app.agents.confluence_agent import ConfluenceAgent
from app.agents.integration_agent import IntegrationAgent
from app.agents.jira_agent import JiraAgent
from app.agents.jsm_agent import JsmAgent
from app.agents.verification_agent import VERIFIERS
from app.core.exceptions import OperationInputError
from app.orchestrators.approval_policy import required_role, requires_approval
from app.orchestrators.plan_validation import validate_plan
from app.orchestrators.references import find_refs, resolve
from app.schemas.agents import ExecutionPlan, PlannedOperation
from app.schemas.operations.catalog import CATALOG, describe_catalog

AGENTS = {
    "jira": JiraAgent,
    "jsm": JsmAgent,
    "confluence": ConfluenceAgent,
    "integration": IntegrationAgent,
}
CAPS = {"products": {"jira": True, "jsm": True, "confluence": True}, "is_jira_admin": True}


def test_every_supported_operation_has_a_handler_and_mutations_have_verifiers() -> None:
    for name, spec in CATALOG.items():
        handlers = AGENTS[spec.agent].handlers
        if spec.supported:
            assert name in handlers, f"{name} has no handler"
            if spec.risk != "read":
                assert name in VERIFIERS, f"{name} changes state but has no verifier"
        else:
            assert spec.limitation and spec.alternative, f"{name} must explain the limitation"
    for agent in AGENTS.values():
        assert set(agent.handlers) <= set(CATALOG)


def test_catalog_description_lists_every_operation() -> None:
    text = describe_catalog()
    for name in CATALOG:
        assert f"### {name}" in text
    assert "NOT SUPPORTED BY API" in text


def test_resolve_keeps_types_and_substitutes_inline() -> None:
    outputs = {"s1": {"id": 42, "key": "BANK"}}
    resolved = resolve({"board": "${s1.id}", "jql": "project = ${s1.key}", "n": [1]}, outputs)
    assert resolved == {"board": 42, "jql": "project = BANK", "n": [1]}
    assert find_refs({"a": ["${s2.key}", {"b": "${s7.id}"}]}) == {"s2", "s7"}


def test_resolve_fails_for_missing_output() -> None:
    with pytest.raises(OperationInputError):
        resolve("${s3.key}", {"s1": {"key": "X"}})


def _plan(*ops: PlannedOperation) -> ExecutionPlan:
    return ExecutionPlan(summary="t", operations=list(ops))


def test_validation_adds_implied_dependencies_and_ignores_ref_typed_params() -> None:
    plan = _plan(
        PlannedOperation(
            id="s1",
            operation="confluence.create_space",
            description="",
            params={"key": "DOCS", "name": "Docs"},
        ),
        PlannedOperation(
            id="s2",
            operation="confluence.create_page",
            description="",
            params={"space_key": "${s1.key}", "title": "Home"},
        ),
    )
    assert [i for i in validate_plan(plan, CAPS, 40) if i.severity == "error"] == []
    assert plan.operations[1].depends_on == ["s1"]


def test_validation_flags_bad_plans() -> None:
    plan = _plan(
        PlannedOperation(id="s1", operation="jira.made_up", description="", params={}),
        PlannedOperation(
            id="s2",
            operation="jira.create_project",
            description="",
            params={"key": "bad key", "name": "X"},
        ),
        PlannedOperation(
            id="s3",
            operation="confluence.create_page",
            description="",
            params={"space_key": "${s9.key}", "title": "x"},
        ),
        PlannedOperation(
            id="s4", operation="jsm.configure_sla_calendar", description="", params={}
        ),
    )
    caps = {"products": {"jira": True, "jsm": True, "confluence": False}, "is_jira_admin": False}
    messages = [(i.severity, i.operation_id, i.message) for i in validate_plan(plan, caps, 40)]
    assert ("error", "s1", "Unknown operation 'jira.made_up'.") in messages
    assert any(s == "error" and o == "s2" and "Invalid param key" in m for s, o, m in messages)
    assert any(o == "s2" and "administrator" in m for _, o, m in messages)
    assert any(o == "s3" and "not an earlier step" in m for _, o, m in messages)
    assert any(o == "s3" and "confluence is not available" in m for _, o, m in messages)
    assert any(s == "warning" and o == "s4" for s, o, _ in messages)


def test_approval_policy() -> None:
    assert requires_approval("create", ["read"]) is True
    assert requires_approval("create", ["read", "create"]) is False
    assert requires_approval("destructive", ["read", "create", "modify", "destructive"]) is True
    assert requires_approval("security", ["security"]) is True
    assert required_role("destructive") == "admin"
    assert required_role("create") == "operator"


def test_transition_to_backlog_is_blocked_at_plan_time() -> None:
    plan = _plan(
        PlannedOperation(
            id="s1",
            operation="jira.transition_issue",
            description="",
            params={"issue_key": "AIDEMO-2", "to_status": "Backlog"},
        )
    )
    errors = [i for i in validate_plan(plan, CAPS, 40) if i.severity == "error"]
    assert errors and "move_issues_to_backlog" in errors[0].message
