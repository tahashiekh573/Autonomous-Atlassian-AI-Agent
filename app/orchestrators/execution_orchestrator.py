"""Execution graph: select → execute → verify (loop) → respond.

Operations run one at a time in plan order. A step runs only when it is approved and every
dependency completed (verified). Nothing is reported as completed without verification.
"""

import logging
from collections.abc import Callable
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

from app.agents.step_repair_agent import StepRepairInput
from app.core.exceptions import LLMError, OperationInputError
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
    PlannedOperation,
    ReportInput,
    VerificationRequest,
    VerificationResult,
)
from app.schemas.operations.catalog import get_spec, param_errors

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


# Failures caused by what was sent (bad JQL, wrong names); not permissions or outages.
STOPPED_MESSAGE = "Stopped by you before this step started; nothing was changed for it."
_REPAIRABLE = {"operation_invalid_input", "atlassian_api_error", "validation_error"}


class ExecutionOrchestrator:
    def __init__(
        self,
        agents: AgentSet,
        sink: RunEventSink,
        should_stop: Callable[[], bool] | None = None,
    ) -> None:
        self._agents = agents
        self._sink = sink
        self._should_stop = should_stop or (lambda: False)
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
        preskipped: dict[str, str] | None = None,
    ) -> ExecutionResult:
        preskipped = preskipped or {}
        state: _State = await self._graph.ainvoke(
            {
                "run_id": run_id,
                "plan": plan,
                "approved": sorted(approved),
                "instruction": instruction,
                "language": language,
                "statuses": {
                    op.id: "skipped" if op.id in preskipped else "pending" for op in plan.operations
                },
                "messages": dict(preskipped),
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
        if self._should_stop():
            # Stopped by the user: the step that was running has finished; start nothing new.
            for op in state["plan"].operations:
                if statuses[op.id] == "pending":
                    await self._set(state, op.id, "skipped", STOPPED_MESSAGE)
            return {"current": None, "statuses": statuses, "messages": state["messages"]}
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
        if not outcome.succeeded and outcome.error_code in _REPAIRABLE:
            outcome, params = await self._repair_and_retry(state, op, params, outcome)
            state["resolved"][op_id] = params
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

    async def _repair_and_retry(
        self,
        state: _State,
        op: PlannedOperation,
        params: dict[str, Any],
        outcome: OperationOutcome,
    ) -> tuple[OperationOutcome, dict[str, Any]]:
        """One corrected attempt with the error Jira gave; the original failure otherwise."""
        if self._agents.repair is None:
            return outcome, params
        try:
            fix = await self._agents.repair.run(
                StepRepairInput(
                    instruction=state["instruction"],
                    operation=op.operation,
                    description=op.description,
                    params=params,
                    error=outcome.message,
                )
            )
        except LLMError:
            return outcome, params
        spec = get_spec(op.operation)
        if not fix.fixable or fix.params == params or spec is None:
            return outcome, params
        if param_errors(spec.params, fix.params):
            return outcome, params
        await self._sink.run_progress(
            state["run_id"], current_agent="step_repair_agent", message=f"{op.id}: auto-correcting"
        )
        retry = await self._agents.for_operation(op.operation).run(
            OperationRequest(
                run_id=state["run_id"], op_id=op.id, operation=op.operation, params=fix.params
            )
        )
        if not retry.succeeded:
            return outcome, params
        retry.message = f"{retry.message} (auto-corrected: {fix.explanation})"[:2000]
        return retry, fix.params

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
                coverage=state["plan"].coverage,
            )
        )
        await self._sink.run_progress(state["run_id"], current_agent=None, message="Done")
        return {"report": report}
