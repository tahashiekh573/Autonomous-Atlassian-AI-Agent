"""Prove a workflow works by walking a test issue through each of its transitions.

The tour is planned on the issue's real workflow graph: it always heads for the nearest untested
transition, but never takes one that would strand the issue (e.g. into a final status with no way
out) while other transitions still need testing. Every move is then confirmed in the issue history.
"""

from collections import deque
from dataclasses import dataclass

from app.agents.handlers.base import HandlerContext, HandlerResult, same_name
from app.core.exceptions import AtlassianError, OperationInputError
from app.schemas.operations.jira_ops import VerifyWorkflowTransitionsParams

MAX_MOVES = 80


@dataclass(frozen=True)
class Edge:
    source: str | None  # None = global transition ("from any status")
    target: str
    name: str


@dataclass
class Graph:
    names: dict[str, str]  # status id -> name
    edges: list[Edge]

    def next_statuses(self, status: str) -> set[str]:
        return {e.target for e in self.edges if e.source in (status, None) and e.target != status}

    def distances(self, start: str) -> dict[str, list[str]]:
        """Shortest path (list of status ids after start) to every reachable status."""
        paths: dict[str, list[str]] = {start: []}
        queue = deque([start])
        while queue:
            node = queue.popleft()
            for nxt in sorted(self.next_statuses(node)):
                if nxt not in paths:
                    paths[nxt] = [*paths[node], nxt]
                    queue.append(nxt)
        return paths

    def status_id(self, name: str) -> str | None:
        return next((sid for sid, n in self.names.items() if same_name(n, name)), None)


def _keeps_going(graph: Graph, edge: Edge, todo: list[Edge]) -> bool:
    """After taking `edge`, can every other untested transition still be reached?"""
    after = graph.distances(edge.target)
    return all(e.source is None or e.source in after for e in todo if e is not edge)


def plan_tour(graph: Graph, start: str, wanted: list[Edge]) -> tuple[list[str], list[Edge]]:
    """Status ids to move through (in order) and the wanted transitions that cannot be reached."""
    todo = list(wanted)
    route: list[str] = []
    current = start
    while todo and len(route) < MAX_MOVES:
        reach = graph.distances(current)
        candidates = sorted(
            (e for e in todo if e.source is None or e.source in reach),
            key=lambda e: 0 if e.source is None else len(reach[e.source]),
        )
        if not candidates:
            break

        edge = next((e for e in candidates if _keeps_going(graph, e, todo)), candidates[0])
        hops = [] if edge.source is None else reach[edge.source]
        for hop in [*hops, edge.target]:
            todo = [e for e in todo if not (e.target == hop and e.source in (current, None))]
            route.append(hop)
            current = hop
    return route, todo


async def _graph(ctx: HandlerContext, issue_key: str) -> tuple[Graph, str]:
    fields = (await ctx.jira.get_issue(issue_key, fields="status,project,issuetype"))["fields"]
    try:
        body = await ctx.jira.get_issue_type_workflow(
            str(fields["project"]["id"]), str(fields["issuetype"]["id"])
        )
    except AtlassianError as exc:
        raise OperationInputError(f"Cannot read the workflow of {issue_key}: {exc}") from exc
    workflows = body.get("workflows") or []
    if not workflows:
        raise OperationInputError(f"No workflow found for {issue_key}.")
    ref = {
        str(s.get("statusReference") or s.get("id")): (str(s.get("id")), str(s.get("name")))
        for s in body.get("statuses") or []
    }
    edges: list[Edge] = []
    for t in workflows[0].get("transitions") or []:
        target = ref.get(str(t.get("toStatusReference")))
        if target is None or t.get("type") == "INITIAL":
            continue
        name = str(t.get("name") or "")
        if t.get("type") == "GLOBAL":
            edges.append(Edge(None, target[0], name))
        for link in t.get("links") or []:
            source = ref.get(str(link.get("fromStatusReference")))
            if source:
                edges.append(Edge(source[0], target[0], name))
    return Graph(dict(ref.values()), edges), str(fields["status"]["id"])


def _wanted(graph: Graph, p: VerifyWorkflowTransitionsParams) -> list[Edge]:
    if not p.transitions:
        return list(dict.fromkeys(graph.edges))
    wanted: list[Edge] = []
    missing: list[str] = []
    for t in p.transitions:
        target = graph.status_id(t.to_status)
        source = graph.status_id(t.from_status) if t.from_status.strip() else None
        match = next(
            (
                e
                for e in graph.edges
                if e.target == target and (e.source == source or e.source is None)
            ),
            None,
        )
        if match is None:
            missing.append(f"{t.from_status or 'any status'} → {t.to_status}")
        else:
            wanted.append(Edge(source if match.source else None, match.target, match.name))
    if missing:
        listing = ", ".join(
            f"{graph.names.get(e.source, 'any') if e.source else 'any'} → {graph.names[e.target]}"
            for e in graph.edges
        )
        raise OperationInputError(
            f"Not in the workflow: {', '.join(missing)} (workflow transitions: {listing})."
        )
    return list(dict.fromkeys(wanted))


def _label(graph: Graph, source: str | None, target: str) -> str:
    return f"{graph.names.get(source, 'any') if source else 'any'} → {graph.names.get(target)}"


async def verify_workflow_transitions(
    ctx: HandlerContext, p: VerifyWorkflowTransitionsParams
) -> HandlerResult:
    graph, start = await _graph(ctx, p.issue_key)
    wanted = _wanted(graph, p)
    route, unreachable = plan_tour(graph, start, wanted)
    if unreachable:
        stuck = ", ".join(_label(graph, e.source, e.target) for e in unreachable)
        raise OperationInputError(
            f"These transitions cannot be reached from {graph.names.get(start)} in "
            f"{p.issue_key}'s workflow: {stuck}."
        )
    moves: list[str] = []
    current = start
    for target in route:
        options = await ctx.jira.get_transitions(p.issue_key)
        step = next((t for t in options if str((t.get("to") or {}).get("id")) == target), None)
        if step is None:
            raise OperationInputError(
                f"{p.issue_key} stopped in {graph.names.get(current)}: the transition to "
                f"'{graph.names.get(target)}' is not available (it needs fields or a condition "
                f"the API cannot satisfy). Tested so far: {', '.join(moves) or 'none'}."
            )
        await ctx.jira.transition_issue(p.issue_key, str(step["id"]))
        moves.append(_label(graph, current, target))
        current = target
    tested = [_label(graph, e.source, e.target) for e in wanted]
    return HandlerResult(
        message=(
            f"Tested {len(wanted)} transition(s) on {p.issue_key} in {len(moves)} move(s): "
            f"{' | '.join(moves)}. Final status: {graph.names.get(current)}."
        ),
        outputs={
            "key": p.issue_key,
            "moves": moves,
            "tested": tested,
            "wanted": [[e.source, e.target] for e in wanted],
            "final_status": graph.names.get(current),
        },
    )
