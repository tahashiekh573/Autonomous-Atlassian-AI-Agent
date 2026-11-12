"""Planning graph: understand → (clarify | discover → plan → preflight)."""

import json
import logging
from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from app.agents.step_repair_agent import StepRepairInput
from app.core.exceptions import LLMError
from app.orchestrators.agent_set import AgentSet
from app.orchestrators.events import RunEventSink
from app.orchestrators.plan_validation import fill_missing_names, validate_plan
from app.orchestrators.references import contains_ref
from app.schemas.agents import (
    ExecutionPlan,
    Intent,
    OperationOutcome,
    OperationRequest,
    PlanIssue,
    PlannedOperation,
    PlanningInput,
    UnderstandingInput,
)
from app.schemas.operations.catalog import describe_catalog, get_spec, param_errors

logger = logging.getLogger(__name__)

PlanningOutcome = Literal["needs_clarification", "planned", "blocked"]


class PlanningResult(BaseModel):
    outcome: PlanningOutcome
    intent: Intent
    plan: ExecutionPlan | None = None
    issues: list[PlanIssue] = Field(default_factory=list)
    checks: dict[str, OperationOutcome] = Field(default_factory=dict)


class _State(TypedDict, total=False):
    run_id: str
    request: UnderstandingInput
    capabilities: dict[str, Any]
    intent: Intent
    workspace: dict[str, Any]
    plan: ExecutionPlan
    issues: list[PlanIssue]
    checks: dict[str, OperationOutcome]


_DISCOVERY = {
    "jira": ("jira.list_projects", {"max_results": 200}, "projects"),
    "jsm": ("jsm.list_service_desks", {}, "service_desks"),
    "confluence": ("confluence.list_spaces", {}, "spaces"),
}


MAX_PLAN_REPAIRS = 12


def _not_repairable(error: str) -> bool:
    """Conflicts that are facts about the site, not mistakes in the params."""
    text = error.casefold()
    return any(k in text for k in ("already used", "already exists", "permission", "licen"))


