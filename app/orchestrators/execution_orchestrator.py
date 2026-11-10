"""Execution graph: select → execute → verify (loop) → respond.

Operations run one at a time in plan order. A step runs only when it is approved and every
dependency completed (verified). Nothing is reported as completed without verification.
"""

import logging
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

from app.core.exceptions import OperationInputError
from app.orchestrators.agent_set import AgentSet
from app.orchestrators.events import RunEventSink
from app.orchestrators.references import resolve
from app.schemas.agents import (
    ExecutionPlan,
    ExecutionReport,
    Language,
    OperationOutcome,
    OperationRequest,
    OperationStatus,
    OperationSummary,
    ReportInput,
    VerificationRequest,
    VerificationResult,
)
from app.schemas.operations.catalog import get_spec

logger = logging.getLogger(__name__)

_DONE: frozenset[str] = frozenset({"completed", "failed", "skipped"})


class ExecutionResult(BaseModel):
    statuses: dict[str, OperationStatus]
    messages: dict[str, str]
    outcomes: dict[str, OperationOutcome]
    verifications: dict[str, VerificationResult]
    report: ExecutionReport


class _State(TypedDict, total=False):
    run_id: str
    plan: ExecutionPlan
    approved: list[str]
    instruction: str
    language: Language
    statuses: dict[str, OperationStatus]
    messages: dict[str, str]
    outcomes: dict[str, OperationOutcome]
    verifications: dict[str, VerificationResult]
    resolved: dict[str, dict[str, Any]]
    current: str | None
    report: ExecutionReport


