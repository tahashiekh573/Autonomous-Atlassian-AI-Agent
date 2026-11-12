"""Transition tour: every workflow transition is tested without stranding the issue in Done."""

from app.agents.handlers.jira_transition_tour import Edge, Graph, plan_tour
from app.agents.planning_agent import collapse_transition_chains
from app.schemas.agents import ExecutionPlan, PlannedOperation

TODO, PROG, REVIEW, DONE = "1", "3", "10001", "10002"
NAMES = {TODO: "To Do", PROG: "In Progress", REVIEW: "In Review", DONE: "Done"}
# The DEMO Simple Ticket Workflow the user asked for.
DEMO = Graph(
    NAMES,
    [
        Edge(TODO, PROG, "Start Progress"),
        Edge(PROG, REVIEW, "Submit for Review"),
        Edge(REVIEW, DONE, "Complete"),
        Edge(REVIEW, PROG, "Rework"),
        Edge(PROG, TODO, "Reopen"),
    ],
)


def _moves(start: str, route: list[str]) -> list[tuple[str, str]]:
    moves, current = [], start
    for target in route:
        moves.append((current, target))
        current = target
    return moves


def test_every_transition_is_tested_and_done_comes_last() -> None:
    route, unreachable = plan_tour(DEMO, TODO, list(DEMO.edges))
    assert unreachable == []
    moves = _moves(TODO, route)
    assert {(e.source, e.target) for e in DEMO.edges} <= set(moves)
    assert route[-1] == DONE and DONE not in route[:-1]
    # every move is a real transition of the workflow
    assert all((s, t) in {(e.source, e.target) for e in DEMO.edges} for s, t in moves)


def test_global_transition_and_unreachable_are_reported() -> None:
    graph = Graph(NAMES, [Edge(TODO, DONE, "Close"), Edge(None, PROG, "Any to progress")])
    route, unreachable = plan_tour(graph, TODO, [Edge(None, PROG, "x"), Edge(TODO, DONE, "y")])
    # the global move can run from Done, so To Do -> Done goes first and both get tested
    assert route == [DONE, PROG] and unreachable == []
    stuck = Graph(NAMES, [Edge(TODO, PROG, "a"), Edge(REVIEW, DONE, "b")])
    route, unreachable = plan_tour(stuck, TODO, list(stuck.edges))
    assert route == [PROG] and unreachable == [Edge(REVIEW, DONE, "b")]


def _op(i: int, operation: str, **params: object) -> PlannedOperation:
    return PlannedOperation(id=f"s{i}", operation=operation, description=operation, params=params)


def test_transition_chain_after_a_workflow_becomes_one_tour() -> None:
    plan = ExecutionPlan(
        summary="x",
        operations=[
            _op(1, "jira.create_workflow", name="W"),
            _op(2, "jira.create_issue", project_key="DEMO", issue_type="Task", summary="t"),
            *[
                _op(i, "jira.transition_issue", issue_key="${s2.key}", to_status=st)
                for i, st in [(3, "In Progress"), (4, "In Review"), (5, "Done"), (6, "In Review")]
            ],
            _op(7, "jira.add_comment", issue_key="${s6.key}", body="done"),
        ],
    )
    plan.operations[3].depends_on = ["s2", "s3"]
    collapse_transition_chains(plan)
    ops = {o.id: o for o in plan.operations}
    assert sorted(ops) == ["s1", "s2", "s3", "s7"]
    assert ops["s3"].operation == "jira.verify_workflow_transitions"
    assert ops["s3"].params == {"issue_key": "${s2.key}", "transitions": []}
    assert ops["s7"].params["issue_key"] == "${s3.key}"


def test_single_move_without_a_workflow_is_left_alone() -> None:
    plan = ExecutionPlan(
        summary="x",
        operations=[
            _op(i, "jira.transition_issue", issue_key="A-1", to_status="Done") for i in (1, 2, 3)
        ],
    )
    collapse_transition_chains(plan)
    assert [o.operation for o in plan.operations] == ["jira.transition_issue"] * 3