class PlanningOrchestrator:
    def __init__(self, agents: AgentSet, sink: RunEventSink, max_operations: int = 40) -> None:
        self._agents = agents
        self._sink = sink
        self._max_operations = max_operations
        self._graph = self._build()

    def _build(self) -> Any:
        graph = StateGraph(_State)
        graph.add_node("understand", self._understand)
        graph.add_node("discover", self._discover)
        graph.add_node("plan", self._plan)
        graph.add_node("preflight", self._preflight)
        graph.add_edge(START, "understand")
        graph.add_conditional_edges(
            "understand", self._after_understand, {"clarify": END, "continue": "discover"}
        )
        graph.add_edge("discover", "plan")
        graph.add_edge("plan", "preflight")
        graph.add_edge("preflight", END)
        return graph.compile()

    async def run(
        self, run_id: str, request: UnderstandingInput, capabilities: dict[str, Any]
    ) -> PlanningResult:
        state: _State = await self._graph.ainvoke(
            {"run_id": run_id, "request": request, "capabilities": capabilities}
        )
        intent = state["intent"]
        if "plan" not in state:
            return PlanningResult(outcome="needs_clarification", intent=intent)
        issues = state.get("issues", [])
        # Step-level errors only disable that step; plan-level errors block the run.
        invalid_steps = {i.operation_id for i in issues if i.severity == "error" and i.operation_id}
        blocked = any(i.severity == "error" and i.operation_id is None for i in issues) or (
            bool(state["plan"].operations)
            and invalid_steps >= {op.id for op in state["plan"].operations}
        )
        return PlanningResult(
            outcome="blocked" if blocked else "planned",
            intent=intent,
            plan=state["plan"],
            issues=issues,
            checks=state.get("checks", {}),
        )

    # --- nodes ------------------------------------------------------------------------------

    async def _understand(self, state: _State) -> _State:
        await self._sink.run_progress(
            state["run_id"],
            current_agent=self._agents.understanding.name,
            message="Understanding the request",
        )
        return {"intent": await self._agents.understanding.run(state["request"])}

    @staticmethod
    def _after_understand(state: _State) -> str:
        intent = state["intent"]
        return (
            "continue" if intent.is_actionable or not intent.clarification_questions else "clarify"
        )

    async def _discover(self, state: _State) -> _State:
        products = state["capabilities"].get("products") or {}
        workspace: dict[str, Any] = {}
        for product, (operation, params, key) in _DISCOVERY.items():
            if not products.get(product):
                continue
            agent = self._agents.for_operation(operation)
            await self._sink.run_progress(
                state["run_id"],
                current_agent=agent.name,
                message=f"Reading existing {product} resources",
            )
            outcome = await agent.run(
                OperationRequest(
                    run_id=state["run_id"],
                    op_id="discovery",
                    operation=operation,
                    params=params,
                )
            )
            items = outcome.outputs.get(key, []) if outcome.succeeded else []
            workspace[f"{product}_{key}"] = [
                {
                    k: i.get(k)
                    for k in (
                        "key",
                        "name",
                        "id",
                        "project_key",
                        "project_name",
                        "managed",
                        "issue_types",
                    )
                    if i.get(k)
                }
                for i in items
            ]
        return {"workspace": workspace}

    async def _plan(self, state: _State) -> _State:
        await self._sink.run_progress(
            state["run_id"],
            current_agent=self._agents.planning.name,
            message="Building the execution plan",
        )
        plan = await self._agents.planning.run(
            PlanningInput(
                intent=state["intent"],
                request_text="\n\n".join(
                    [t.content for t in state["request"].history if t.role == "user"]
                    + [state["request"].text]
                ),
                catalog=describe_catalog(),
                capabilities=state["capabilities"],
                workspace=state.get("workspace", {}),
                max_operations=self._max_operations,
            )
        )
        return {"plan": plan}

    async def _repair(
        self, state: _State, op: PlannedOperation, error: str
    ) -> OperationOutcome | None:
        """Ask the repair agent for corrected params and re-check; None when not fixed."""
        if self._agents.repair is None or _not_repairable(error):
            return None
        try:
            fix = await self._agents.repair.run(
                StepRepairInput(
                    instruction=state["request"].text,
                    operation=op.operation,
                    description=op.description,
                    params=op.params,
                    error=error,
                    facts=json.dumps(state.get("workspace", {}), ensure_ascii=False),
                )
            )
        except LLMError:
            return None
        spec = get_spec(op.operation)
        if not fix.fixable or fix.params == op.params or spec is None:
            return None
        if param_errors(spec.params, fix.params):
            return None
        agent = self._agents.for_operation(op.operation)
        result = await agent.run(
            OperationRequest(
                run_id=state["run_id"],
                op_id=op.id,
                operation=op.operation,
                params=fix.params,
                mode="check",
            )
        )
        if result.conflict:
            return None
        op.params = fix.params
        state["plan"].assumptions.append(
            f"{op.id} auto-corrected after Jira rejected it ({error[:120]}): {fix.explanation}"
        )
        return result

    async def _preflight(self, state: _State) -> _State:
        plan = state["plan"]
        named = fill_missing_names(plan)
        if named:
            plan.assumptions.append(
                f"Steps {', '.join(named)} had no name; their description is used as the name."
            )
        issues = validate_plan(plan, state["capabilities"], self._max_operations)
        checks: dict[str, OperationOutcome] = {}
        invalid_ops = {i.operation_id for i in issues if i.severity == "error"}
        repairs = 0
        for op in plan.operations:
            spec = get_spec(op.operation)
            if (
                spec is None
                or not spec.supported
                or op.id in invalid_ops
                or contains_ref(op.params)
            ):
                continue
            agent = self._agents.for_operation(op.operation)
            await self._sink.run_progress(
                state["run_id"],
                current_agent=agent.name,
                message=f"Preflight check {op.id} {op.operation}",
            )
            result = await agent.run(
                OperationRequest(
                    run_id=state["run_id"],
                    op_id=op.id,
                    operation=op.operation,
                    params=op.params,
                    mode="check",
                )
            )
            if result.conflict and repairs < MAX_PLAN_REPAIRS:
                fixed = await self._repair(state, op, result.message)
                if fixed is not None:
                    repairs += 1
                    result = fixed
            checks[op.id] = result
            if result.conflict:
                issues.append(
                    PlanIssue(severity="error", operation_id=op.id, message=result.message)
                )
            elif not result.succeeded and result.error_code:
                issues.append(
                    PlanIssue(
                        severity="warning",
                        operation_id=op.id,
                        message=f"Preflight could not check: {result.message}",
                    )
                )
        return {"issues": issues, "checks": checks}