class ExecutionOrchestrator:
    def __init__(self, agents: AgentSet, sink: RunEventSink) -> None:
        self._agents = agents
        self._sink = sink
        self._graph = self._build()

    def _build(self) -> Any:
        graph = StateGraph(_State)
        graph.add_node("select", self._select)
        graph.add_node("execute", self._execute)
        graph.add_node("verify", self._verify)
        graph.add_node("respond", self._respond)
        graph.add_edge(START, "select")
        graph.add_conditional_edges(
            "select",
            lambda s: "execute" if s.get("current") else "respond",
            {"execute": "execute", "respond": "respond"},
        )
        graph.add_conditional_edges(
            "execute",
            lambda s: "verify" if s["statuses"][str(s["current"])] == "in_progress" else "select",
            {"verify": "verify", "select": "select"},
        )
        graph.add_edge("verify", "select")
        graph.add_edge("respond", END)
        return graph.compile()

    async def run(
        self,
        run_id: str,
        plan: ExecutionPlan,
        approved: set[str],
        instruction: str,
        language: Language = "en",
    ) -> ExecutionResult:
        state: _State = await self._graph.ainvoke(
            {
                "run_id": run_id,
                "plan": plan,
                "approved": sorted(approved),
                "instruction": instruction,
                "language": language,
                "statuses": {op.id: "pending" for op in plan.operations},
                "messages": {},
                "outcomes": {},
                "verifications": {},
                "resolved": {},
                "current": None,
            },
            config={"recursion_limit": 4 * len(plan.operations) + 10},
        )
        return ExecutionResult(
            statuses=state["statuses"],
            messages=state["messages"],
            outcomes=state["outcomes"],
            verifications=state["verifications"],
            report=state["report"],
        )

    async def _set(
        self, state: _State, op_id: str, status: OperationStatus, message: str, **extra: Any
    ) -> None:
        state["statuses"][op_id] = status
        state["messages"][op_id] = message
        await self._sink.operation_status(state["run_id"], op_id, status, message=message, **extra)

    # --- nodes ------------------------------------------------------------------------------

    async def _select(self, state: _State) -> _State:
        statuses = state["statuses"]
        for op in state["plan"].operations:
            if statuses[op.id] != "pending":
                continue
            spec = get_spec(op.operation)
            if op.id not in state["approved"]:
                await self._set(state, op.id, "skipped", "Not approved.")
                continue
            if spec is not None and not spec.supported:
                await self._set(
                    state,
                    op.id,
                    "skipped",
                    f"Not supported by the Atlassian public API. {spec.limitation} "
                    f"Manual step: {spec.alternative}",
                )
                continue
            blocked = [d for d in op.depends_on if statuses.get(d) in ("failed", "skipped")]
            if blocked:
                await self._set(
                    state,
                    op.id,
                    "skipped",
                    f"Skipped because {', '.join(blocked)} did not complete.",
                )
                continue
            if all(statuses.get(d) == "completed" for d in op.depends_on):
                return {"current": op.id, "statuses": statuses, "messages": state["messages"]}
        return {"current": None, "statuses": statuses, "messages": state["messages"]}

    async def _execute(self, state: _State) -> _State:
        op_id = str(state["current"])
        op = next(o for o in state["plan"].operations if o.id == op_id)
        agent = self._agents.for_operation(op.operation)
        outputs = {
            k: v.outputs
            for k, v in state["outcomes"].items()
            if state["statuses"][k] == "completed"
        }
        try:
            params = resolve(op.params, outputs)
        except OperationInputError as exc:
            await self._set(state, op_id, "failed", exc.message)
            return {"statuses": state["statuses"], "messages": state["messages"]}
        state["resolved"][op_id] = params
        await self._sink.run_progress(
            state["run_id"], current_agent=agent.name, message=f"{op_id}: {op.description}"
        )
        await self._set(
            state, op_id, "in_progress", "Executing…", agent=agent.name, resolved_params=params
        )
        outcome = await agent.run(
            OperationRequest(
                run_id=state["run_id"],
                op_id=op_id,
                operation=op.operation,
                params=params,
            )
        )
        state["outcomes"][op_id] = outcome
        if not outcome.succeeded:
            await self._set(
                state, op_id, "failed", outcome.message, agent=agent.name, outcome=outcome
            )
        return {
            "statuses": state["statuses"],
            "messages": state["messages"],
            "outcomes": state["outcomes"],
            "resolved": state["resolved"],
        }

    async def _verify(self, state: _State) -> _State:
        op_id = str(state["current"])
        op = next(o for o in state["plan"].operations if o.id == op_id)
        outcome = state["outcomes"][op_id]
        await self._sink.run_progress(
            state["run_id"],
            current_agent=self._agents.verification.name,
            message=f"Verifying {op_id}",
        )
        result = await self._agents.verification.run(
            VerificationRequest(
                operation=op.operation,
                params=state["resolved"][op_id],
                outcome=outcome,
            )
        )
        state["verifications"][op_id] = result
        status: OperationStatus = "completed" if result.verified else "failed"
        message = (
            outcome.message
            if result.verified
            else f"{outcome.message} — verification failed: {result.message}"
        )
        await self._set(
            state, op_id, status, message, agent=outcome.agent, outcome=outcome, verification=result
        )
        return {
            "statuses": state["statuses"],
            "messages": state["messages"],
            "verifications": state["verifications"],
        }

    async def _respond(self, state: _State) -> _State:
        await self._sink.run_progress(
            state["run_id"],
            current_agent=self._agents.response.name,
            message="Writing the execution report",
        )
        summaries = [
            OperationSummary(
                op_id=op.id,
                operation=op.operation,
                description=op.description,
                status=state["statuses"][op.id],
                message=state["messages"].get(op.id, ""),
                resource=(
                    state["outcomes"][op.id].resource if op.id in state["outcomes"] else None
                ),
                verified=(
                    state["verifications"][op.id].verified
                    if op.id in state["verifications"]
                    else None
                ),
            )
            for op in state["plan"].operations
        ]
        report = await self._agents.response.run(
            ReportInput(
                instruction=state["instruction"],
                language=state["language"],
                plan_summary=state["plan"].summary,
                operations=summaries,
            )
        )
        await self._sink.run_progress(state["run_id"], current_agent=None, message="Done")
        return {"report": report}
